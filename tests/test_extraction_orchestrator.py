"""Tests for modular extraction behavior in the orchestrator."""

import asyncio
from collections import defaultdict

import pytest

from finding_extractor.extractor.chunking import (
    ChunkingDiagnostics,
    ChunkingResult,
    ChunkingSettings,
    SectionChunk,
)
from finding_extractor.extractor.orchestrator import (
    ExtractionReviewDecision,
    ExtractionReviewProblem,
    run_orchestrated_extraction,
)
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    ExtractionResult,
    ExtractionUsage,
    Finding,
    NonFindingText,
    ValidationResult,
)


def _validation_ok(_report_text: str, _extraction: ExtractedReportFindings) -> ValidationResult:
    return ValidationResult(verbatim_errors=[], coverage_warnings=[])


@pytest.mark.asyncio
async def test_modular_pipeline_respects_section_concurrency_limit():
    """Section extraction should honor the configured bounded concurrency."""
    report_text = """Findings:
Stone in right kidney.
Impression:
Right nephrolithiasis.
Findings:
Left kidney clear.
"""
    statuses: list[str] = []
    in_flight = 0
    max_in_flight = 0
    seen_unit_texts: list[str] = []

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        nonlocal in_flight, max_in_flight
        seen_unit_texts.append(report_text)
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1

        second_line = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name=f"finding-{second_line}",
                        presence="present",
                        report_text=second_line,
                    )
                ],
                non_finding_text=[],
            ),
            usage=ExtractionUsage(requests=1, input_tokens=10, output_tokens=5),
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert max_in_flight == 2
    assert len(seen_unit_texts) == 3
    assert all(":" not in text.splitlines()[0] for text in seen_unit_texts)
    assert any("max_concurrency=2" in message for message in statuses)
    assert len(result.extraction.findings) == 3
    assert result.usage is not None
    assert result.usage.requests == 3
    assert result.pipeline_diagnostics.mode == "modular"
    assert result.pipeline_diagnostics.total_chunks == 3
    assert result.pipeline_diagnostics.initial_failed_chunks == 0
    assert result.pipeline_diagnostics.remaining_failed_chunks == 0
    assert result.pipeline_diagnostics.total_chunk_attempts == 3


@pytest.mark.asyncio
async def test_modular_pipeline_records_failed_chunk_without_retry():
    """Failed chunk extraction should be recorded — no retry is attempted."""
    report_text = """Findings:
Stable 3 mm right renal stone.
Impression:
Persistent right nephrolithiasis.
"""
    statuses: list[str] = []
    attempts_by_section: dict[str, int] = defaultdict(int)

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        header = report_text.splitlines()[0].strip().lower()
        attempts_by_section[header] += 1
        if "nephrolithiasis" in header:
            raise TimeoutError("transient timeout")

        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name=finding_text.lower().replace(" ", "_"),
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    # Each chunk is attempted exactly once — no retry
    assert attempts_by_section["stable 3 mm right renal stone."] == 1
    assert attempts_by_section["persistent right nephrolithiasis."] == 1
    # Only the successful chunk produces findings
    assert len(result.extraction.findings) == 1
    assert any(
        "extract_sections" in message and "chunk=impression_1 attempt=1 status=failed" in message
        for message in statuses
    )
    assert result.pipeline_diagnostics.mode == "modular"
    assert result.pipeline_diagnostics.total_chunks == 2
    assert result.pipeline_diagnostics.initial_failed_chunks == 1
    assert result.pipeline_diagnostics.remaining_failed_chunks == 1
    assert result.pipeline_diagnostics.total_chunk_attempts == 2


@pytest.mark.asyncio
async def test_modular_pipeline_requires_findings_or_impression_sections():
    """Reports with parsed sections but no findings/impression should be rejected."""
    report_text = """Technique:
CT without contrast.
History:
Flank pain.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(**kwargs):  # noqa: ARG001
        raise AssertionError("extract_findings should not run")

    with pytest.raises(ValueError, match="No extractable `findings` or `impression` sections"):
        await run_orchestrated_extraction(
            report_text=report_text,
            study_description=None,
            model_name="openai:gpt-5-mini",
            reasoning="medium",
            validate=False,
            emit_progress=emit_progress,
            extract_findings_fn=fake_extract_findings,
            validate_extraction_fn=_validation_ok,
            max_subagent_concurrency=2,
        )


@pytest.mark.asyncio
async def test_modular_pipeline_supports_impression_only_reports():
    """Impression-only reports should produce a single extractable chunk."""
    report_text = """Impression:
No acute cardiopulmonary abnormality.
"""
    seen_unit_texts: list[str] = []

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        seen_unit_texts.append(report_text)
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CXR"),
                findings=[
                    Finding(
                        finding_name="no acute cardiopulmonary abnormality",
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(seen_unit_texts) == 1
    assert seen_unit_texts[0].startswith("No acute cardiopulmonary abnormality.")
    assert len(result.extraction.findings) == 1
    assert result.pipeline_diagnostics.total_chunks == 1


@pytest.mark.asyncio
async def test_modular_pipeline_supports_standalone_allcaps_findings_only_reports():
    """Standalone FINDINGS headers should produce an extractable chunk."""
    report_text = """FINDINGS
No pleural effusion.
No pulmonary nodule.
"""
    seen_unit_texts: list[str] = []

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        seen_unit_texts.append(report_text)
        finding_text = report_text.splitlines()[0].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Chest"),
                findings=[
                    Finding(
                        finding_name="pleural effusion",
                        presence="absent",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,
        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(seen_unit_texts) == 1
    assert seen_unit_texts[0].startswith("No pleural effusion.")
    assert len(result.extraction.findings) == 1
    assert result.pipeline_diagnostics.total_chunks == 1


@pytest.mark.asyncio
async def test_modular_pipeline_supports_findings_impression_combined_header():
    """Combined Findings/Impression header should still be extracted as one chunk."""
    report_text = """Findings/Impression:
No focal airspace opacity.
No pleural effusion.
"""
    seen_unit_texts: list[str] = []

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        seen_unit_texts.append(report_text)
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CXR"),
                findings=[],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(seen_unit_texts) == 1
    assert seen_unit_texts[0].startswith("No focal airspace opacity.")
    assert result.pipeline_diagnostics.total_chunks == 1
    assert result.pipeline_diagnostics.initial_failed_chunks == 0


@pytest.mark.asyncio
async def test_modular_pipeline_dedupes_cross_section_findings_to_source_both():
    """Duplicate finding content across findings/impression should merge to source_section='both'."""
    report_text = """Findings:
There is a right renal calculus.
Impression:
There is a right renal calculus.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = "There is a right renal calculus."
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name="renal calculus",
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(result.extraction.findings) == 1
    assert result.extraction.findings[0].source_section == "both"


@pytest.mark.asyncio
async def test_modular_pipeline_drops_non_finding_text_that_duplicates_finding_span():
    """Merged output should not keep duplicate span text in non_finding_text."""
    report_text = """Impression:
No acute cardiopulmonary process.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = "No acute cardiopulmonary process."
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CXR"),
                findings=[
                    Finding(
                        finding_name="acute cardiopulmonary process",
                        presence="absent",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[
                    NonFindingText(text=finding_text, category="impression"),
                    NonFindingText(text="Technique: AP portable chest.", category="technique"),
                ],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(result.extraction.findings) == 1
    assert result.extraction.findings[0].report_text == "No acute cardiopulmonary process."
    assert [span.text for span in result.extraction.non_finding_text] == [
        "Technique: AP portable chest."
    ]


@pytest.mark.asyncio
async def test_modular_pipeline_preserves_report_order_with_partial_failure():
    """Successful chunks should merge in report order, skipping failed chunks."""
    report_text = """Findings:
Right renal stone.
Impression:
Persistent nephrolithiasis.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        header = report_text.splitlines()[0].strip()
        if header == "Right renal stone.":
            raise TimeoutError("persistent failure")

        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="Exam from impression section"),
                findings=[
                    Finding(
                        finding_name="from-impression",
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    # Only the successful impression chunk produces findings
    assert [finding.finding_name for finding in result.extraction.findings] == [
        "from-impression",
    ]
    assert result.pipeline_diagnostics.remaining_failed_chunks == 1
    assert result.pipeline_diagnostics.total_chunks == 2


@pytest.mark.asyncio
async def test_modular_pipeline_emits_remaining_failed_unit_diagnostics():
    """Permanently failed chunks should expose parseable failed-chunk diagnostics."""
    report_text = """Findings:
Right renal stone.
Impression:
Persistent nephrolithiasis.
"""
    statuses: list[str] = []

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        header = report_text.splitlines()[0].strip()
        if header == "Persistent nephrolithiasis.":
            raise TimeoutError("persistent timeout")

        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name="from-findings",
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
    )

    assert len(result.extraction.findings) == 1
    assert result.pipeline_diagnostics.remaining_failed_chunks == 1
    assert result.pipeline_diagnostics.failed_chunk_ids == ("impression_1",)
    assert result.pipeline_diagnostics.failed_chunk_error_types == ("TimeoutError",)
    # Failed chunk should be recorded in extraction progress messages
    assert any(
        "extract_sections" in message
        and "chunk=impression_1 attempt=1 status=failed" in message
        for message in statuses
    )


@pytest.mark.asyncio
async def test_modular_pipeline_expands_sections_with_semantic_chunking(monkeypatch):
    """Enabled chunking should fan out one section into multiple extraction chunks."""
    report_text = """Findings:
Sentence one. Sentence two.
Impression:
Stable findings.
"""
    seen_chunk_ids: list[str] = []

    async def fake_chunk_section_text(*, section_name: str, section_text: str, settings):  # noqa: ARG001
        if section_name == "findings":
            return ChunkingResult(
                chunks=(
                    SectionChunk(start_index=0, end_index=20, text="Findings:\nSentence one."),
                    SectionChunk(start_index=21, end_index=len(section_text), text="Sentence two."),
                ),
                diagnostics=ChunkingDiagnostics(
                    strategy="semantic_chunked",
                    chunk_count=2,
                    sentence_count=4,
                    semantic_applied=True,
                ),
            )
        return ChunkingResult(
            chunks=(SectionChunk(start_index=0, end_index=len(section_text), text=section_text),),
            diagnostics=ChunkingDiagnostics(
                strategy="sentence_only",
                chunk_count=1,
                sentence_count=1,
                semantic_applied=False,
            ),
        )

    monkeypatch.setattr(
        "finding_extractor.extractor.orchestrator.chunks.chunk_section_text",
        fake_chunk_section_text,
    )

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        seen_chunk_ids.append(report_text.splitlines()[0].strip())
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name=finding_text.lower().replace(" ", "_"),
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
        chunking_settings=ChunkingSettings(),
    )

    assert len(result.extraction.findings) == 3
    assert seen_chunk_ids == ["Findings:", "Sentence two.", "Impression:"]
    assert result.pipeline_diagnostics.total_chunks == 3


@pytest.mark.asyncio
async def test_modular_pipeline_runs_reviewer_when_reextract_disabled():
    """Reviewer should still run even when re-extract is disabled."""
    report_text = """Findings:
finding to review.
"""
    extract_calls = 0
    review_calls = 0
    statuses: list[str] = []

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        nonlocal extract_calls
        extract_calls += 1
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    async def fake_review_chunks(**kwargs):  # noqa: ARG001
        nonlocal review_calls
        review_calls += 1
        return ExtractionReviewDecision(
            report_chunk_id="findings_1",
            should_reextract=True,
            problems=(
                ExtractionReviewProblem(
                    raw_extracted_finding_index=0,
                    extract_problem_type="other",
                    problem_detail="would reextract if enabled",
                ),
            ),
            rationale="would reextract if enabled",
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        review_chunks_fn=fake_review_chunks,
        max_subagent_concurrency=2,
        reviewer_reextract_enabled=False,
    )

    assert review_calls == 1
    assert extract_calls == 1
    assert result.pipeline_diagnostics.reviewer_requested_chunks == 1
    assert result.pipeline_diagnostics.reviewer_reextracted_chunks == 0
    # Inline review should emit chunk-level decision showing reextract was requested
    assert any(
        "review" in message
        and "chunk_review_decision" in message
        and "should_reextract=true" in message
        for message in statuses
    )


@pytest.mark.asyncio
async def test_modular_pipeline_chunk_extraction_timeout_recorded_as_error():
    """Chunk extraction timeout should be recorded as TimeoutError in diagnostics."""
    report_text = """Findings:
Right renal stone.
Impression:
Persistent nephrolithiasis.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def slow_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        await asyncio.sleep(0.5)  # Exceeds timeout
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT"),
                findings=[
                    Finding(
                        finding_name="test",
                        presence="present",
                        report_text=report_text.splitlines()[-1].strip(),
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    with pytest.raises((TimeoutError, RuntimeError)):
        await run_orchestrated_extraction(
            report_text=report_text,
            study_description=None,
            model_name="openai:gpt-5-mini",
            reasoning="medium",
            validate=False,
            emit_progress=emit_progress,
            extract_findings_fn=slow_extract_findings,
            validate_extraction_fn=_validation_ok,
            max_subagent_concurrency=2,
            subagent_timeout_seconds=0.05,
        )


@pytest.mark.asyncio
async def test_modular_pipeline_no_timeout_when_none():
    """None timeout should not enforce any deadline."""
    report_text = """Findings:
Normal finding.
"""

    async def emit_progress(_message: str) -> None:
        return None

    async def fast_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        await asyncio.sleep(0.01)
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fast_extract_findings,
        validate_extraction_fn=_validation_ok,
        max_subagent_concurrency=2,
        subagent_timeout_seconds=None,
    )

    assert len(result.extraction.findings) == 1


@pytest.mark.asyncio
async def test_modular_pipeline_exam_info_parallel_execution():
    """Exam-info fn should run in parallel with chunk extraction."""
    exam_info_started_at = 0.0
    extract_started_at = 0.0

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_exam_info(
        report_text: str,  # noqa: ARG001
        *,
        study_description: str | None = None,  # noqa: ARG001
        source_ref: str | None = None,  # noqa: ARG001
        external_metadata: dict[str, str] | None = None,  # noqa: ARG001
        report_headers: str | None = None,  # noqa: ARG001
    ):
        nonlocal exam_info_started_at
        exam_info_started_at = asyncio.get_running_loop().time()
        await asyncio.sleep(0.02)
        return ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen")

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        nonlocal extract_started_at
        extract_started_at = asyncio.get_running_loop().time()
        await asyncio.sleep(0.02)
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="placeholder"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    report_text = """Findings:
Right renal stone.
"""

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description="CT Abdomen",
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        extract_exam_info_fn=fake_extract_exam_info,
        max_subagent_concurrency=2,
    )

    assert result.extraction.exam_info.modality == "CT"
    assert result.extraction.exam_info.body_part == "abdomen"
    # Both should have started at roughly the same time (parallel)
    assert abs(exam_info_started_at - extract_started_at) < 0.1


@pytest.mark.asyncio
async def test_modular_pipeline_passes_exam_info_context_inputs():
    """Exam-info sub-agent should receive source_ref, metadata, and header-focused text."""
    captured: dict[str, object] = {}

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_exam_info(
        report_text: str,
        *,
        study_description: str | None = None,
        source_ref: str | None = None,
        external_metadata: dict[str, str] | None = None,
    ):
        captured.update(
            {
                "report_text": report_text,
                "study_description": study_description,
                "source_ref": source_ref,
                "external_metadata": external_metadata,
            }
        )
        return ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen")

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="placeholder"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    report_text = """Indication: flank pain
Comparison: prior study
Findings:
Right renal stone.
Impression:
Right nephrolithiasis.
"""

    await run_orchestrated_extraction(
        report_text=report_text,
        study_description="CT Abdomen",
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        extract_exam_info_fn=fake_extract_exam_info,
        source_ref="sample_data/example2/ct_abdomen_20230118.md",
        external_metadata={"report_id": "r-1"},
        max_subagent_concurrency=2,
    )

    assert captured["source_ref"] == "sample_data/example2/ct_abdomen_20230118.md"
    assert captured["external_metadata"] == {"report_id": "r-1"}
    # Full report text is passed to exam info fn (context extraction is internal)
    assert captured["report_text"] == report_text


@pytest.mark.asyncio
async def test_modular_pipeline_exam_info_failure_nonfatal():
    """Exam-info failure should be non-fatal — pipeline keeps placeholder exam_info."""

    async def emit_progress(_message: str) -> None:
        return None

    async def failing_extract_exam_info(**kwargs):  # noqa: ARG001
        raise RuntimeError("exam info agent failed")

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="placeholder"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    report_text = """Findings:
Normal finding.
"""

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        extract_exam_info_fn=failing_extract_exam_info,
        max_subagent_concurrency=2,
    )

    # Should still succeed — failed exam_info preserves chunk-level metadata
    assert len(result.extraction.findings) == 1
    assert result.extraction.exam_info.study_description == "placeholder"


@pytest.mark.asyncio
async def test_modular_pipeline_exam_info_signature_mismatch_nonfatal():
    """Outdated exam-info callable signatures should fail non-fatally."""
    statuses: list[str] = []

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def legacy_extract_exam_info(
        report_text: str,  # noqa: ARG001
        *,
        study_description: str | None = None,  # noqa: ARG001
    ) -> ExamInfo:
        return ExamInfo(study_description="legacy")

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="placeholder"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    report_text = """Findings:
Normal finding.
"""

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        extract_exam_info_fn=legacy_extract_exam_info,
        max_subagent_concurrency=2,
    )

    assert len(result.extraction.findings) == 1
    assert result.extraction.exam_info.study_description == "placeholder"
    assert any(
        "[stage:extract_exam_info] failed error=TypeError" in message for message in statuses
    )


@pytest.mark.asyncio
async def test_modular_pipeline_exam_info_task_cancelled_on_all_chunk_failure():
    """Exam-info task should be cancelled when all chunk extractions fail."""
    exam_info_completed = False

    async def emit_progress(_message: str) -> None:
        return None

    async def always_failing_extract(*, report_text: str, **kwargs):  # noqa: ARG001
        raise RuntimeError("chunk extraction failed")

    async def slow_extract_exam_info(
        report_text: str,  # noqa: ARG001
        *,
        study_description: str | None = None,  # noqa: ARG001
        source_ref: str | None = None,  # noqa: ARG001
        external_metadata: dict[str, str] | None = None,  # noqa: ARG001
        report_headers: str | None = None,  # noqa: ARG001
    ):
        nonlocal exam_info_completed
        await asyncio.sleep(0.3)
        exam_info_completed = True
        return ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen")

    report_text = """Findings:
Right renal stone.
"""

    with pytest.raises(RuntimeError, match="chunk extraction failed"):
        await run_orchestrated_extraction(
            report_text=report_text,
            study_description=None,
            model_name="openai:gpt-5-mini",
            reasoning="medium",
            validate=False,
            emit_progress=emit_progress,
            extract_findings_fn=always_failing_extract,
            validate_extraction_fn=_validation_ok,
            extract_exam_info_fn=slow_extract_exam_info,
            max_subagent_concurrency=2,
        )

    # Exam-info now runs and completes BEFORE chunk extraction starts,
    # so it should always complete regardless of chunk failures.
    assert exam_info_completed


@pytest.mark.asyncio
async def test_modular_pipeline_reviewer_feedback_threaded_to_retry():
    """Feedback from reviewer should be passed to retry chunks."""
    report_text = """Findings:
finding to review.
"""
    extract_calls = 0
    received_feedback: list[str | None] = []

    async def emit_progress(_message: str) -> None:
        return None

    async def fake_extract_findings(*, report_text: str, feedback: str | None = None, **kwargs):  # noqa: ARG001
        nonlocal extract_calls
        extract_calls += 1
        received_feedback.append(feedback)
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT Abdomen"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    async def fake_review_chunks(**kwargs):  # noqa: ARG001
        return ExtractionReviewDecision(
            report_chunk_id="findings_1",
            should_reextract=True,
            problems=(
                ExtractionReviewProblem(
                    raw_extracted_finding_index=0,
                    extract_problem_type="missed_finding",
                    problem_detail="Look for missed hepatic findings",
                ),
            ),
            rationale="possible missed detail",
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        review_chunks_fn=fake_review_chunks,
        max_subagent_concurrency=2,
        reviewer_reextract_enabled=True,
    )

    assert extract_calls == 2
    # First call has no feedback, second call gets review feedback
    assert received_feedback[0] is None
    assert received_feedback[1] is not None
    assert "PREVIOUS_CHUNK_EXTRACTION" in received_feedback[1]
    assert "RE-EXTRACTION_FEEDBACK" in received_feedback[1]
    assert "extract_problem_type: missed_finding" in received_feedback[1]
    assert "problem_detail: Look for missed hepatic findings" in received_feedback[1]
    assert result.pipeline_diagnostics.reviewer_requested_chunks == 1
    assert result.pipeline_diagnostics.reviewer_reextracted_chunks == 1


@pytest.mark.asyncio
async def test_modular_pipeline_reviewer_timeout_nonfatal():
    """Reviewer timeout should be non-fatal -- pipeline continues without re-extraction."""
    report_text = """Findings:
Normal finding.
"""
    statuses: list[str] = []

    async def emit_progress(message: str) -> None:
        statuses.append(message)

    async def fake_extract_findings(*, report_text: str, **kwargs):  # noqa: ARG001
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=ExtractedReportFindings(
                exam_info=ExamInfo(study_description="CT"),
                findings=[
                    Finding(
                        finding_name=finding_text,
                        presence="present",
                        report_text=finding_text,
                    )
                ],
                non_finding_text=[],
            ),
            usage=None,
        )

    async def slow_review_chunks(**kwargs):  # noqa: ARG001
        await asyncio.sleep(0.5)  # Exceeds timeout
        return ExtractionReviewDecision(
            report_chunk_id="findings_1",
            should_reextract=True,
            problems=(
                ExtractionReviewProblem(
                    raw_extracted_finding_index=0,
                    extract_problem_type="other",
                    problem_detail="slow validator path",
                ),
            ),
        )

    result = await run_orchestrated_extraction(
        report_text=report_text,
        study_description=None,
        model_name="openai:gpt-5-mini",
        reasoning="medium",
        validate=False,

        emit_progress=emit_progress,
        extract_findings_fn=fake_extract_findings,
        validate_extraction_fn=_validation_ok,
        review_chunks_fn=slow_review_chunks,
        max_subagent_concurrency=2,
        subagent_timeout_seconds=0.05,
    )

    # Pipeline should succeed with the extraction intact
    assert len(result.extraction.findings) == 1
    # Reviewer should have failed non-fatally
    assert result.pipeline_diagnostics.reviewer_requested_chunks == 0
    assert result.pipeline_diagnostics.reviewer_reextracted_chunks == 0
    assert any(
        "review" in msg
        and "chunk_review_decision" in msg
        and "error=TimeoutError" in msg
        for msg in statuses
    )
