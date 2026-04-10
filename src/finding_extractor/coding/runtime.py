"""Runtime orchestration for post-extraction coding."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TypeVar

import logfire
import structlog
from anatomic_locations import AnatomicLocation, AnatomicLocationIndex
from findingmodel import Index
from findingmodel.index import IndexEntry

from finding_extractor.coding.agents import (
    build_coding_model_runtime,
    create_finding_selector_agent,
    create_finding_term_agent,
    create_location_selector_agent,
    create_location_term_agent,
)
from finding_extractor.coding.prompt import (
    build_finding_selector_user_prompt,
    build_finding_term_user_prompt,
    build_location_selector_user_prompt,
    build_location_term_user_prompt,
)
from finding_extractor.coding.types import FindingCodeSelection, LocationCodeSelection
from finding_extractor.core.config import ExtractorSettings, get_settings
from finding_extractor.core.observability import get_current_trace_id
from finding_extractor.db.store import ExtractionStore
from finding_extractor.extractor.progress import ProgressCallbackType, emit_stage_progress
from finding_extractor.llm.model_settings import resolve_runtime_reasoning
from finding_extractor.llm.resilience import AgentModelRuntime
from finding_extractor.models import (
    AlternateCode,
    ExtractedReportFindings,
    Finding,
    FindingCode,
    FindingCodingBundle,
    LocationAlternateCode,
    LocationCode,
)

logger = structlog.get_logger(__name__)

LocationGroupKey = tuple[str | None, str | None, str | None, str]


@dataclass(frozen=True)
class CodingRunResult:
    """Output from one coding run."""

    extraction: ExtractedReportFindings
    model_name: str
    reasoning_effort: str | None
    duration_ms: int
    coded_finding_count: int
    unresolved_finding_count: int
    trace_id: str | None


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _location_group_key(finding: Finding) -> LocationGroupKey:
    location = finding.location
    return (
        location.specific_anatomy if location else None,
        location.laterality if location else None,
        location.body_region if location else None,
        finding.finding_name,
    )


def _location_fast_path_queries(finding: Finding) -> list[str]:
    location = finding.location
    if location is None or location.specific_anatomy is None:
        return []
    if location.laterality == "bilateral":
        return []
    anatomy = location.specific_anatomy.strip()
    if not anatomy:
        return []
    laterality = location.laterality
    if laterality in {"left", "right"} and not anatomy.casefold().startswith(f"{laterality} "):
        return [f"{laterality} {anatomy}", anatomy]
    return [anatomy]


def _location_term_fallback(finding: Finding) -> list[str]:
    location = finding.location
    if location and location.specific_anatomy:
        anatomy = location.specific_anatomy.strip()
        if not anatomy:
            return []
        if location.laterality == "bilateral":
            return _dedupe_terms([f"left {anatomy}", f"right {anatomy}", anatomy])
        if location.laterality in {"left", "right"} and not anatomy.casefold().startswith(
            f"{location.laterality} "
        ):
            return _dedupe_terms([f"{location.laterality} {anatomy}", anatomy])
        return [anatomy]
    if location and location.body_region:
        return [location.body_region]
    return []


def _location_alternates(candidates: list[AnatomicLocation]) -> list[LocationAlternateCode]:
    return [
        LocationAlternateCode(location_id=candidate.id, location_name=candidate.description)
        for candidate in candidates
    ]


def _finding_alternates(candidates: list[IndexEntry]) -> list[AlternateCode]:
    return [AlternateCode(oifm_id=candidate.oifm_id, name=candidate.name) for candidate in candidates]


def _build_finding_code_from_fast_path(candidate: IndexEntry) -> FindingCode:
    return FindingCode(
        status="coded",
        oifm_id=candidate.oifm_id,
        oifm_name=candidate.name,
        method="fast-path",
    )


def _build_location_codes_from_fast_path(candidate: AnatomicLocation) -> list[LocationCode]:
    return [
        LocationCode(
            status="coded",
            location_id=candidate.id,
            location_name=candidate.description,
            method="fast-path",
        )
    ]


def _build_finding_code_from_selection(
    selection: FindingCodeSelection | None,
    candidates: list[IndexEntry],
) -> FindingCode:
    alternates = _finding_alternates(candidates)
    if selection is None:
        return FindingCode(
            status="unmapped",
            method="unresolved",
            reason="coding_error",
            candidates=alternates,
        )
    if selection.oifm_id:
        matched_name = next(
            (candidate.name for candidate in candidates if candidate.oifm_id == selection.oifm_id),
            None,
        )
        return FindingCode(
            status="coded",
            oifm_id=selection.oifm_id,
            oifm_name=matched_name,
            method="llm",
            reasoning=selection.reasoning,
            candidates=alternates,
        )
    reason = selection.rejection_reason or "no_candidates"
    return FindingCode(
        status="unmapped",
        method="unresolved",
        reason=reason,
        reasoning=selection.reasoning,
        closest_candidate_id=selection.closest_candidate_id,
        candidates=alternates,
    )


def _build_location_codes_from_selection(
    selection: LocationCodeSelection | None,
    candidates: list[AnatomicLocation],
) -> list[LocationCode]:
    alternates = _location_alternates(candidates)
    if selection is None:
        return [
            LocationCode(
                status="unmapped",
                method="unresolved",
                reason="no_candidates" if not candidates else "coding_error",
                candidates=alternates,
            )
        ]
    if selection.location_ids:
        id_to_name = {candidate.id: candidate.description for candidate in candidates}
        return [
            LocationCode(
                status="coded",
                location_id=location_id,
                location_name=id_to_name.get(location_id),
                method="llm",
                reasoning=selection.reasoning,
                candidates=alternates,
            )
            for location_id in selection.location_ids
        ]
    return [
        LocationCode(
            status="unmapped",
            method="unresolved",
            reason=selection.unresolved_reason or "no_candidates",
            reasoning=selection.reasoning,
            candidates=alternates,
        )
    ]


_K = TypeVar("_K")


def _backfill_missing_terms(
    term_inputs: list[tuple[_K, Finding]],
    terms_by_key: dict[_K, list[str]],
    *,
    fallback_for: Callable[[Finding], list[str]],
    axis: str,
) -> None:
    for key, representative in term_inputs:
        if key in terms_by_key:
            continue
        fallback_terms = fallback_for(representative)
        terms_by_key[key] = fallback_terms
        logger.warning(
            "Coding term generation omitted item; using fallback terms",
            axis=axis,
            finding_name=representative.finding_name,
            fallback_terms=fallback_terms,
        )


async def run_coding(
    extraction: ExtractedReportFindings,
    *,
    model: str | None = None,
    reasoning: str | None = None,
    settings: ExtractorSettings | None = None,
    progress_callback: ProgressCallbackType | None = None,
    store: ExtractionStore | None = None,
    extraction_id: str | None = None,
    report_id: str | None = None,
    job_id: str | None = None,
) -> CodingRunResult:
    """Run the coding pipeline against a completed extraction."""

    resolved_settings = settings or get_settings()

    if getattr(resolved_settings, "local_only_mode", False):
        raise RuntimeError(
            "Coding is not permitted in local-only mode. The findingmodel and "
            "anatomic_locations packages have not been audited for network egress."
        )
    model_name = model or resolved_settings.coding_model
    effective_reasoning = resolve_runtime_reasoning(
        model_name,
        reasoning or resolved_settings.coding_reasoning,
        allow_unknown_model_reasoning=resolved_settings.allow_unknown_model_reasoning,
    )
    selector_model = build_coding_model_runtime(
        model_name=model_name,
        reasoning=effective_reasoning,
        fallback_model_name=resolved_settings.coding_fallback_model,
        max_concurrency=resolved_settings.coding_max_concurrency,
    )
    term_gen_model: AgentModelRuntime | None = None
    if resolved_settings.coding_term_model and resolved_settings.coding_term_model != model_name:
        term_gen_model = build_coding_model_runtime(
            model_name=resolved_settings.coding_term_model,
            reasoning=None,
            fallback_model_name=resolved_settings.coding_fallback_model,
            max_concurrency=resolved_settings.coding_max_concurrency,
        )
    finding_term_agent = create_finding_term_agent(selector_model, term_runtime=term_gen_model)
    location_term_agent = create_location_term_agent(selector_model, term_runtime=term_gen_model)
    finding_selector = create_finding_selector_agent(selector_model)
    location_selector = create_location_selector_agent(selector_model)
    finding_index = Index()
    location_index = AnatomicLocationIndex()
    started_at = perf_counter()
    total_findings = len(extraction.findings)
    trace_id = get_current_trace_id()

    logger.info(
        "Coding task started",
        model=model_name,
        reasoning=effective_reasoning,
        total_findings=total_findings,
    )

    with logfire.span(
        "coding_pipeline",
        job_id=job_id,
        report_id=report_id,
        extraction_id=extraction_id,
        coding_model=model_name,
        coding_reasoning=effective_reasoning,
        total_findings=total_findings,
        max_concurrency=resolved_settings.coding_max_concurrency,
    ):
        await emit_stage_progress(progress_callback, "coding_fast_path", "resolving_indexes")
        finding_groups: dict[str, list[int]] = {}
        location_groups: dict[LocationGroupKey, list[int]] = {}
        for index, finding in enumerate(extraction.findings):
            finding_groups.setdefault(finding.finding_name, []).append(index)
            location_groups.setdefault(_location_group_key(finding), []).append(index)

        finding_fast_path: dict[str, IndexEntry] = {}
        location_fast_path: dict[LocationGroupKey, AnatomicLocation] = {}
        finding_term_inputs: list[tuple[str, Finding]] = []
        location_term_inputs: list[tuple[LocationGroupKey, Finding]] = []

        with logfire.span("phase1_fast_path") as phase_span:
            for key, indexes in finding_groups.items():
                candidate = await finding_index.get(key)
                if candidate is not None:
                    finding_fast_path[key] = candidate
                else:
                    finding_term_inputs.append((key, extraction.findings[indexes[0]]))

            for key, indexes in location_groups.items():
                representative = extraction.findings[indexes[0]]
                # The anatomic-location library exposes an in-memory synchronous
                # lookup for exact-name resolution; only the semantic batch search
                # API is async.
                for query in _location_fast_path_queries(representative):
                    try:
                        location_fast_path[key] = location_index.get(query)
                        break
                    except KeyError:
                        continue
                if key in location_fast_path:
                    continue
                location_term_inputs.append((key, representative))

            phase_span.set_attribute("findings_resolved", len(finding_fast_path))
            phase_span.set_attribute("locations_resolved", len(location_fast_path))
            phase_span.set_attribute("findings_need_llm", len(finding_term_inputs))
            phase_span.set_attribute("locations_need_llm", len(location_term_inputs))

        await emit_stage_progress(progress_callback, "coding_term_gen", "generating_search_terms")
        finding_terms_by_key: dict[str, list[str]] = {}
        location_terms_by_key: dict[LocationGroupKey, list[str]] = {}
        with logfire.span(
            "phase2_term_generation",
            finding_count=len(finding_term_inputs),
            location_count=len(location_term_inputs),
        ):
            async def _generate_finding_terms() -> None:
                if not finding_term_inputs:
                    return
                prompt = build_finding_term_user_prompt(
                    extraction.exam_info,
                    [finding for _, finding in finding_term_inputs],
                )
                try:
                    result = await finding_term_agent.run(prompt)
                    for item in result.output.results:
                        key, representative = finding_term_inputs[item.finding_index]
                        terms = item.search_terms or [representative.finding_name]
                        finding_terms_by_key[key] = terms
                except Exception:
                    logger.warning("Finding term generation failed", exc_info=True)
                    for key, representative in finding_term_inputs:
                        finding_terms_by_key[key] = [representative.finding_name]
                else:
                    _backfill_missing_terms(
                        finding_term_inputs,
                        finding_terms_by_key,
                        fallback_for=lambda finding: [finding.finding_name],
                        axis="finding",
                    )

            async def _generate_location_terms() -> None:
                if not location_term_inputs:
                    return
                prompt = build_location_term_user_prompt(
                    extraction.exam_info,
                    [finding for _, finding in location_term_inputs],
                )
                try:
                    result = await location_term_agent.run(prompt)
                    for item in result.output.results:
                        key, representative = location_term_inputs[item.finding_index]
                        terms = item.search_terms or _location_term_fallback(representative)
                        location_terms_by_key[key] = terms
                except Exception:
                    logger.warning("Location term generation failed", exc_info=True)
                    for key, representative in location_term_inputs:
                        location_terms_by_key[key] = _location_term_fallback(representative)
                else:
                    _backfill_missing_terms(
                        location_term_inputs,
                        location_terms_by_key,
                        fallback_for=_location_term_fallback,
                        axis="location",
                    )

            await asyncio.gather(_generate_finding_terms(), _generate_location_terms())

        await emit_stage_progress(progress_callback, "coding_search", "searching_indexes")
        finding_candidates_by_key: dict[str, list[IndexEntry]] = {}
        location_candidates_by_key: dict[LocationGroupKey, list[AnatomicLocation]] = {}
        with logfire.span("phase3_index_search") as phase_span:
            finding_queries = sorted({term for terms in finding_terms_by_key.values() for term in terms})
            location_queries = sorted({term for terms in location_terms_by_key.values() for term in terms})
            phase_span.set_attribute("finding_queries", len(finding_queries))
            phase_span.set_attribute("location_queries", len(location_queries))

            try:
                finding_search = (
                    await finding_index.search_batch(
                        finding_queries,
                        limit=resolved_settings.coding_search_limit,
                    )
                    if finding_queries
                    else {}
                )
            except Exception:
                logger.warning("Finding index search failed", exc_info=True)
                finding_search = {}
            try:
                location_search = (
                    await location_index.search_batch(
                        location_queries,
                        limit=resolved_settings.coding_search_limit,
                    )
                    if location_queries
                    else {}
                )
            except Exception:
                logger.warning("Location index search failed", exc_info=True)
                location_search = {}

            for key, terms in finding_terms_by_key.items():
                seen: set[str] = set()
                deduped: list[IndexEntry] = []
                for term in terms:
                    for candidate in finding_search.get(term, []):
                        if candidate.oifm_id in seen:
                            continue
                        seen.add(candidate.oifm_id)
                        deduped.append(candidate)
                finding_candidates_by_key[key] = deduped[: resolved_settings.coding_max_candidates]

            for key, terms in location_terms_by_key.items():
                seen: set[str] = set()
                deduped_locs: list[AnatomicLocation] = []
                for term in terms:
                    for candidate in location_search.get(term, []):
                        if candidate.id in seen:
                            continue
                        seen.add(candidate.id)
                        deduped_locs.append(candidate)
                location_candidates_by_key[key] = deduped_locs[: resolved_settings.coding_max_candidates]

        await emit_stage_progress(progress_callback, "coding_selection", "selecting_codes")
        finding_selections_by_key: dict[str, FindingCodeSelection | None] = {}
        location_selections_by_key: dict[LocationGroupKey, LocationCodeSelection | None] = {}
        selection_items = [
            ("finding", key, representative)
            for key, representative in finding_term_inputs
        ] + [
            ("location", key, representative)
            for key, representative in location_term_inputs
        ]
        total_selection_items = len(selection_items)
        completed_selection_items = 0
        selection_lock = asyncio.Lock()

        async def _mark_selection_progress() -> None:
            nonlocal completed_selection_items
            async with selection_lock:
                completed_selection_items += 1
                await emit_stage_progress(
                    progress_callback,
                    "coding_selection",
                    f"selecting_codes_{completed_selection_items}_of_{total_selection_items}",
                )

        with logfire.span("phase4_code_selection") as phase_span:
            semaphore = asyncio.Semaphore(resolved_settings.coding_max_concurrency)

            async def _select_finding(key: str, finding: Finding) -> None:
                candidates = finding_candidates_by_key.get(key, [])
                if not candidates:
                    finding_selections_by_key[key] = FindingCodeSelection(
                        oifm_id=None,
                        reasoning="No candidates from search",
                        rejection_reason=None,
                    )
                    await _mark_selection_progress()
                    return
                async with semaphore:
                    with logfire.span(
                        "select_finding_code",
                        finding_name=finding.finding_name,
                        num_candidates=len(candidates),
                    ) as span:
                        try:
                            result = await finding_selector.run(
                                build_finding_selector_user_prompt(
                                    finding,
                                    extraction.exam_info,
                                    candidates,
                                )
                            )
                            selection = result.output
                        except Exception:
                            logger.warning(
                                "Finding code selection failed",
                                finding_name=finding.finding_name,
                                exc_info=True,
                            )
                            selection = None
                        else:
                            valid_ids = {candidate.oifm_id for candidate in candidates}
                            if selection.oifm_id and selection.oifm_id not in valid_ids:
                                logger.warning(
                                    "Finding selector returned candidate not in set",
                                    finding_name=finding.finding_name,
                                    oifm_id=selection.oifm_id,
                                )
                                selection = FindingCodeSelection(
                                    oifm_id=None,
                                    reasoning=(
                                        f"Invalid selection {selection.oifm_id!r} "
                                        "was not in the candidate set"
                                    ),
                                )
                        finding_selections_by_key[key] = selection
                        span.set_attribute("selected_oifm_id", selection.oifm_id if selection else None)
                        await _mark_selection_progress()

            async def _select_location(key: LocationGroupKey, finding: Finding) -> None:
                candidates = location_candidates_by_key.get(key, [])
                if not candidates:
                    location_selections_by_key[key] = None
                    await _mark_selection_progress()
                    return
                async with semaphore:
                    with logfire.span(
                        "select_location_code",
                        finding_name=finding.finding_name,
                        num_candidates=len(candidates),
                    ) as span:
                        try:
                            result = await location_selector.run(
                                build_location_selector_user_prompt(
                                    finding,
                                    extraction.exam_info,
                                    candidates,
                                )
                            )
                            selection = result.output
                        except Exception:
                            logger.warning(
                                "Location code selection failed",
                                finding_name=finding.finding_name,
                                exc_info=True,
                            )
                            selection = None
                        else:
                            valid_ids = {candidate.id for candidate in candidates}
                            filtered = [
                                location_id
                                for location_id in selection.location_ids
                                if location_id in valid_ids
                            ]
                            if filtered != selection.location_ids:
                                logger.warning(
                                    "Location selector returned candidate not in set",
                                    finding_name=finding.finding_name,
                                )
                                selection = LocationCodeSelection(
                                    location_ids=filtered,
                                    unresolved_reason=(
                                        selection.unresolved_reason
                                        if filtered
                                        else "no_candidate_match"
                                    ),
                                    reasoning=selection.reasoning,
                                )
                        location_selections_by_key[key] = selection
                        span.set_attribute(
                            "selected_location_ids",
                            selection.location_ids if selection else [],
                        )
                        await _mark_selection_progress()

            await asyncio.gather(
                *[_select_finding(key, representative) for key, representative in finding_term_inputs],
                *[_select_location(key, representative) for key, representative in location_term_inputs],
            )

            phase_span.set_attribute(
                "findings_coded",
                sum(1 for selection in finding_selections_by_key.values() if selection and selection.oifm_id),
            )
            phase_span.set_attribute(
                "locations_coded",
                sum(
                    1
                    for selection in location_selections_by_key.values()
                    if selection and selection.location_ids
                ),
            )

        await emit_stage_progress(progress_callback, "coding_assembly", "assembling_results")
        updated_findings = list(extraction.findings)
        with logfire.span("phase5_assembly"):
            for key, indexes in finding_groups.items():
                if key in finding_fast_path:
                    finding_code = _build_finding_code_from_fast_path(finding_fast_path[key])
                else:
                    finding_code = _build_finding_code_from_selection(
                        finding_selections_by_key.get(key),
                        finding_candidates_by_key.get(key, []),
                    )
                for index in indexes:
                    existing = updated_findings[index].coding or FindingCodingBundle()
                    updated_findings[index] = updated_findings[index].model_copy(
                        update={
                            "coding": existing.model_copy(
                                update={"finding_code": finding_code}
                            )
                        }
                    )

            for key, indexes in location_groups.items():
                if key in location_fast_path:
                    location_codes = _build_location_codes_from_fast_path(location_fast_path[key])
                else:
                    location_codes = _build_location_codes_from_selection(
                        location_selections_by_key.get(key),
                        location_candidates_by_key.get(key, []),
                    )
                for index in indexes:
                    existing = updated_findings[index].coding or FindingCodingBundle()
                    updated_findings[index] = updated_findings[index].model_copy(
                        update={
                            "coding": existing.model_copy(
                                update={"location_codes": location_codes}
                            )
                        }
                    )

        coded_extraction = extraction.model_copy(update={"findings": updated_findings})
        coded_count = sum(
            1
            for finding in coded_extraction.findings
            if finding.coding is not None and finding.coding.finding_code.status == "coded"
        )
        unresolved_count = sum(
            1
            for finding in coded_extraction.findings
            if finding.coding is not None and finding.coding.finding_code.status == "unmapped"
        )
        duration_ms = int(round((perf_counter() - started_at) * 1000))

        logger.info(
            "Coding pipeline outcome",
            coded_findings=coded_count,
            unresolved_findings=unresolved_count,
            fast_path_findings=len(finding_fast_path),
            llm_coded_findings=max(coded_count - len(finding_fast_path), 0),
            wall_clock_seconds=round(duration_ms / 1000, 3),
        )
        logfire.info(
            "Coding pipeline outcome",
            job_id=job_id,
            extraction_id=extraction_id,
            total_findings=total_findings,
            coded_findings=coded_count,
            unresolved_findings=unresolved_count,
            fast_path_findings=len(finding_fast_path),
            llm_coded_findings=max(coded_count - len(finding_fast_path), 0),
            wall_clock_seconds=round(duration_ms / 1000, 3),
        )

        if unresolved_count > 0:
            logger.warning(
                "Coding completed with unresolved findings",
                unresolved_count=unresolved_count,
            )

        if store is not None:
            if extraction_id is None:
                raise RuntimeError("extraction_id is required when persisting coding results")
            await emit_stage_progress(progress_callback, "coding_persist", "saving_coded_extraction")
            await store.update_extraction_coding(
                extraction_id=extraction_id,
                extraction=coded_extraction,
                coding_model=model_name,
                coding_reasoning=effective_reasoning,
                coding_duration_ms=duration_ms,
                coding_trace_id=trace_id,
            )

    await emit_stage_progress(progress_callback, "coding_complete", "coding_complete")
    return CodingRunResult(
        extraction=coded_extraction,
        model_name=model_name,
        reasoning_effort=effective_reasoning,
        duration_ms=duration_ms,
        coded_finding_count=coded_count,
        unresolved_finding_count=unresolved_count,
        trace_id=trace_id,
    )
