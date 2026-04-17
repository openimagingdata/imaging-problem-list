"""Shared helpers for ``--local-only`` enforcement across finding-extractor CLIs.

CLIs use three steps: (1) apply the ``--local-only`` flag as a settings
override so the Layer 1 validator runs, (2) enforce the model/endpoint gates
on the resolved model, (3) print the operator-visible manifest. This module
provides the shared implementation; CLI-specific concerns (the extract CLI's
``--logfire`` incompatibility guard, preset resolution) stay in the callers.
"""

from __future__ import annotations

from typing import Any

import click

from finding_extractor.core.config import ExtractorSettings, get_settings, override_settings
from finding_extractor.llm.policy import (
    LocalOnlyViolationError,
    enforce_local_only,
    provider_from_model_id,
)


def apply_cli_override(
    *,
    local_only: bool,
    extra_overrides: dict[str, Any] | None = None,
) -> ExtractorSettings:
    """Rebuild settings with CLI overrides applied and inject into the global cache.

    Round-trips through ``model_dump`` / ``model_validate`` so the Layer 1
    validator runs (``model_copy(update=...)`` skips validators).
    """
    settings = get_settings()
    if not local_only and not extra_overrides:
        return settings
    overrides = settings.model_dump()
    if local_only:
        overrides["local_only_mode"] = True
    if extra_overrides:
        overrides.update(extra_overrides)
    new_settings = ExtractorSettings.model_validate(overrides)
    override_settings(new_settings)
    return new_settings


def assert_local_only_model(
    resolved_model: str,
    settings: ExtractorSettings,
    *,
    context: str,
    preset: str | None = None,
) -> None:
    """Run the local-only policy check, converting violations to click errors.

    When ``preset`` is provided and the resolved model is non-Ollama, raise a
    preset-specific error message that names the offending preset — easier to
    act on than the generic "not an Ollama model" violation.
    """
    if preset is not None and provider_from_model_id(resolved_model) != "ollama":
        raise click.ClickException(
            f"[{context}] Preset {preset!r} selects cloud model "
            f"{resolved_model!r}. Use --preset local (or omit --preset)."
        )
    try:
        enforce_local_only(
            resolved_model,
            local_only_mode=True,
            ollama_base_url=settings.ollama_base_url,
            context=context,
        )
    except LocalOnlyViolationError as exc:
        raise click.ClickException(str(exc)) from exc


def print_manifest(
    resolved_model: str,
    settings: ExtractorSettings,
    *,
    extras: dict[str, str] | None = None,
) -> None:
    """Print the ``[local-only]`` manifest to stderr.

    ``extras`` adds caller-specific lines between the common body and the
    closing Modelfile-alias warning (e.g. the batch CLI adds an ``inputs`` count).
    """
    fallback = settings.fallback_model or "(none)"
    reviewer = settings.reviewer_model if settings.reviewer_enabled else "disabled"
    lines = [
        "[local-only] Preflight passed. No report text or extraction output will leave this machine.",
        f"  model               = {resolved_model}",
        f"  ollama endpoint     = {settings.ollama_base_url}",
        f"  fallback_model      = {fallback}",
        f"  reviewer            = {reviewer}",
        "  coding              = disallowed",
        "  logfire             = disabled (overridden)",
        "  model downloads     = allowed (no PHI sent)",
    ]
    if extras:
        for key, value in extras.items():
            lines.append(f"  {key:<20}= {value}")
    lines.append(
        "  \u26a0 model provenance  = NOT verified \u2014 do not use Modelfiles whose FROM points at a :cloud source"
    )
    click.echo("\n".join(lines), err=True)
