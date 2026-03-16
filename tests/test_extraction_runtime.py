"""Tests for shared extraction runtime wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from finding_extractor.extractor.orchestrator import (
    ExtractionReviewDecision,
    OrchestrationResult,
)
from finding_extractor.extractor.runtime import run_extraction_runtime
from finding_extractor.models import ExamInfo, ExtractedReportFindings, PipelineDiagnostics


def _empty_orchestrated_result() -> OrchestrationResult:
    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="CT"),
        findings=[],
        non_finding_text=[],
    )
    return OrchestrationResult(
        extraction=extraction,
        usage=None,
        validation_result=None,
        pipeline_diagnostics=PipelineDiagnostics(
            mode="modular",
            total_chunks=1,
            initial_failed_chunks=0,
            remaining_failed_chunks=0,
            total_chunk_attempts=1,
            failed_chunk_ids=(),
            failed_chunk_error_types=(),
        ),
    )


def _runtime_settings(**overrides):
    base = {
        "default_model": "openai:gpt-5-mini",
        "fallback_model": "openai:gpt-5.2",
        "allow_unknown_model_reasoning": False,
        "reviewer_enabled": True,
        "reviewer_model": None,
        "reviewer_reasoning": "minimal",
        "reviewer_reextract_enabled": True,
        "extractor_max_subagent_concurrency": 5,
        "chunking_semantic_trigger_sentence_count": 4,
        "chunking_semantic_embedding_model": "minishlab/potion-base-32M",
        "chunking_semantic_threshold": 0.8,
        "chunking_semantic_chunk_size": 2048,
        "chunking_semantic_similarity_window": 3,
        "chunking_semantic_skip_window": 0,
        "chunking_impression_list_chunking_enabled": True,
        "chunking_impression_list_max_items_per_chunk": 3,
        "chunking_impression_list_min_items_per_chunk": 2,
        "subagent_timeout_seconds": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_runtime_enables_reviewer_without_reviewer_model(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(

        reviewer_model=None,
        reviewer_reextract_enabled=True,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-5-mini",
        reasoning=None,
        validate=False,
        settings=settings,
    )

    assert observed["review_chunks_fn"] is not None
    assert observed["reviewer_reextract_enabled"] is True


@pytest.mark.asyncio
async def test_runtime_normalizes_extraction_reasoning_for_openai_gpt52(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=False,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-5.2",
        reasoning="minimal",
        validate=False,
        settings=settings,
    )

    assert observed["reasoning"] == "low"


@pytest.mark.asyncio
async def test_runtime_normalizes_reviewer_reasoning_for_openai_gpt52(monkeypatch):
    observed: dict[str, object] = {}
    captured_review_args: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    async def _fake_review_extraction_chunk(**kwargs):
        captured_review_args.update(kwargs)
        return ExtractionReviewDecision(report_chunk_id=kwargs["report_chunk_id"])

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )
    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.review_extraction_chunk",
        _fake_review_extraction_chunk,
    )

    settings = _runtime_settings(
        reviewer_enabled=True,
        reviewer_model="openai:gpt-5.2",
        reviewer_reasoning="minimal",
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-5-mini",
        reasoning=None,
        validate=False,
        settings=settings,
    )

    review_chunks_fn = observed["review_chunks_fn"]
    assert review_chunks_fn is not None
    await review_chunks_fn(
        report_chunk_id="findings_1",
        section_name="findings",
        chunk_text="No acute findings.",
        preceding_chunk_context=None,
        following_chunk_context=None,
        chunk_extraction=_empty_orchestrated_result().extraction,
        exam_info=ExamInfo(study_description="CT"),
    )

    assert captured_review_args["model_name"] == "openai:gpt-5.2"
    assert captured_review_args["reasoning"] == "low"


@pytest.mark.asyncio
async def test_runtime_disables_reviewer_when_flag_off(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=False,
        reviewer_reextract_enabled=False,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-5-mini",
        reasoning=None,
        validate=False,
        settings=settings,
    )

    assert observed["review_chunks_fn"] is None
    assert observed["reviewer_reextract_enabled"] is False


@pytest.mark.asyncio
async def test_runtime_keeps_reviewer_when_reextract_disabled(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(

        reviewer_reextract_enabled=False,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-5-mini",
        reasoning=None,
        validate=False,
        settings=settings,
    )

    assert observed["review_chunks_fn"] is not None
    assert observed["reviewer_reextract_enabled"] is False


@pytest.mark.asyncio
async def test_runtime_rejects_unknown_model_reasoning_when_override_disabled(monkeypatch):
    async def _fake_orchestrator(**kwargs):  # noqa: ARG001
        raise AssertionError("orchestrator should not be called")

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=False,
        allow_unknown_model_reasoning=False,
    )

    with pytest.raises(ValueError, match="Cannot verify reasoning compatibility"):
        await run_extraction_runtime(
            report_text="Findings:\nNo acute findings.",
            study_description=None,
            model="openai:gpt-6",
            reasoning="minimal",
            validate=False,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_runtime_allows_unknown_model_reasoning_with_override(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=False,
        allow_unknown_model_reasoning=True,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description=None,
        model="openai:gpt-6",
        reasoning="minimal",
        validate=False,
        settings=settings,
    )

    assert observed["reasoning"] == "minimal"


@pytest.mark.asyncio
async def test_runtime_rejects_reviewer_model_matching_extraction_model(monkeypatch):
    async def _fake_orchestrator(**kwargs):  # noqa: ARG001
        raise AssertionError("orchestrator should not be called")

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=True,
        reviewer_model="openai:gpt-5-mini",
    )

    with pytest.raises(ValueError, match="reviewer_model must differ"):
        await run_extraction_runtime(
            report_text="Findings:\nNo acute findings.",
            study_description=None,
            model="openai:gpt-5-mini",
            reasoning=None,
            validate=False,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_runtime_rejects_reviewer_when_no_alternate_model_available(monkeypatch):
    async def _fake_orchestrator(**kwargs):  # noqa: ARG001
        raise AssertionError("orchestrator should not be called")

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(
        reviewer_enabled=True,
        reviewer_model=None,
        fallback_model="openai:gpt-5-mini",
    )

    with pytest.raises(ValueError, match="Reviewer review requires a model different"):
        await run_extraction_runtime(
            report_text="Findings:\nNo acute findings.",
            study_description=None,
            model="openai:gpt-5-mini",
            reasoning=None,
            validate=False,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_runtime_forwards_source_ref_to_exam_info_path(monkeypatch):
    observed: dict[str, object] = {}

    async def _fake_orchestrator(**kwargs):
        observed.update(kwargs)
        return _empty_orchestrated_result()

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.run_orchestrated_extraction",
        _fake_orchestrator,
    )

    settings = _runtime_settings(

        reviewer_reextract_enabled=True,
    )

    await run_extraction_runtime(
        report_text="Findings:\nNo acute findings.",
        study_description="CT Chest",
        model="openai:gpt-5-mini",
        reasoning=None,
        validate=False,
        source_ref="sample_data/example2/ct_chest_foo.md",
        report_id="report-123",
        settings=settings,
    )

    assert observed["source_ref"] == "sample_data/example2/ct_chest_foo.md"
    assert observed["external_metadata"] == {"report_id": "report-123"}
    assert observed["review_chunks_fn"] is not None
