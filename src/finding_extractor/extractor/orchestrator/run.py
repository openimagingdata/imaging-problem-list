"""Worker-side extraction orchestration with per-chunk pipeline execution."""

from __future__ import annotations

import asyncio
import contextlib

from finding_extractor.core.observability import observation_span
from finding_extractor.extractor.chunking import ChunkingSettings
from finding_extractor.extractor.progress import ProgressCallbackType, emit_stage_progress
from finding_extractor.models import ExamInfo, PipelineDiagnostics

from .chunks import (
    build_section_chunks,
    expand_chunks_with_semantic_chunking,
    run_section_attempt,
)
from .merge import (
    collect_failed_metadata,
    merge_extractions,
)
from .review import build_retry_chunk, review_single_chunk
from .types import (
    ChunkPipelineResult,
    ExtractExamInfoFn,
    ExtractFindingsFn,
    OrchestrationResult,
    ReportChunk,
    ReviewChunksFn,
    ValidateExtractionFn,
)


async def _resolve_exam_info(
    task: asyncio.Task[ExamInfo] | None,
    *,
    subagent_timeout_seconds: float | None,
    emit_progress: ProgressCallbackType,
    logger=None,
) -> ExamInfo | None:
    """Resolve exam info from a shared task. Returns None on failure (non-fatal)."""
    if task is None:
        return None

    try:
        if subagent_timeout_seconds is not None:
            exam_info = await asyncio.wait_for(task, timeout=subagent_timeout_seconds)
        else:
            exam_info = await task
        await emit_stage_progress(
            emit_progress,
            "extract_exam_info",
            (
                f"completed modality={exam_info.modality} "
                f"body_region={exam_info.body_region} "
                f"body_part={exam_info.body_part} "
                f"contrast={exam_info.contrast} "
                f"laterality={exam_info.laterality}"
            ),
        )
        return exam_info
    except Exception as exc:
        await emit_stage_progress(
            emit_progress,
            "extract_exam_info",
            f"failed error={type(exc).__name__} (keeping placeholder exam_info)",
        )
        if logger is not None:
            logger.warning(
                "Exam-info sub-agent failed (non-fatal): %s",
                type(exc).__name__,
                exc_info=True,
            )
        return None


async def _run_chunk_pipeline(
    *,
    chunk: ReportChunk,
    semaphore: asyncio.Semaphore,
    exam_info_future: asyncio.Task[ExamInfo | None],
    study_description: str | None,
    model_name: str,
    reasoning: str | None,
    emit_progress: ProgressCallbackType,
    extract_findings_fn: ExtractFindingsFn,
    review_chunks_fn: ReviewChunksFn | None,
    reviewer_reextract_enabled: bool,
    subagent_timeout_seconds: float | None,
    logger=None,
) -> ChunkPipelineResult:
    """Run one chunk through extract → review → correct.

    All exceptions are handled internally — extraction and review failures
    are captured in the result, never propagated to TaskGroup.
    """
    # 1. Extract
    async with semaphore:
        outcome = await run_section_attempt(
            chunk=chunk,
            attempt=1,
            stage="extract_sections",
            study_description=study_description,
            model_name=model_name,
            reasoning=reasoning,
            emit_progress=emit_progress,
            extract_findings_fn=extract_findings_fn,
            subagent_timeout_seconds=subagent_timeout_seconds,
        )

    if outcome.error is not None or review_chunks_fn is None:
        return ChunkPipelineResult(outcome=outcome, decision=None)

    # 2. Review (await shared exam_info — resolves once, no-op after first)
    exam_info = await exam_info_future
    # Use placeholder if exam_info resolution failed
    review_exam_info = exam_info if exam_info is not None else ExamInfo(
        study_description=study_description or "Radiology study"
    )

    async with semaphore:
        decision = await review_single_chunk(
            outcome=outcome,
            exam_info=review_exam_info,
            review_chunks_fn=review_chunks_fn,
            emit_progress=emit_progress,
            subagent_timeout_seconds=subagent_timeout_seconds,
            logger=logger,
        )

    if decision is None or not decision.should_reextract or not reviewer_reextract_enabled:
        return ChunkPipelineResult(outcome=outcome, decision=decision)

    # 3. Reviewer correction — re-extract with feedback
    await emit_stage_progress(
        emit_progress,
        "review",
        f"chunk_reextract_start report_chunk_id={chunk.report_chunk_id}",
    )
    retry_chunk = build_retry_chunk(chunk, outcome, decision)
    async with semaphore:
        reextract_outcome = await run_section_attempt(
            chunk=retry_chunk,
            attempt=2,
            stage="review",
            study_description=study_description,
            model_name=model_name,
            reasoning=reasoning,
            emit_progress=emit_progress,
            extract_findings_fn=extract_findings_fn,
            subagent_timeout_seconds=subagent_timeout_seconds,
        )

    reextract_succeeded = reextract_outcome.error is None
    await emit_stage_progress(
        emit_progress,
        "review",
        (
            f"chunk_reextract_complete report_chunk_id={chunk.report_chunk_id} "
            f"status={'success' if reextract_succeeded else 'failed'}"
        ),
    )

    final_outcome = reextract_outcome if reextract_succeeded else outcome
    return ChunkPipelineResult(
        outcome=final_outcome,
        decision=decision,
        was_reextracted=reextract_succeeded,
    )


async def run_orchestrated_extraction(
    *,
    report_text: str,
    study_description: str | None,
    model_name: str,
    reasoning: str | None,
    validate: bool,
    emit_progress: ProgressCallbackType,
    extract_findings_fn: ExtractFindingsFn,
    validate_extraction_fn: ValidateExtractionFn,
    review_chunks_fn: ReviewChunksFn | None = None,
    extract_exam_info_fn: ExtractExamInfoFn | None = None,
    source_ref: str | None = None,
    external_metadata: dict[str, str] | None = None,
    max_subagent_concurrency: int = 5,
    reviewer_reextract_enabled: bool = True,
    chunking_settings: ChunkingSettings | None = None,
    subagent_timeout_seconds: float | None = None,
    logger=None,
) -> OrchestrationResult:
    """Run extraction with per-chunk pipeline: extract → review → correct."""

    # --- Sectionize first (no LLM call) ---
    base_chunks = build_section_chunks(report_text)
    if not base_chunks:
        raise ValueError("No extractable `findings` or `impression` sections found in report text.")

    if chunking_settings is None:
        chunking_settings = ChunkingSettings()

    with observation_span("extraction.sectionize") as sectionize_span:
        chunks, chunking_degraded_sections = await expand_chunks_with_semantic_chunking(
            section_chunks=base_chunks,
            chunking_settings=chunking_settings,
            emit_progress=emit_progress,
        )
        unique_section_names = sorted({c.section_name for c in chunks})
        sectionize_span.set_attribute("section_count", len(unique_section_names))
        sectionize_span.set_attribute("chunk_count", len(chunks))
        sectionize_span.set_attribute("degraded_sections", chunking_degraded_sections)
        await emit_stage_progress(
            emit_progress,
            "sectionize",
            (
                f"mode=v2 sections={len(unique_section_names)} "
                f"chunks={len(chunks)} names={','.join(unique_section_names)} "
                "chunking=on "
                f"degraded_sections={chunking_degraded_sections}"
            ),
        )

    # --- Shared semaphore for ALL model calls (exam_info + chunks) ---
    semaphore = asyncio.Semaphore(max(1, max_subagent_concurrency))

    # --- Start exam_info behind the shared semaphore ---
    exam_info_task: asyncio.Task[ExamInfo] | None = None
    if extract_exam_info_fn is not None:
        await emit_stage_progress(emit_progress, "extract_exam_info", "start")

        async def _run_exam_info() -> ExamInfo:
            async with semaphore:
                with observation_span("extraction.exam_info", model_name=model_name):
                    return await extract_exam_info_fn(
                        report_text=report_text,
                        study_description=study_description,
                        source_ref=source_ref,
                        external_metadata=external_metadata,
                    )

        exam_info_task = asyncio.create_task(_run_exam_info())

    # --- Wrap exam_info resolution as a shared future ---
    exam_info_resolved: asyncio.Task[ExamInfo | None] = asyncio.ensure_future(
        _resolve_exam_info(
            exam_info_task,
            subagent_timeout_seconds=subagent_timeout_seconds,
            emit_progress=emit_progress,
            logger=logger,
        )
    )

    # --- Per-chunk pipelines ---
    await emit_stage_progress(
        emit_progress,
        "extract_sections",
        f"start chunks={len(chunks)} max_concurrency={max(1, max_subagent_concurrency)}",
    )

    with observation_span(
        "extraction.chunk_pipelines",
        chunk_count=len(chunks),
        max_concurrency=max(1, max_subagent_concurrency),
    ) as pipelines_span:
        async with asyncio.TaskGroup() as tg:
            pipeline_tasks = [
                tg.create_task(
                    _run_chunk_pipeline(
                        chunk=chunk,
                        semaphore=semaphore,
                        exam_info_future=exam_info_resolved,
                        study_description=study_description,
                        model_name=model_name,
                        reasoning=reasoning,
                        emit_progress=emit_progress,
                        extract_findings_fn=extract_findings_fn,
                        review_chunks_fn=review_chunks_fn,
                        reviewer_reextract_enabled=reviewer_reextract_enabled,
                        subagent_timeout_seconds=subagent_timeout_seconds,
                        logger=logger,
                    )
                )
                for chunk in chunks
            ]
        results = [t.result() for t in pipeline_tasks]

        successful = [r for r in results if r.outcome.error is None]
        failed = [r for r in results if r.outcome.error is not None]
        reviewed = [r for r in results if r.decision is not None]
        reextracted = [r for r in results if r.was_reextracted]
        pipelines_span.set_attribute("successful_chunks", len(successful))
        pipelines_span.set_attribute("failed_chunks", len(failed))
        pipelines_span.set_attribute("reviewed_chunks", len(reviewed))
        pipelines_span.set_attribute("reextracted_chunks", len(reextracted))

    # --- Handle all-failed case ---
    if not successful:
        if exam_info_task is not None and not exam_info_task.done():
            exam_info_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await exam_info_task
        first_error = next(
            (r.outcome.error for r in results if r.outcome.error is not None), None
        )
        if first_error is None:
            raise RuntimeError("Pipeline produced no successful chunk outputs.")
        raise first_error

    # --- Merge ---
    successful_outcomes = sorted(
        [r.outcome for r in successful], key=lambda o: o.chunk.index
    )
    with observation_span("extraction.merge") as merge_span:
        extraction, usage = merge_extractions(successful_outcomes)
        merge_span.set_attribute("findings_count", len(extraction.findings))
        merge_span.set_attribute("non_findings_count", len(extraction.non_finding_text))

    await emit_stage_progress(
        emit_progress,
        "merge_dedupe",
        (
            f"final_merge findings={len(extraction.findings)} "
            f"non_findings={len(extraction.non_finding_text)}"
        ),
    )

    # Apply resolved exam_info only if the dedicated pass succeeded
    resolved_exam_info = await exam_info_resolved
    if resolved_exam_info is not None:
        extraction = extraction.model_copy(update={"exam_info": resolved_exam_info})

    # --- Validate ---
    if validate:
        with observation_span("extraction.validate") as validate_span:
            await emit_stage_progress(
                emit_progress, "validate_output", "validating_extraction_results"
            )
            validation_result = validate_extraction_fn(report_text, extraction)
            if validation_result is not None:
                validate_span.set_attribute(
                    "coverage_warnings_count", len(validation_result.coverage_warnings)
                )
                validate_span.set_attribute(
                    "verbatim_errors_count", len(validation_result.verbatim_errors)
                )
    else:
        validation_result = None

    # --- Diagnostics ---
    failed_outcomes = [r.outcome for r in failed]
    chunk_last_error_type = {
        r.outcome.chunk.report_chunk_id: type(r.outcome.error).__name__
        for r in failed
        if r.outcome.error is not None
    }
    failed_chunk_ids, failed_error_types = collect_failed_metadata(
        [o.chunk for o in failed_outcomes],
        chunk_last_error_type,
    )

    reviewer_requested = sum(
        1 for r in reviewed if r.decision is not None and r.decision.should_reextract
    )
    total_chunk_attempts = len(chunks) + len(reextracted)

    pipeline_diagnostics = PipelineDiagnostics(
        mode="modular",
        total_chunks=len(chunks),
        initial_failed_chunks=len(failed),
        remaining_failed_chunks=len(failed),
        total_chunk_attempts=total_chunk_attempts,
        failed_chunk_ids=failed_chunk_ids,
        failed_chunk_error_types=failed_error_types,
        reviewer_requested_chunks=reviewer_requested,
        reviewer_reextracted_chunks=len(reextracted),
    )

    return OrchestrationResult(
        extraction=extraction,
        usage=usage,
        validation_result=validation_result,
        pipeline_diagnostics=pipeline_diagnostics,
    )
