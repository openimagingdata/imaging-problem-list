"""CLI for the finding extraction agent.

Usage:
    finding-extractor <report_file> [OPTIONS]

Model configuration is controlled via environment variables (or config.toml):

    IPL_MODEL               Extraction model (default: gemini-3-flash-preview)
    IPL_FALLBACK_MODEL      Fallback model for resilience (default: gpt-5.2)
    IPL_REASONING           Default reasoning effort level
    IPL_REVIEWER_ENABLED    Enable per-chunk review pass (default: true)
    IPL_REVIEWER_MODEL      Reviewer model (default: gpt-5.4-mini via Responses API)
    IPL_REVIEWER_REASONING  Reviewer reasoning effort (default: low)

CLI options --model, --reasoning, and --preset override the env var defaults.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click
from asyncer import runnify

from finding_extractor.cli._local_only import (
    apply_cli_override,
    assert_local_only_model,
    print_manifest,
)
from finding_extractor.coding_summary import inline_coding_counts
from finding_extractor.core.logging_setup import setup_logging
from finding_extractor.core.observability import configure_logfire
from finding_extractor.db.store import ExtractionStore
from finding_extractor.extractor.runtime import (
    StorageMetadata,
    resolve_db_path,
    run_extraction_runtime,
)
from finding_extractor.llm.model_settings import (
    PRESET_NAMES,
    format_preset_help_summary,
    get_preset,
)
from finding_extractor.models import ExtractedReportFindings, ValidationResult


def _preflight_local_only(base_url: str, model_name: str) -> None:
    """Verify Ollama is reachable and the requested model is pulled.

    Assumes the policy-level locality checks have already passed. Exits with
    actionable guidance on HTTP-level failures.
    """
    import httpx

    # Derive the native Ollama API URL from the OpenAI-compat URL
    # (e.g. http://localhost:11434/v1 → http://localhost:11434)
    api_base = base_url.rstrip("/").removesuffix("/v1")

    try:
        resp = httpx.get(f"{api_base}/api/tags", timeout=5)
        resp.raise_for_status()
    except httpx.ConnectError:
        click.echo(
            f"[local-only] Cannot connect to Ollama at {api_base}\n"
            "\n"
            "  Is Ollama running? Start it with:\n"
            "    ollama serve",
            err=True,
        )
        sys.exit(1)
    except Exception as exc:
        click.echo(
            f"[local-only] Ollama health check failed: {exc}",
            err=True,
        )
        sys.exit(1)

    # Check if the requested model is pulled
    _, raw_model_id = model_name.split(":", maxsplit=1)
    available = resp.json().get("models", [])
    available_names = [m.get("name", "") for m in available]
    # Match by prefix (e.g. "qwen3.5:35b-a3b" matches "qwen3.5:35b-a3b")
    if not any(name.startswith(raw_model_id) for name in available_names):
        model_list = "\n".join(f"    - {n}" for n in sorted(available_names)) or "    (none)"
        click.echo(
            f"[local-only] Model '{raw_model_id}' is not available in Ollama.\n"
            "\n"
            f"  Pull it with:\n"
            f"    ollama pull {raw_model_id}\n"
            "\n"
            f"  Available models:\n{model_list}",
            err=True,
        )
        sys.exit(1)


async def _run_pipeline(
    report_text: str,
    *,
    study_description: str | None,
    model: str | None,
    reasoning: str | None,
    validate: bool,
    store: bool,
    db_path: Path | None,
    source_ref: str | None,
) -> tuple[ExtractedReportFindings, ValidationResult | None, StorageMetadata | None]:
    """Run extraction, optional validation, and optional persistence."""

    async def _status_cb(message: str) -> None:
        click.echo(message, err=True)

    if not store:
        result = await run_extraction_runtime(
            report_text,
            study_description=study_description,
            model=model,
            reasoning=reasoning,
            validate=validate,
            reliability_mode="strict",
            store=None,
            db_path=None,
            source_ref=source_ref,
            progress_callback=_status_cb,
        )
        return result.extraction, result.validation_result, result.storage_metadata

    resolved_db_path = resolve_db_path(db_path)
    extraction_store = ExtractionStore(resolved_db_path)
    migration_error = await extraction_store.check_migration_current()
    if migration_error is not None:
        await extraction_store.close()
        raise click.ClickException(f"{migration_error} (IPL_DB_PATH={resolved_db_path})")
    await extraction_store.init()
    try:
        result = await run_extraction_runtime(
            report_text,
            study_description=study_description,
            model=model,
            reasoning=reasoning,
            validate=validate,
            reliability_mode="strict",
            store=extraction_store,
            db_path=resolved_db_path,
            source_ref=source_ref,
            progress_callback=_status_cb,
        )
        return result.extraction, result.validation_result, result.storage_metadata
    finally:
        await extraction_store.close()


_run_pipeline_sync = runnify(_run_pipeline)


@click.command()
@click.argument("report_file", type=click.File("r"))
@click.option(
    "--exam-type",
    help="Exam description for context (e.g., modality, body part)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output JSON file (default: stdout)",
)
@click.option(
    "--model",
    "-m",
    help="LLM model override (default: IPL_MODEL env var)",
)
@click.option(
    "--preset",
    "-p",
    type=click.Choice(PRESET_NAMES, case_sensitive=False),
    help=(
        f"Named extraction profile ({format_preset_help_summary()}). "
        "Explicit --model/--reasoning override preset values. Also settable via IPL_PRESET."
    ),
)
@click.option(
    "--reasoning",
    "-r",
    type=click.Choice(["none", "minimal", "low", "medium", "high"], case_sensitive=False),
    help="Reasoning effort level",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "table"], case_sensitive=False),
    default="json",
    help="Output format (default: json)",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Run post-extraction coverage analysis; verbatim checking is handled by the agent's output validator (default: validate)",
)
@click.option(
    "--store/--no-store",
    default=False,
    help="Persist report and extraction metadata to SQLite (default: no-store)",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    help="SQLite path (default: IPL_DB_PATH or .finding_extractor.db)",
)
@click.option(
    "--logfire",
    "logfire_enabled",
    flag_value=True,
    default=None,
    help="Enable Logfire observability for this run (overrides env setting)",
)
@click.option(
    "--no-logfire",
    "logfire_enabled",
    flag_value=False,
    help="Disable Logfire observability for this run (overrides env setting)",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Set logging emission level to INFO for this run.",
)
@click.option(
    "--local-only",
    is_flag=True,
    default=False,
    help="PHI-safe mode: require ollama models only, disable Logfire, block HuggingFace.",
)
def main(
    report_file,
    exam_type,
    output,
    model,
    preset,
    reasoning,
    output_format,
    validate,
    store,
    db_path,
    logfire_enabled,
    verbose,
    local_only,
):
    """Extract structured findings from a radiology report.

    REPORT_FILE is the path to the radiology report text file.
    """
    report_text = report_file.read()

    # Apply CLI overrides so the Layer 1 validator runs with --local-only on.
    extra: dict = {"log_level": "INFO"} if verbose else {}
    settings = apply_cli_override(
        local_only=local_only,
        model_override=model,
        extra_overrides=extra,
    )

    if settings.local_only_mode:
        if logfire_enabled:
            raise click.ClickException("--logfire cannot be used with --local-only")
        # Force logfire off regardless of env
        logfire_enabled = False

    logfire_configured = configure_logfire(runtime="cli", enabled_override=logfire_enabled)
    setup_logging(settings, include_logfire_processor=logfire_configured)

    # Resolve preset: CLI flag > IPL_PRESET config > none
    effective_preset = preset or settings.default_preset
    effective_model = model
    effective_reasoning = reasoning
    if effective_preset is not None:
        preset_obj = get_preset(effective_preset)
        if effective_model is None:
            effective_model = preset_obj.model
        if effective_reasoning is None:
            effective_reasoning = preset_obj.reasoning

    if settings.local_only_mode:
        resolved = effective_model or settings.default_model
        assert_local_only_model(resolved, settings, context="CLI --local-only", preset=effective_preset)

        # settings.ollama_base_url is guaranteed non-empty by the helper above.
        assert settings.ollama_base_url is not None
        _preflight_local_only(settings.ollama_base_url, resolved)
        print_manifest(resolved, settings)

    try:
        extraction, validation_result, storage_metadata = _run_pipeline_sync(
            report_text=report_text,
            study_description=exam_type,
            model=effective_model,
            reasoning=effective_reasoning,
            validate=validate,
            store=store,
            db_path=db_path,
            source_ref=report_file.name,
        )

        if output:
            # Always write JSON to file; optionally also show table on terminal
            json_text = format_json_output(extraction, validation_result, storage_metadata)
            output.write_text(json_text)
            click.echo(f"Output written to {output}", err=True)
            if output_format == "table":
                click.echo(format_table_output(extraction, validation_result, storage_metadata))
        elif output_format == "table":
            click.echo(format_table_output(extraction, validation_result, storage_metadata))
        else:
            click.echo(format_json_output(extraction, validation_result, storage_metadata))

    except Exception as e:
        click.echo(f"Error during extraction: {e}", err=True)
        sys.exit(1)


def format_json_output(
    extraction: ExtractedReportFindings,
    validation_result: ValidationResult | None = None,
    storage_metadata: StorageMetadata | None = None,
) -> str:
    """Format extraction as JSON output."""
    data = extraction.model_dump(mode="json")

    if validation_result is not None:
        data["_validation"] = validation_result.model_dump(mode="json")
    if storage_metadata:
        storage_dict = asdict(storage_metadata)
        if storage_metadata.usage is not None:
            storage_dict["usage"] = storage_metadata.usage.model_dump(mode="json")
        data["_storage"] = storage_dict
    return json.dumps(data, indent=2)


def format_table_output(
    extraction: ExtractedReportFindings,
    validation_result: ValidationResult | None = None,
    storage_metadata: StorageMetadata | None = None,
) -> str:
    """Format extraction as human-readable table/summary."""
    lines = []

    lines.append("=" * 70)
    lines.append("RADIOLOGY REPORT EXTRACTION")
    lines.append("=" * 70)
    lines.append("")

    lines.append(f"Study: {extraction.exam_info.study_description}")
    if extraction.exam_info.study_date:
        lines.append(f"Date: {extraction.exam_info.study_date}")
    if extraction.exam_info.modality:
        lines.append(f"Modality: {extraction.exam_info.modality}")
    if extraction.exam_info.body_region:
        lines.append(f"Body Region: {extraction.exam_info.body_region}")
    if extraction.exam_info.body_part:
        lines.append(f"Body Part: {extraction.exam_info.body_part}")
    if extraction.exam_info.contrast:
        lines.append(f"Contrast: {extraction.exam_info.contrast}")
    lines.append("")

    present = [f for f in extraction.findings if f.presence == "present"]
    absent = [f for f in extraction.findings if f.presence == "absent"]
    possible = [f for f in extraction.findings if f.presence == "possible"]
    indeterminate = [f for f in extraction.findings if f.presence == "indeterminate"]

    lines.append("-" * 70)
    lines.append(f"FINDINGS SUMMARY: {len(extraction.findings)} total")
    lines.append(
        f"  Present: {len(present)} | Absent: {len(absent)}"
        f" | Possible: {len(possible)} | Indeterminate: {len(indeterminate)}"
    )
    lines.append("-" * 70)
    lines.append("")

    if present:
        lines.append("PRESENT FINDINGS:")
        lines.append("")
        for i, finding in enumerate(present, 1):
            lines.append(f"  {i}. {finding.finding_name}")
            if finding.location:
                loc_parts = [finding.location.body_region]
                if finding.location.specific_anatomy:
                    loc_parts.append(finding.location.specific_anatomy)
                if finding.location.laterality:
                    loc_parts.append(f"({finding.location.laterality})")
                lines.append(f"     Location: {' - '.join(loc_parts)}")
            if finding.attributes:
                attrs = ", ".join(f"{a.key}={a.value}" for a in finding.attributes)
                lines.append(f"     Attributes: {attrs}")
            text_preview = finding.report_text[:60]
            ellipsis = "..." if len(finding.report_text) > 60 else ""
            lines.append(f'     Text: "{text_preview}{ellipsis}"')
            lines.append("")

    if absent:
        lines.append("ABSENT FINDINGS (ruled out):")
        absent_names = [f.finding_name for f in absent]
        for i in range(0, len(absent_names), 4):
            chunk = absent_names[i : i + 4]
            lines.append(f"  {', '.join(chunk)}")
        lines.append("")

    if possible:
        lines.append("POSSIBLE FINDINGS (hedged/uncertain):")
        for finding in possible:
            lines.append(f"  - {finding.finding_name}")
        lines.append("")

    if extraction.non_finding_text:
        lines.append("-" * 70)
        lines.append(f"NON-FINDING TEXT: {len(extraction.non_finding_text)} segments")
        categories: dict[str, int] = {}
        for nft in extraction.non_finding_text:
            categories[nft.category] = categories.get(nft.category, 0) + 1
        for cat, count in sorted(categories.items()):
            lines.append(f"  {cat}: {count}")
        lines.append("")

    if validation_result:
        lines.append("-" * 70)
        lines.append("VALIDATION:")
        if len(validation_result.verbatim_errors) == 0:
            lines.append("  Status: PASSED")
        else:
            lines.append("  Status: FAILED")

        if validation_result.verbatim_errors:
            lines.append(f"  Verbatim Errors: {len(validation_result.verbatim_errors)}")
            for error in validation_result.verbatim_errors[:3]:
                lines.append(f"    - {error[:80]}")
            if len(validation_result.verbatim_errors) > 3:
                lines.append(f"    ... and {len(validation_result.verbatim_errors) - 3} more")

        if validation_result.coverage_warnings:
            lines.append(f"  Coverage Warnings: {len(validation_result.coverage_warnings)}")
            for warning in validation_result.coverage_warnings[:2]:
                lines.append(f"    - {warning[:80]}")
        lines.append("")

    coded_count, unresolved_count = inline_coding_counts(extraction)
    if coded_count is not None and unresolved_count is not None:
        unresolved_names = [
            finding.finding_name
            for finding in extraction.findings
            if finding.coding is not None and finding.coding.finding_code.status == "unmapped"
        ]
        lines.append("-" * 70)
        lines.append("CODING:")
        lines.append(f"  Findings coded: {coded_count} | Unresolved: {unresolved_count}")
        if unresolved_names:
            preview = unresolved_names[:5]
            lines.append(f"  Unresolved names: {', '.join(preview)}")
            if len(preview) != len(unresolved_names):
                lines.append(f"  ... and {len(unresolved_names) - len(preview)} more")
        lines.append("")

    if storage_metadata:
        lines.append("-" * 70)
        lines.append("PERSISTENCE:")
        lines.append(f"  DB Path: {storage_metadata.db_path}")
        lines.append(f"  Report ID: {storage_metadata.report_id}")
        lines.append(f"  Seen Before: {storage_metadata.report_seen_before}")
        lines.append(f"  Extraction ID: {storage_metadata.extraction_id}")
        lines.append(f"  Model: {storage_metadata.model_name}")
        lines.append(f"  Timestamp: {storage_metadata.extracted_at}")
        if storage_metadata.usage:
            u = storage_metadata.usage
            lines.append(
                f"  Tokens: {u.input_tokens} in / {u.output_tokens} out"
                f" | Cache: {u.cache_read_tokens} read / {u.cache_write_tokens} write"
                f" | Requests: {u.requests}"
            )
            if u.duration_ms is not None:
                lines.append(f"  Duration: {u.duration_ms / 1000:.1f}s")
        lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


if __name__ == "__main__":
    main()
