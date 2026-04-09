"""Chunk building and execution helpers for the orchestrator."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from finding_extractor.core.observability import observation_span
from finding_extractor.extractor.chunking import ChunkingSettings, SectionChunk, chunk_section_text
from finding_extractor.extractor.progress import ProgressCallbackType, emit_stage_progress
from finding_extractor.extractor.report_sections import parse_report_sections

from .types import ChunkExtractionOutcome, ExtractFindingsFn, ReportChunk


def _agent_status_detail(message: str) -> str:
    lowered = message.strip().lower()
    if lowered.startswith("calling model"):
        return "calling_model"
    if lowered.startswith("model call complete"):
        return "model_call_complete"
    if lowered.startswith("retrying"):
        return "model_retrying"
    return "agent_status"


def build_section_chunks(report_text: str) -> list[ReportChunk]:
    parsed = parse_report_sections(report_text)
    if not parsed.sections:
        return []

    # Both findings and impression are always selected — no conditional gating.
    selected_sections = [s for s in parsed.sections if s.name in {"findings", "impression"}]
    if not selected_sections:
        return []

    lines = report_text.split("\n")
    name_counts: dict[str, int] = defaultdict(int)
    result: list[ReportChunk] = []
    for section in selected_sections:
        section_text = "\n".join(lines[section.start_line : section.end_line]).strip()
        if not section_text:
            continue
        name_counts[section.name] += 1
        result.append(
            ReportChunk(
                index=len(result),
                section_name=section.name,
                report_chunk_id=f"{section.name}_{name_counts[section.name]}",
                text=section_text,
            )
        )
    return result


def _half_tail(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    mid = max(1, len(stripped) // 2)
    return stripped[-mid:].strip() or None


def _half_head(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    mid = max(1, len(stripped) // 2)
    return stripped[:mid].strip() or None


def _as_passthrough_chunk(report_text: str) -> tuple[SectionChunk, ...]:
    if not report_text:
        return ()
    return (SectionChunk(start_index=0, end_index=len(report_text), text=report_text),)


def _chunk_id_label(base: str, index: int, count: int) -> str:
    if count == 1:
        return base
    return f"{base}_chunk_{index + 1}"


async def run_section_attempt(
    *,
    chunk: ReportChunk,
    attempt: int,
    stage: str,
    study_description: str | None,
    exam_context: str | None = None,
    model_name: str,
    reasoning: str | None,
    emit_progress: ProgressCallbackType,
    extract_findings_fn: ExtractFindingsFn,
    subagent_timeout_seconds: float | None = None,
) -> ChunkExtractionOutcome:
    """Run one extraction attempt for a chunk. Never raises — errors are captured in the outcome."""
    await emit_stage_progress(
        emit_progress,
        stage,
        f"chunk={chunk.report_chunk_id} attempt={attempt} status=started section={chunk.section_name}",
    )

    async def _chunk_status_cb(message: str) -> None:
        await emit_stage_progress(
            emit_progress,
            stage,
            f"chunk={chunk.report_chunk_id} attempt={attempt} status={_agent_status_detail(message)}",
        )

    with observation_span(
        "extraction.chunk",
        chunk_id=chunk.report_chunk_id,
        section_name=chunk.section_name,
        attempt=attempt,
        stage=stage,
    ) as chunk_span:
        try:
            if subagent_timeout_seconds is not None:
                async with asyncio.timeout(subagent_timeout_seconds):
                    extraction_result = await extract_findings_fn(
                        report_text=chunk.text,
                        study_description=study_description,
                        exam_context=exam_context,
                        model=model_name,
                        reasoning=reasoning,
                        section_name=chunk.section_name,
                        preceding_chunk_context=chunk.preceding_chunk_context,
                        following_chunk_context=chunk.following_chunk_context,
                        progress_callback=_chunk_status_cb,
                        feedback=chunk.feedback,
                    )
            else:
                extraction_result = await extract_findings_fn(
                    report_text=chunk.text,
                    study_description=study_description,
                    exam_context=exam_context,
                    model=model_name,
                    reasoning=reasoning,
                    section_name=chunk.section_name,
                    preceding_chunk_context=chunk.preceding_chunk_context,
                    following_chunk_context=chunk.following_chunk_context,
                    progress_callback=_chunk_status_cb,
                    feedback=chunk.feedback,
                )
            chunk_span.set_attribute("status", "completed")
            chunk_span.set_attribute(
                "findings_count", len(extraction_result.report_findings.findings)
            )
            await emit_stage_progress(
                emit_progress,
                stage,
                (
                    f"chunk={chunk.report_chunk_id} attempt={attempt} status=completed "
                    f"findings={len(extraction_result.report_findings.findings)} "
                    f"non_findings={len(extraction_result.report_findings.non_finding_text)}"
                ),
            )
            return ChunkExtractionOutcome(
                chunk=chunk,
                attempt=attempt,
                extraction=extraction_result.report_findings,
                usage=extraction_result.usage,
                error=None,
            )
        except Exception as exc:
            chunk_span.set_attribute("status", "failed")
            chunk_span.set_attribute("error_type", type(exc).__name__)
            await emit_stage_progress(
                emit_progress,
                stage,
                f"chunk={chunk.report_chunk_id} attempt={attempt} status=failed error={type(exc).__name__}",
            )
            return ChunkExtractionOutcome(
                chunk=chunk,
                attempt=attempt,
                extraction=None,
                usage=None,
                error=exc,
            )


async def expand_chunks_with_semantic_chunking(
    *,
    section_chunks: list[ReportChunk],
    chunking_settings: ChunkingSettings,
    emit_progress: ProgressCallbackType,
) -> tuple[list[ReportChunk], int]:
    """Expand section-level chunks into sub-chunks with adjacency context."""
    expanded: list[ReportChunk] = []
    degraded_sections = 0

    for section_chunk in section_chunks:
        result = await chunk_section_text(
            section_name=section_chunk.section_name,
            section_text=section_chunk.text,
            settings=chunking_settings,
        )
        chunks = result.chunks or _as_passthrough_chunk(section_chunk.text)
        strategy = result.diagnostics.strategy
        warnings = result.diagnostics.warnings
        sentence_count = result.diagnostics.sentence_count
        semantic_applied = result.diagnostics.semantic_applied

        if "semantic_failed" in strategy:
            degraded_sections += 1

        texts = [chunk.text for chunk in chunks]
        for i, chunk_text in enumerate(texts):
            prev_context = _half_tail(texts[i - 1]) if i > 0 else None
            next_context = _half_head(texts[i + 1]) if i + 1 < len(texts) else None
            expanded.append(
                ReportChunk(
                    index=len(expanded),
                    section_name=section_chunk.section_name,
                    report_chunk_id=_chunk_id_label(section_chunk.report_chunk_id, i, len(texts)),
                    text=chunk_text,
                    preceding_chunk_context=prev_context,
                    following_chunk_context=next_context,
                )
            )

        warning_detail = ""
        if warnings:
            warning_detail = f" warnings={','.join(warnings)}"
        await emit_stage_progress(
            emit_progress,
            "sectionize",
            (
                f"chunk section={section_chunk.report_chunk_id} strategy={strategy} chunks={len(chunks)} "
                f"sentences={sentence_count} semantic_applied={str(semantic_applied).lower()}"
                f"{warning_detail}"
            ),
        )

    return expanded, degraded_sections
