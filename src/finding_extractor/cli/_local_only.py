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
from pydantic import ValidationError

from finding_extractor.core.config import ExtractorSettings, get_settings, override_settings
from finding_extractor.llm.policy import (
    LocalOnlyViolationError,
    enforce_local_only,
    provider_from_model_id,
)


def apply_cli_override(
    *,
    local_only: bool,
    model_override: str | None = None,
    extra_overrides: dict[str, Any] | None = None,
) -> ExtractorSettings:
    """Rebuild settings with CLI overrides applied and inject into the global cache.

    Round-trips through ``model_dump`` / ``model_validate`` so the Layer 1
    validator runs (``model_copy(update=...)`` skips validators).

    ``model_override`` injects the CLI ``--model`` flag as ``default_model`` so
    the Layer 1 validator sees the effective model. Without this, a user
    running ``--local-only --model ollama:X`` would hit the validator at
    settings load (before the CLI flag had a chance to propagate) and be
    rejected for whatever ``IPL_MODEL`` happened to be in their env.
    """
    settings = get_settings()
    if not local_only and model_override is None and not extra_overrides:
        return settings
    # ``exclude_unset=True`` preserves the "user didn't set this" signal
    # through the round-trip, so the ``mode="before"`` model_validator can
    # apply local-friendly defaults only to genuinely unset fields.
    overrides = settings.model_dump(exclude_unset=True)
    if local_only:
        overrides["local_only_mode"] = True
    if model_override is not None:
        overrides["default_model"] = model_override
    if extra_overrides:
        overrides.update(extra_overrides)
    try:
        new_settings = ExtractorSettings.model_validate(overrides)
    except ValidationError as exc:
        # CLI validation failures should surface as clean Click errors rather
        # than pydantic tracebacks. Prefer the underlying ``ctx.error`` message
        # (the string the field/model validator actually raised), else fall
        # back to pydantic's ``msg``.
        errors = exc.errors()
        if errors:
            first = errors[0]
            cause = first.get("ctx", {}).get("error")
            message = str(cause) if cause is not None else first.get("msg", str(exc))
            raise click.ClickException(message) from exc
        raise
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

    When ``preset`` is provided and the resolved model is not approved, raise a
    preset-specific error message that names the offending preset — easier to
    act on than the generic provider violation.
    """
    provider = provider_from_model_id(resolved_model)
    if preset is not None and provider not in {"ollama", "vllm"}:
        raise click.ClickException(
            f"[{context}] Preset {preset!r} selects cloud model "
            f"{resolved_model!r}. Use --preset local (or omit --preset)."
        )
    try:
        enforce_local_only(
            resolved_model,
            local_only_mode=True,
            ollama_base_url=settings.ollama_base_url,
            vllm_base_url=settings.vllm_base_url_for_model_optional(resolved_model)
            if provider == "vllm"
            else None,
            vllm_allowed_hosts=settings.vllm_local_only_allowed_hosts,
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
    provider = provider_from_model_id(resolved_model)
    endpoint_label = "ollama endpoint"
    endpoint_value = settings.ollama_base_url or "(none)"
    if provider == "vllm":
        endpoint_label = "vllm endpoint"
        endpoint_value = settings.vllm_base_url_for_model(resolved_model)
    lines = [
        "[local-only] Preflight passed. Inference is restricted to approved local/on-prem endpoints.",
        f"  model               = {resolved_model}",
        f"  {endpoint_label:<20}= {endpoint_value}",
        f"  fallback_model      = {fallback}",
        f"  reviewer            = {reviewer}",
        "  coding              = disallowed",
        "  logfire             = disabled (overridden)",
        "  model downloads     = allowed (no PHI sent)",
    ]
    if extras:
        for key, value in extras.items():
            lines.append(f"  {key:<20}= {value}")
    if provider == "ollama":
        lines.append(
            "  \u26a0 model provenance  = NOT verified \u2014 do not use Modelfiles whose FROM points at a :cloud source"
        )
    click.echo("\n".join(lines), err=True)
