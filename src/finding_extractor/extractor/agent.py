"""Pydantic AI extraction helpers.

Active runtime path:
- chunk-scoped extraction via ``extract_chunk`` / ``extract_chunk_findings``

Legacy helper retained for non-runtime tests:
- chunk-level extraction via ``extract_chunk_findings``
"""

import time
from dataclasses import dataclass, field

import structlog
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from finding_extractor.core.config import get_settings
from finding_extractor.extractor.progress import ProgressCallbackType
from finding_extractor.extractor.prompt import build_chunk_system_prompt, build_system_prompt
from finding_extractor.extractor.verbatim import verbatim_match
from finding_extractor.llm.resilience import create_resilient_agent
from finding_extractor.models import (
    ChunkExtractionResult,
    ExamInfo,
    ExtractedChunkFindings,
    ExtractedReportFindings,
    ExtractionResult,
    ExtractionUsage,
    Finding,
    ValidationResult,
)

logger = structlog.get_logger(__name__)


@dataclass
class ExtractorDeps:
    """Dependencies for the extraction agent — carries the original report text."""

    report_text: str
    progress_callback: ProgressCallbackType | None = field(default=None, repr=False)


async def _emit_progress(deps: ExtractorDeps, message: str) -> None:
    """Emit a status message via the deps callback, if one is configured."""
    if deps.progress_callback is not None:
        await deps.progress_callback(message)


def create_agent(
    model: str | None = None,
    *,
    reasoning: str | None = None,
) -> Agent[ExtractorDeps, ExtractedReportFindings]:
    """Create and configure the legacy full-report extraction agent.

    Args:
        model: Optional model override. Defaults to google-gla:gemini-3-flash-preview or
               IPL_MODEL env var.

    Returns:
        Configured Agent instance with ExtractedReportFindings output type
    """
    if model is None:
        model = get_settings().default_model

    instructions = build_system_prompt()
    agent = create_resilient_agent(
        model_name=model,
        reasoning=reasoning,
        instructions=instructions,
        output_type=ExtractedReportFindings,
        deps_type=ExtractorDeps,
        output_retries=3,
    )

    @agent.output_validator
    async def validate_verbatim(
        ctx: RunContext[ExtractorDeps], output: ExtractedReportFindings
    ) -> ExtractedReportFindings:
        errors = check_verbatim(ctx.deps.report_text, output)
        if errors:
            await _emit_progress(
                ctx.deps,
                f"Retrying: verbatim validation failed ({len(errors)} error(s))",
            )
            msg = "\n".join(errors)
            raise ModelRetry(msg)
        return output

    return agent


def create_chunk_agent(
    model: str | None = None,
    *,
    reasoning: str | None = None,
) -> Agent[ExtractorDeps, ExtractedChunkFindings]:
    """Create and configure the chunk extraction agent."""
    if model is None:
        model = get_settings().default_model

    instructions = build_chunk_system_prompt()
    agent = create_resilient_agent(
        model_name=model,
        reasoning=reasoning,
        instructions=instructions,
        output_type=ExtractedChunkFindings,
        deps_type=ExtractorDeps,
        output_retries=3,
    )

    @agent.output_validator
    async def validate_chunk_verbatim(
        ctx: RunContext[ExtractorDeps], output: ExtractedChunkFindings
    ) -> ExtractedChunkFindings:
        errors = check_chunk_verbatim(ctx.deps.report_text, output)
        if errors:
            await _emit_progress(
                ctx.deps,
                f"Retrying: verbatim validation failed ({len(errors)} error(s))",
            )
            msg = "\n".join(errors)
            raise ModelRetry(msg)
        return output

    return agent


def _truncate(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def check_verbatim(report_text: str, output: ExtractedReportFindings) -> list[str]:
    """Check that all extracted text segments appear verbatim in the report.

    Args:
        report_text: The original report text
        output: The extraction to validate

    Returns:
        List of error messages for non-verbatim quotes (empty if all pass)
    """
    errors = []
    for finding in output.findings:
        if not verbatim_match(finding.report_text, report_text):
            errors.append(
                f"Finding '{finding.finding_name}': report_text is not a substring of the "
                f"report. You provided: \"{_truncate(finding.report_text)}\""
            )
    for nft in output.non_finding_text:
        if not verbatim_match(nft.text, report_text):
            errors.append(
                f"Non-finding ({nft.category}): text is not a substring of the "
                f"report. You provided: \"{_truncate(nft.text)}\""
            )
    return errors


def check_chunk_verbatim(report_text: str, output: ExtractedChunkFindings) -> list[str]:
    """Check that all chunk finding evidence spans appear verbatim in chunk text."""
    errors = []
    for finding in output.findings:
        if not verbatim_match(finding.report_text, report_text):
            errors.append(
                f"Finding '{finding.finding_name}': report_text is not a substring of the "
                f"target chunk. You provided: \"{_truncate(finding.report_text)}\""
            )
    return errors


def build_prompt(report_text: str, study_description: str | None = None) -> str:
    """Build the user prompt for the extraction agent.

    Calls ``parse_report_sections()`` to detect section boundaries and inserts a
    section hint before the report text when sections are detected.  The hint
    is placed *outside* the report delimiters so verbatim validation against
    the original text is unaffected.

    Args:
        report_text: The full text of the radiology report
        study_description: Optional exam description for context (e.g., modality, body part)

    Returns:
        Formatted prompt string
    """
    from finding_extractor.extractor.report_sections import parse_report_sections

    parsed = parse_report_sections(report_text)
    prompt_parts = []

    if study_description:
        prompt_parts.append(f"Exam Description: {study_description}")
        prompt_parts.append("")

    section_hint = parsed.format_section_hint()
    if section_hint:
        prompt_parts.append(section_hint)
        prompt_parts.append("")

    prompt_parts.append("RADIOLOGY REPORT:")
    prompt_parts.append("-" * 40)
    prompt_parts.append(report_text)
    prompt_parts.append("-" * 40)
    prompt_parts.append("")
    prompt_parts.append(
        "Extract all findings from this report into the structured format described above."
    )

    return "\n".join(prompt_parts)


def build_chunk_prompt(
    *,
    chunk_text: str,
    section_name: str,
    study_description: str | None = None,
    preceding_chunk_context: str | None = None,
    following_chunk_context: str | None = None,
    feedback: str | None = None,
) -> str:
    """Build the user prompt for chunk-scoped extraction."""
    prompt_parts = []
    if study_description:
        prompt_parts.append(f"Exam Description: {study_description}")
        prompt_parts.append("")

    prompt_parts.append(f"Section: {section_name}")
    if preceding_chunk_context:
        prompt_parts.append(f"Context before (reference-only): {preceding_chunk_context}")
    if following_chunk_context:
        prompt_parts.append(f"Context after (reference-only): {following_chunk_context}")
    prompt_parts.append("")
    prompt_parts.append("TARGET CHUNK:")
    prompt_parts.append("-" * 40)
    prompt_parts.append(chunk_text)
    prompt_parts.append("-" * 40)
    prompt_parts.append("")
    prompt_parts.append("Extract findings only from TARGET CHUNK.")

    if feedback:
        prompt_parts.append("")
        prompt_parts.append(feedback)

    return "\n".join(prompt_parts)


def _capture_usage(result, elapsed_ms: int) -> ExtractionUsage | None:
    usage: ExtractionUsage | None = None
    try:
        run_usage = result.usage()
        details: dict[str, int] = {}
        if run_usage.details:
            details = {k: v for k, v in run_usage.details.items() if isinstance(v, int)}
        usage = ExtractionUsage(
            requests=run_usage.requests,
            input_tokens=run_usage.input_tokens,
            output_tokens=run_usage.output_tokens,
            cache_read_tokens=run_usage.cache_read_tokens,
            cache_write_tokens=run_usage.cache_write_tokens,
            duration_ms=elapsed_ms,
            details=details,
        )
    except Exception:
        logger.debug("Failed to capture usage from agent run", exc_info=True)
    return usage


def _exam_info_from_hint(study_description: str | None) -> ExamInfo:
    description = (study_description or "").strip() or "Radiology study"
    return ExamInfo(study_description=description)


def _chunk_to_report_extraction(
    *,
    chunk_extraction: ExtractedChunkFindings,
    study_description: str | None,
) -> ExtractedReportFindings:
    findings = [
        Finding(
            finding_name=finding.finding_name,
            presence=finding.presence,
            location=finding.location,
            attributes=finding.attributes,
            report_text=finding.report_text,
        )
        for finding in chunk_extraction.findings
    ]
    return ExtractedReportFindings(
        exam_info=_exam_info_from_hint(study_description),
        findings=findings,
        non_finding_text=[],
    )


async def extract_chunk(
    report_text: str,
    *,
    section_name: str,
    study_description: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    preceding_chunk_context: str | None = None,
    following_chunk_context: str | None = None,
    feedback: str | None = None,
    progress_callback: ProgressCallbackType | None = None,
) -> ChunkExtractionResult:
    """Run the dedicated chunk extraction agent on one chunk."""
    agent = create_chunk_agent(model, reasoning=reasoning)
    deps = ExtractorDeps(report_text=report_text, progress_callback=progress_callback)

    prompt = build_chunk_prompt(
        chunk_text=report_text,
        section_name=section_name,
        study_description=study_description,
        preceding_chunk_context=preceding_chunk_context,
        following_chunk_context=following_chunk_context,
        feedback=feedback,
    )
    usage_limits = UsageLimits(request_limit=8)

    await _emit_progress(deps, "Calling model...")
    t0 = time.monotonic()
    result = await agent.run(prompt, deps=deps, usage_limits=usage_limits)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    await _emit_progress(deps, "Model call complete, processing results")

    return ChunkExtractionResult(
        chunk_findings=result.output,
        usage=_capture_usage(result, elapsed_ms),
    )


async def extract_chunk_findings(
    report_text: str,
    study_description: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    *,
    section_name: str = "findings",
    preceding_chunk_context: str | None = None,
    following_chunk_context: str | None = None,
    feedback: str | None = None,
    progress_callback: ProgressCallbackType | None = None,
) -> ExtractionResult:
    """Run chunk extraction and adapt to ExtractedReportFindings for orchestrator merging."""
    chunk_result = await extract_chunk(
        report_text=report_text,
        section_name=section_name,
        study_description=study_description,
        model=model,
        reasoning=reasoning,
        preceding_chunk_context=preceding_chunk_context,
        following_chunk_context=following_chunk_context,
        feedback=feedback,
        progress_callback=progress_callback,
    )
    return ExtractionResult(
        report_findings=_chunk_to_report_extraction(
            chunk_extraction=chunk_result.chunk_findings,
            study_description=study_description,
        ),
        usage=chunk_result.usage,
    )


def validate_extraction(
    report_text: str,
    extraction: ExtractedReportFindings,
) -> ValidationResult:
    """Validate a ExtractedReportFindings against the original report text.

    Performs coverage analysis to identify report text segments that may have
    been skipped during extraction.  Verbatim quote checking is handled by the
    agent's output validator (which retries the model on failure), so it is not
    repeated here.

    Args:
        report_text: The original report text
        extraction: The extracted findings to validate

    Returns:
        ValidationResult with coverage warnings
    """
    coverage_warnings = []

    extracted_texts = [f.report_text for f in extraction.findings]
    extracted_texts.extend(nf.text for nf in extraction.non_finding_text)

    report_lines = report_text.split("\n")
    unaccounted_lines = []

    for line in report_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        found = any(line_stripped in extracted for extracted in extracted_texts)
        if not found:
            unaccounted_lines.append(line_stripped)

    if unaccounted_lines:
        coverage_warnings.append(
            f"Some report lines may not be fully accounted for: {len(unaccounted_lines)} lines. "
            f"Example: '{unaccounted_lines[0][:80]}...'"
        )

    return ValidationResult(
        verbatim_errors=[],
        coverage_warnings=coverage_warnings,
    )
