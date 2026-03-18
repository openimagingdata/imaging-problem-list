"""CLI for the post-extraction coding pipeline.

Usage:
    finding-extractor-code <extraction_json> [OPTIONS]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from asyncer import runnify

from finding_extractor.coding.runtime import run_coding
from finding_extractor.core.config import get_settings
from finding_extractor.core.logging_setup import setup_logging
from finding_extractor.core.observability import configure_logfire
from finding_extractor.llm.policy import validate_model_id
from finding_extractor.models import ExtractedReportFindings


async def _run_coding_pipeline(
    extraction: ExtractedReportFindings,
    *,
    model: str | None,
    reasoning: str | None,
) -> ExtractedReportFindings:
    """Run the coding pipeline and return the updated extraction."""

    async def _status_cb(message: str) -> None:
        click.echo(message, err=True)

    result = await run_coding(
        extraction,
        model=model,
        reasoning=reasoning,
        progress_callback=_status_cb,
    )
    return result.extraction


_run_coding_pipeline_sync = runnify(_run_coding_pipeline)


def format_coding_json_output(extraction: ExtractedReportFindings) -> str:
    """Format a coded extraction as pretty JSON."""
    return json.dumps(extraction.model_dump(mode="json"), indent=2)


@click.command(name="finding-extractor-code")
@click.argument("extraction_json", type=click.File("r"))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output JSON file (default: stdout)",
)
@click.option(
    "--model",
    "-m",
    help="LLM model override (default: IPL_CODING_MODEL or config default)",
)
@click.option(
    "--reasoning",
    "-r",
    type=click.Choice(["none", "minimal", "low", "medium", "high"], case_sensitive=False),
    help="Reasoning effort level",
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
def main(
    extraction_json,
    output,
    model,
    reasoning,
    logfire_enabled,
    verbose,
):
    """Assign codes to an extracted report JSON payload."""

    settings = get_settings()
    if verbose:
        settings = settings.model_copy(update={"log_level": "INFO"})
    logfire_configured = configure_logfire(runtime="cli", enabled_override=logfire_enabled)
    setup_logging(settings, include_logfire_processor=logfire_configured)

    effective_model = model or settings.coding_model
    try:
        validate_model_id(effective_model)
        extraction = ExtractedReportFindings.model_validate_json(extraction_json.read())
        coded = _run_coding_pipeline_sync(
            extraction=extraction,
            model=model,
            reasoning=reasoning,
        )
        output_text = format_coding_json_output(coded)
        if output:
            output.write_text(output_text)
            click.echo(f"Output written to {output}")
        else:
            click.echo(output_text)
    except Exception as exc:
        click.echo(f"Error during coding: {exc}", err=True)
        sys.exit(1)

