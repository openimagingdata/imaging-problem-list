"""Tests for coding runtime orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from finding_extractor.coding.runtime import _location_term_fallback, run_coding
from finding_extractor.coding.types import (
    FindingCodeSelection,
    FindingTerms,
    FindingTermsBatchOutput,
    LocationCodeSelection,
    LocationTerms,
    LocationTermsBatchOutput,
)
from finding_extractor.models import ExamInfo, ExtractedReportFindings, Finding, FindingLocation


def _settings(**overrides):
    base = {
        "coding_model": "openai:gpt-5.2",
        "coding_reasoning": "low",
        "coding_term_model": None,
        "allow_unknown_model_reasoning": False,
        "coding_fallback_model": "google-gla:gemini-3.1-flash-lite-preview",
        "coding_max_concurrency": 8,
        "coding_search_limit": 6,
        "coding_max_candidates": 12,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _UnusedAgent:
    async def run(self, prompt):  # noqa: ARG002
        raise AssertionError("LLM agent should not be called for full fast-path resolution")


class _FakeFindingIndex:
    async def get(self, key: str):
        if key == "renal calculus":
            return SimpleNamespace(oifm_id="OIFM:1", name="renal calculus")
        return None

    async def search_batch(self, queries, limit):  # noqa: ARG002
        raise AssertionError("finding search should not run when fast-path resolves every finding")


class _FakeLocationIndex:
    def get(self, key: str):
        if key == "right kidney":
            return SimpleNamespace(
                id="LOC:RIGHT_KIDNEY",
                description="right kidney",
                region="abdomen",
                laterality="right",
                containment_parent=None,
                partof_parent=None,
            )
        raise KeyError(key)

    async def search_batch(self, queries, limit):  # noqa: ARG002
        raise AssertionError("location search should not run when fast-path resolves every finding")


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def update_extraction_coding(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FixedOutputAgent:
    def __init__(self, output) -> None:
        self.output = output

    async def run(self, prompt):  # noqa: ARG002
        return SimpleNamespace(output=self.output)


class _FirstCandidateFindingSelector:
    async def run(self, prompt: str):
        first_id = next(
            line.split(". ", maxsplit=1)[1]
            for line in prompt.splitlines()
            if line.startswith("1. OIFM:")
        )
        return SimpleNamespace(
            output=FindingCodeSelection(
                oifm_id=first_id,
                reasoning="Selected first candidate for test coverage.",
            )
        )


class _FirstCandidateLocationSelector:
    async def run(self, prompt: str):
        first_id = next(
            line.split(". ", maxsplit=1)[1]
            for line in prompt.splitlines()
            if line.startswith("1. LOC:")
        )
        return SimpleNamespace(
            output=LocationCodeSelection(
                location_ids=[first_id],
                reasoning="Selected first candidate for test coverage.",
            )
        )


class _InvalidFindingSelector:
    async def run(self, prompt: str):  # noqa: ARG002
        return SimpleNamespace(
            output=FindingCodeSelection(
                oifm_id="OIFM:NOT_IN_SET",
                reasoning="Returning invalid ID for validation coverage.",
            )
        )


@contextmanager
def _null_span(*args, **kwargs):  # noqa: ARG001
    yield SimpleNamespace(set_attribute=lambda *a, **k: None)


@pytest.mark.asyncio
async def test_run_coding_applies_fast_path_to_duplicate_findings(monkeypatch):
    """Duplicate findings sharing the same lookup key are all updated from one fast-path hit."""
    monkeypatch.setattr("finding_extractor.coding.runtime.Index", _FakeFindingIndex)
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.AnatomicLocationIndex",
        _FakeLocationIndex,
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.build_coding_model_runtime",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_term_agent",
        lambda runtime, **kw: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_term_agent",
        lambda runtime, **kw: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.resolve_runtime_reasoning",
        lambda model_name, reasoning, allow_unknown_model_reasoning: reasoning,
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.get_current_trace_id",
        lambda: "trace-123",
    )
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.span", _null_span)
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.info", lambda *args, **kwargs: None)

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(
            study_description="CT Abdomen and Pelvis With Contrast",
            modality="CT",
            body_part="abdomen, pelvis",
        ),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="right kidney",
                    laterality="right",
                ),
                report_text="3 mm stone in the right kidney.",
            ),
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="right kidney",
                    laterality="right",
                ),
                report_text="Additional punctate calculus in the right kidney.",
            ),
        ],
    )
    progress_messages: list[str] = []
    store = _RecordingStore()

    async def _progress_callback(message: str) -> None:
        progress_messages.append(message)

    result = await run_coding(
        extraction,
        settings=_settings(),
        progress_callback=_progress_callback,
        store=store,
        extraction_id="ext-123",
        report_id="rep-123",
        job_id="job-123",
    )

    assert result.coded_finding_count == 2
    assert result.unresolved_finding_count == 0
    assert result.trace_id == "trace-123"
    assert progress_messages[0] == "[stage:coding_fast_path] resolving_indexes"
    assert progress_messages[-1] == "[stage:coding_complete] coding_complete"
    assert len(store.calls) == 1
    assert store.calls[0]["coding_model"] == "openai:gpt-5.2"
    assert store.calls[0]["coding_reasoning"] == "low"
    assert store.calls[0]["coding_trace_id"] == "trace-123"

    for finding in result.extraction.findings:
        assert finding.coding is not None
        assert finding.coding.finding_code.status == "coded"
        assert finding.coding.finding_code.method == "fast-path"
        assert finding.coding.finding_code.oifm_id == "OIFM:1"
        assert len(finding.coding.location_codes) == 1
        assert finding.coding.location_codes[0].status == "coded"
        assert finding.coding.location_codes[0].method == "fast-path"
        assert finding.coding.location_codes[0].location_id == "LOC:RIGHT_KIDNEY"


@pytest.mark.asyncio
async def test_run_coding_keeps_lateralized_locations_separate(monkeypatch):
    """Location grouping and fast-path lookup must not collapse left/right findings."""

    class _LateralityAwareLocationIndex:
        def get(self, key: str):
            if key == "left kidney":
                return SimpleNamespace(
                    id="LOC:LEFT_KIDNEY",
                    description="left kidney",
                    region="abdomen",
                    laterality="left",
                    containment_parent=None,
                    partof_parent=None,
                )
            if key == "right kidney":
                return SimpleNamespace(
                    id="LOC:RIGHT_KIDNEY",
                    description="right kidney",
                    region="abdomen",
                    laterality="right",
                    containment_parent=None,
                    partof_parent=None,
                )
            raise KeyError(key)

        async def search_batch(self, queries, limit):  # noqa: ARG002
            raise AssertionError("location search should not run when lateralized fast-path succeeds")

    monkeypatch.setattr("finding_extractor.coding.runtime.Index", _FakeFindingIndex)
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.AnatomicLocationIndex",
        _LateralityAwareLocationIndex,
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.build_coding_model_runtime",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_term_agent",
        lambda runtime, **kw: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_term_agent",
        lambda runtime, **kw: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.resolve_runtime_reasoning",
        lambda model_name, reasoning, allow_unknown_model_reasoning: reasoning,
    )
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.span", _null_span)
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.info", lambda *args, **kwargs: None)

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(
            study_description="CT Abdomen and Pelvis With Contrast",
            modality="CT",
            body_part="abdomen, pelvis",
        ),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidney",
                    laterality="left",
                ),
                report_text="Stone in the left kidney.",
            ),
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidney",
                    laterality="right",
                ),
                report_text="Stone in the right kidney.",
            ),
        ],
    )

    result = await run_coding(
        extraction,
        settings=_settings(),
    )

    assert result.extraction.findings[0].coding is not None
    assert result.extraction.findings[1].coding is not None
    assert result.extraction.findings[0].coding.location_codes[0].location_id == "LOC:LEFT_KIDNEY"
    assert result.extraction.findings[1].coding.location_codes[0].location_id == "LOC:RIGHT_KIDNEY"


@pytest.mark.asyncio
async def test_run_coding_backfills_partial_term_generation_outputs(monkeypatch):
    """Missing items in a successful batch should fall back to deterministic search terms."""

    class _PartialFindingIndex:
        def __init__(self) -> None:
            self.search_queries: list[str] = []

        async def get(self, key: str):  # noqa: ARG002
            return None

        async def search_batch(self, queries, limit):  # noqa: ARG002
            self.search_queries = list(queries)
            return {
                "renal stone": [
                    SimpleNamespace(
                        oifm_id="OIFM:STONE",
                        name="renal calculus",
                        description="Kidney stone.",
                        synonyms=["kidney stone"],
                        tags=["abdomen"],
                    )
                ],
                "hydronephrosis": [
                    SimpleNamespace(
                        oifm_id="OIFM:HYDRO",
                        name="hydronephrosis",
                        description="Dilation of the renal collecting system.",
                        synonyms=[],
                        tags=["abdomen"],
                    )
                ],
            }

    class _PartialLocationIndex:
        def __init__(self) -> None:
            self.search_queries: list[str] = []

        def get(self, key: str):  # noqa: ARG002
            raise KeyError(key)

        async def search_batch(self, queries, limit):  # noqa: ARG002
            self.search_queries = list(queries)
            return {
                "left kidney": [
                    SimpleNamespace(
                        id="LOC:LEFT_KIDNEY",
                        description="left kidney",
                        region="abdomen",
                        laterality="left",
                        containment_parent=None,
                        partof_parent=None,
                    )
                ],
                "right kidney": [
                    SimpleNamespace(
                        id="LOC:RIGHT_KIDNEY",
                        description="right kidney",
                        region="abdomen",
                        laterality="right",
                        containment_parent=None,
                        partof_parent=None,
                    )
                ],
            }

    finding_index = _PartialFindingIndex()
    location_index = _PartialLocationIndex()

    monkeypatch.setattr("finding_extractor.coding.runtime.Index", lambda: finding_index)
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.AnatomicLocationIndex",
        lambda: location_index,
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.build_coding_model_runtime",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_term_agent",
        lambda runtime, **kw: _FixedOutputAgent(
            FindingTermsBatchOutput(
                results=[FindingTerms(finding_index=0, search_terms=["renal stone"])]
            )
        ),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_term_agent",
        lambda runtime, **kw: _FixedOutputAgent(
            LocationTermsBatchOutput(
                results=[LocationTerms(finding_index=0, search_terms=["left kidney"])]
            )
        ),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_selector_agent",
        lambda runtime: _FirstCandidateFindingSelector(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_selector_agent",
        lambda runtime: _FirstCandidateLocationSelector(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.resolve_runtime_reasoning",
        lambda model_name, reasoning, allow_unknown_model_reasoning: reasoning,
    )
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.span", _null_span)
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.info", lambda *args, **kwargs: None)

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(
            study_description="CT Abdomen and Pelvis With Contrast",
            modality="CT",
            body_part="abdomen, pelvis",
        ),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidney",
                    laterality="left",
                ),
                report_text="Stone in the left kidney.",
            ),
            Finding(
                finding_name="hydronephrosis",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidney",
                    laterality="right",
                ),
                report_text="Hydronephrosis in the right kidney.",
            ),
        ],
    )

    result = await run_coding(
        extraction,
        settings=_settings(),
    )

    assert set(finding_index.search_queries) == {"renal stone", "hydronephrosis"}
    assert "right kidney" in location_index.search_queries
    assert result.extraction.findings[0].coding is not None
    assert result.extraction.findings[0].coding.finding_code.oifm_id == "OIFM:STONE"
    assert result.extraction.findings[0].coding.location_codes[0].location_id == "LOC:LEFT_KIDNEY"
    assert result.extraction.findings[1].coding is not None
    assert result.extraction.findings[1].coding.finding_code.oifm_id == "OIFM:HYDRO"
    assert result.extraction.findings[1].coding.location_codes[0].location_id == "LOC:RIGHT_KIDNEY"


@pytest.mark.asyncio
async def test_run_coding_marks_location_no_candidates_without_selector(monkeypatch):
    """Location selection should resolve to `no_candidates` when search returns nothing."""

    class _FindingSearchIndex:
        async def get(self, key: str):  # noqa: ARG002
            return None

        async def search_batch(self, queries, limit):  # noqa: ARG002
            return {
                "renal stone": [
                    SimpleNamespace(
                        oifm_id="OIFM:STONE",
                        name="renal calculus",
                        description="Kidney stone.",
                        synonyms=[],
                        tags=[],
                    )
                ]
            }

    class _EmptyLocationIndex:
        def get(self, key: str):  # noqa: ARG002
            raise KeyError(key)

        async def search_batch(self, queries, limit):  # noqa: ARG002
            return {}

    monkeypatch.setattr("finding_extractor.coding.runtime.Index", _FindingSearchIndex)
    monkeypatch.setattr("finding_extractor.coding.runtime.AnatomicLocationIndex", _EmptyLocationIndex)
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.build_coding_model_runtime",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_term_agent",
        lambda runtime, **kw: _FixedOutputAgent(
            FindingTermsBatchOutput(
                results=[FindingTerms(finding_index=0, search_terms=["renal stone"])]
            )
        ),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_term_agent",
        lambda runtime, **kw: _FixedOutputAgent(
            LocationTermsBatchOutput(
                results=[LocationTerms(finding_index=0, search_terms=["left kidney"])]
            )
        ),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_selector_agent",
        lambda runtime: _FirstCandidateFindingSelector(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.resolve_runtime_reasoning",
        lambda model_name, reasoning, allow_unknown_model_reasoning: reasoning,
    )
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.span", _null_span)
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.info", lambda *args, **kwargs: None)

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen"),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidney",
                    laterality="left",
                ),
                report_text="Stone in the left kidney.",
            )
        ],
    )

    result = await run_coding(extraction, settings=_settings())

    location_code = result.extraction.findings[0].coding.location_codes[0]
    assert location_code.status == "unmapped"
    assert location_code.reason == "no_candidates"


@pytest.mark.asyncio
async def test_run_coding_invalid_finding_selector_id_becomes_unmapped(monkeypatch):
    """Finding selector outputs must be validated against the candidate set."""

    class _CandidateFindingIndex:
        async def get(self, key: str):  # noqa: ARG002
            return None

        async def search_batch(self, queries, limit):  # noqa: ARG002
            return {
                "renal stone": [
                    SimpleNamespace(
                        oifm_id="OIFM:STONE",
                        name="renal calculus",
                        description="Kidney stone.",
                        synonyms=[],
                        tags=[],
                    )
                ]
            }

    monkeypatch.setattr("finding_extractor.coding.runtime.Index", _CandidateFindingIndex)
    monkeypatch.setattr("finding_extractor.coding.runtime.AnatomicLocationIndex", _FakeLocationIndex)
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.build_coding_model_runtime",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_term_agent",
        lambda runtime, **kw: _FixedOutputAgent(
            FindingTermsBatchOutput(
                results=[FindingTerms(finding_index=0, search_terms=["renal stone"])]
            )
        ),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_term_agent",
        lambda runtime, **kw: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_finding_selector_agent",
        lambda runtime: _InvalidFindingSelector(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.create_location_selector_agent",
        lambda runtime: _UnusedAgent(),
    )
    monkeypatch.setattr(
        "finding_extractor.coding.runtime.resolve_runtime_reasoning",
        lambda model_name, reasoning, allow_unknown_model_reasoning: reasoning,
    )
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.span", _null_span)
    monkeypatch.setattr("finding_extractor.coding.runtime.logfire.info", lambda *args, **kwargs: None)

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen"),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="right kidney",
                    laterality="right",
                ),
                report_text="Stone in the right kidney.",
            )
        ],
    )

    result = await run_coding(extraction, settings=_settings())

    finding_code = result.extraction.findings[0].coding.finding_code
    assert finding_code.status == "unmapped"
    assert finding_code.reason == "no_candidates"
    assert finding_code.oifm_id is None


def test_location_term_fallback_expands_bilateral_anatomy():
    """Bilateral locations should fall back to separate left/right search terms."""
    finding = Finding(
        finding_name="ground-glass opacity",
        presence="present",
        location=FindingLocation(
            body_region="chest",
            specific_anatomy="lung",
            laterality="bilateral",
        ),
        report_text="Bilateral lung opacities.",
    )

    assert _location_term_fallback(finding) == ["left lung", "right lung", "lung"]
