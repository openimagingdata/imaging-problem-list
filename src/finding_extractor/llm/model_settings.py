"""Provider-specific model settings configuration.

This module manages reasoning/thinking configuration for supported LLM providers:
- OpenAI (reasoning effort: none, minimal, low, medium, high)
- Anthropic (adaptive thinking for 4.6+, budget-based extended thinking for older models)
- Google (thinking levels: NONE, MINIMAL, LOW, MEDIUM, HIGH)
- OpenRouter (effort-based reasoning: low, medium, high)
- Ollama (model-specific thinking support via ``extra_body.think``)

Each provider has:
- Default reasoning level when unspecified
- Supported reasoning levels (validation)
- Settings builder function that returns provider-specific ModelSettings

Architecture:
- Provider detection is imported from `model_policy.py` (canonical source)
- This module focuses on runtime settings construction for extraction agent
- `model_policy.py` handles validation, SOTA filtering, and model ID parsing
"""

import re
from dataclasses import dataclass
from typing import Literal, get_args

from anthropic.types.beta import (
    BetaThinkingConfigAdaptiveParam,
    BetaThinkingConfigDisabledParam,
    BetaThinkingConfigEnabledParam,
)
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.google import GoogleModelSettings
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.settings import ModelSettings

from finding_extractor.core.config import get_settings
from finding_extractor.llm.defaults import (
    MODEL_ANTHROPIC_CLAUDE_OPUS_4_6,
    MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW,
    MODEL_OLLAMA_QWEN35_35B_A3B,
    MODEL_OPENAI_GPT_5_2,
)
from finding_extractor.llm.policy import (
    anthropic_model_minor,
    provider_from_model_id,
    validate_model_id,
)
from finding_extractor.models import ReasoningLevel

# ---------------------------------------------------------------------------
# Reasoning level constants and validation
# ---------------------------------------------------------------------------

VALID_REASONING_LEVELS: tuple[str, ...] = get_args(ReasoningLevel)

# Default reasoning level per provider (when --reasoning is omitted)
PROVIDER_DEFAULT_REASONING: dict[str, str] = {
    "openai": "medium",
    "anthropic": "medium",
    "google": "low",
    "openrouter": "medium",
    "ollama": "none",
}

PROVIDER_SUPPORTED_REASONING: dict[str, set[str]] = {
    "openai": set(VALID_REASONING_LEVELS),
    "anthropic": set(VALID_REASONING_LEVELS),
    "google": set(VALID_REASONING_LEVELS),
    "openrouter": set(VALID_REASONING_LEVELS),
    "ollama": {"none"},
}

# Anthropic thinking budget mapping: level -> (budget_tokens, max_tokens)
# Used for pre-4.6 models with budget-based extended thinking.
ANTHROPIC_THINKING_BUDGETS: dict[str, tuple[int, int]] = {
    "minimal": (1024, 8192),
    "low": (1024, 8192),
    "medium": (4096, 8192),
    "high": (10240, 16384),
}

# Anthropic adaptive thinking effort mapping: reasoning level -> anthropic_effort
# Used for 4.6+ models (Opus 4.6, Sonnet 4.6, etc.).
AnthropicEffort = Literal["low", "medium", "high", "max"]

ANTHROPIC_EFFORT_MAP: dict[str, AnthropicEffort] = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
}


def _anthropic_uses_adaptive_thinking(model: str) -> bool:
    """Return True if the Anthropic model supports adaptive thinking.

    Models with minor version >= 6 (e.g., claude-opus-4-6, claude-sonnet-4-6)
    use adaptive thinking with effort levels instead of budget-based extended thinking.
    """
    minor = anthropic_model_minor(model)
    return minor is not None and minor >= 6


# ---------------------------------------------------------------------------
# Extraction presets: named (model, reasoning) configurations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractionPreset:
    """Named (model, reasoning) configuration for common extraction profiles."""

    name: str
    model: str
    reasoning: str
    description: str


EXTRACTION_PRESETS: dict[str, ExtractionPreset] = {
    "fast": ExtractionPreset(
        name="fast",
        model=MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW,
        reasoning="low",
        description="High-throughput extraction (Gemini Flash, low thinking)",
    ),
    "balanced": ExtractionPreset(
        name="balanced",
        model=MODEL_OPENAI_GPT_5_2,
        reasoning="low",
        description="Stable extraction baseline (GPT-5.2, low reasoning)",
    ),
    "quality": ExtractionPreset(
        name="quality",
        model=MODEL_ANTHROPIC_CLAUDE_OPUS_4_6,
        reasoning="low",
        description="Higher-quality extraction (Claude Opus 4.6, low thinking)",
    ),
    "local": ExtractionPreset(
        name="local",
        model=MODEL_OLLAMA_QWEN35_35B_A3B,
        reasoning="none",
        description="Local default (Qwen3.5 35b MoE, 23GB), no API keys needed",
    ),
}

PRESET_NAMES: tuple[str, ...] = tuple(EXTRACTION_PRESETS.keys())


def get_preset(name: str) -> ExtractionPreset:
    """Look up a preset by name (case-insensitive).

    Raises ``ValueError`` if the preset name is not recognized.
    """
    preset = EXTRACTION_PRESETS.get(name.lower())
    if preset is None:
        allowed = ", ".join(PRESET_NAMES)
        raise ValueError(f"Unknown preset {name!r}; must be one of: {allowed}")
    return preset


def validate_all_presets() -> None:
    """Verify all preset model IDs pass model policy validation."""
    for preset in EXTRACTION_PRESETS.values():
        validate_model_id(preset.model)


def format_preset_help_summary() -> str:
    """Return deterministic CLI help text for preset model/reasoning pairs."""
    parts: list[str] = []
    for name in PRESET_NAMES:
        preset = EXTRACTION_PRESETS[name]
        parts.append(f"{preset.name}={preset.model}/{preset.reasoning}")
    return ", ".join(parts)


def validate_reasoning(reasoning: str) -> ReasoningLevel:
    """Validate that *reasoning* is one of the accepted levels.

    Raises ``ValueError`` with a descriptive message when it is not.
    Returns the validated level for convenience.
    """
    if reasoning not in VALID_REASONING_LEVELS:
        allowed = ", ".join(VALID_REASONING_LEVELS)
        raise ValueError(f"Invalid reasoning level {reasoning!r}; must be one of: {allowed}")
    return reasoning  # type: ignore[return-value]


def validate_reasoning_for_model(model: str, reasoning: str) -> ReasoningLevel:
    """Validate *reasoning* is compatible with the provider behind *model*.

    Raises ``ValueError`` when the provider does not support the level
    (e.g. ``ollama:llama4`` with ``reasoning="high"``).
    Returns the validated level for convenience.
    """
    level = validate_reasoning(reasoning)
    provider = provider_from_model_id(model)
    if provider is None:
        return level  # unknown provider — let the agent handle it
    if provider == "ollama":
        model_supported = _ollama_supported_reasoning_for_model(model)
        if model_supported is None:
            # Conservative fallback for unknown Ollama families.
            if level != "none":
                raise ValueError(
                    f"Reasoning level {reasoning!r} is not supported by {provider} models; "
                    "supported levels: none"
                )
            return level
        return _resolve_ollama_reasoning_for_model(model, level)  # type: ignore[return-value]
    supported = PROVIDER_SUPPORTED_REASONING.get(provider)
    if supported is not None and reasoning not in supported:
        allowed = ", ".join(sorted(supported))
        raise ValueError(
            f"Reasoning level {reasoning!r} is not supported by {provider} models; "
            f"supported levels: {allowed}"
        )
    if provider == "google":
        return _resolve_google_reasoning_for_model(model, level)  # type: ignore[return-value]
    return level


def _google_supported_reasoning_for_model(model: str) -> set[str] | None:
    """Return supported reasoning levels for known Gemini-3 families."""
    if ":" not in model:
        return None
    _, raw_model_id = model.split(":", maxsplit=1)
    lowered = raw_model_id.lower()
    match = re.match(r"^gemini-3(?:\.\d+)?-(?P<tier>pro|flash)(?:-|$)", lowered)
    if match is None:
        return None
    tier = match.group("tier")
    if tier == "pro":
        return {"low", "high"}
    if tier == "flash":
        return {"minimal", "low", "medium", "high"}
    return None


def _resolve_google_reasoning_for_model(model: str, reasoning_level: str) -> str:
    """Resolve Google reasoning level with Gemini-3 family constraints.

    Gemini 3 Pro supports low/high; Gemini 3 Flash supports minimal/low/medium/high.
    For reasoning='none', map to nearest practical equivalent per family.
    """
    supported = _google_supported_reasoning_for_model(model)
    if supported is None:
        return reasoning_level

    if reasoning_level == "none":
        # Gemini 3 doesn't support fully disabled thinking; use closest level.
        if "minimal" in supported:
            return "minimal"
        return "low"

    if reasoning_level in supported:
        return reasoning_level

    allowed = ", ".join(sorted(supported))
    raise ValueError(
        f"Reasoning level {reasoning_level!r} is not supported by {model}; "
        f"supported levels: {allowed}"
    )


def _openai_supported_reasoning_for_model(model: str) -> set[str] | None:
    """Return supported reasoning levels for known OpenAI model families."""
    if ":" not in model:
        return None
    _, raw_model_id = model.split(":", maxsplit=1)
    lowered = raw_model_id.lower()
    if lowered.startswith("gpt-5.2"):
        # gpt-5.2 rejects "minimal"; accepted tiers are none/low/medium/high(/xhigh).
        return {"none", "low", "medium", "high"}
    if lowered.startswith("gpt-5"):
        return set(VALID_REASONING_LEVELS)
    return None


def ollama_needs_native_output(model_name: str) -> bool:
    """Return True if this Ollama model needs PydanticAI's NativeOutput mode.

    Some Ollama model families don't handle tool-calling reliably (empty
    responses, text-instead-of-tool-call, or Ollama rejecting tools entirely).
    For these models, PydanticAI's ``NativeOutput`` (JSON schema mode) works.

    Returns False for non-Ollama models.
    """
    provider = provider_from_model_id(model_name)
    if provider != "ollama":
        return False
    if ":" not in model_name:
        return True  # unknown Ollama model — conservative default
    _, raw_model_id = model_name.split(":", maxsplit=1)
    lowered = raw_model_id.lower()

    # nemotron-cascade-2 appears tool-capable in Ollama's catalog, but under
    # the extractor's structured chunk schema it exhibits the same
    # UnexpectedModelBehavior retry loop we saw from other models that need
    # NativeOutput. Keep other Nemotron families tool-capable for now.
    if lowered.startswith("nemotron-cascade-2"):
        return True

    # Families known to work with tool calling
    tool_capable_prefixes = (
        "gpt-oss",
        "llama3", "llama4",
        "qwen3", "qwen3.5",
        "nemotron",
    )
    # Everything else (gemma3, gemma4 MoE, deepseek-r1, medgemma, unknown) — use native
    return all(not lowered.startswith(prefix) for prefix in tool_capable_prefixes)


def _ollama_supported_reasoning_for_model(model: str) -> set[str] | None:
    """Return supported reasoning levels for known Ollama model families."""
    if ":" not in model:
        return None
    _, raw_model_id = model.split(":", maxsplit=1)
    lowered = raw_model_id.lower()
    if lowered.startswith("qwen3.5"):
        # Qwen3.5 thinks by default; reasoning_effort controls it via OpenAI-compat API
        return {"none", "low", "medium", "high"}
    if lowered.startswith("nemotron-cascade-2"):
        # Ollama marks nemotron-cascade-2 as a thinking-capable model on the
        # OpenAI-compatible API, so it should accept reasoning_effort tiers.
        return {"none", "low", "medium", "high"}
    if lowered.startswith("qwen3:30b") and "thinking" in lowered:
        return set(VALID_REASONING_LEVELS)
    if lowered.startswith("qwen3:30b") and "instruct" in lowered:
        return {"none"}
    if lowered.startswith("gpt-oss:120b"):
        # gpt-oss expects low|medium|high natively; we normalize "minimal" -> "low"
        return {"none", "low", "medium", "high"}
    if lowered.startswith(("llama3", "llama3.1", "llama3.2", "llama3.3", "llama4")):
        return {"none"}
    return None


def _resolve_ollama_reasoning_for_model(
    model: str,
    reasoning_level: str,
    *,
    allow_unknown_model_reasoning: bool = False,
) -> str:
    """Resolve Ollama reasoning with model-family compatibility checks."""
    supported = _ollama_supported_reasoning_for_model(model)
    if supported is None:
        if allow_unknown_model_reasoning:
            return reasoning_level
        msg = (
            f"Cannot verify reasoning compatibility for model {model!r}. "
            "Set IPL_ALLOW_UNKNOWN_MODEL_REASONING=true to bypass."
        )
        raise ValueError(msg)

    if reasoning_level in supported:
        return reasoning_level
    if reasoning_level == "minimal" and "low" in supported:
        return "low"

    allowed = ", ".join(sorted(supported))
    raise ValueError(
        f"Reasoning level {reasoning_level!r} is not supported by {model}; "
        f"supported levels: {allowed}"
    )


def resolve_runtime_reasoning(
    model: str,
    reasoning: str | None = None,
    *,
    allow_unknown_model_reasoning: bool = False,
) -> str | None:
    """Resolve runtime reasoning with model-family compatibility checks.

    Behavior:
    - resolve requested level: explicit arg -> settings.default_reasoning -> provider default
    - auto-normalize known-safe incompatibilities
    - fail fast when compatibility is unknown/unverifiable unless override is enabled
    """
    provider = provider_from_model_id(model)
    settings = get_settings()
    level = (
        reasoning
        or settings.default_reasoning
        or (PROVIDER_DEFAULT_REASONING.get(provider) if provider else None)
    )
    if level is None:
        return None

    validated_level = validate_reasoning(level)
    if provider is None:
        if allow_unknown_model_reasoning:
            return validated_level
        msg = (
            f"Cannot verify reasoning compatibility for unknown provider model {model!r}. "
            "Set IPL_ALLOW_UNKNOWN_MODEL_REASONING=true to bypass."
        )
        raise ValueError(msg)

    if provider == "google":
        return _resolve_google_reasoning_for_model(model, validated_level)

    if provider == "openai":
        supported = _openai_supported_reasoning_for_model(model)
        if supported is None:
            if allow_unknown_model_reasoning:
                return validated_level
            msg = (
                f"Cannot verify reasoning compatibility for model {model!r}. "
                "Set IPL_ALLOW_UNKNOWN_MODEL_REASONING=true to bypass."
            )
            raise ValueError(msg)
        if validated_level in supported:
            return validated_level
        if validated_level == "minimal" and "low" in supported:
            return "low"
        allowed = ", ".join(sorted(supported))
        raise ValueError(
            f"Reasoning level {validated_level!r} is not supported by {model}; "
            f"supported levels: {allowed}"
        )

    if provider == "ollama":
        return _resolve_ollama_reasoning_for_model(
            model,
            validated_level,
            allow_unknown_model_reasoning=allow_unknown_model_reasoning,
        )

    return validate_reasoning_for_model(model, validated_level)


def build_openai_settings(reasoning_level: str) -> OpenAIChatModelSettings:
    """Build OpenAI model settings with reasoning effort."""
    return OpenAIChatModelSettings(openai_reasoning_effort=reasoning_level)  # type: ignore[typeddict-item]


def build_anthropic_settings(
    reasoning_level: str, *, model: str
) -> AnthropicModelSettings | None:
    """Build Anthropic model settings with thinking configuration.

    Opus 4.6+ models use adaptive thinking with effort levels.
    Older models use budget-based extended thinking.
    """
    if reasoning_level == "none":
        # Unlike OpenAI/Google, Anthropic needs an explicit disable — returning None
        # would leave agent-level defaults (thinking enabled) in effect.
        return AnthropicModelSettings(
            anthropic_thinking=BetaThinkingConfigDisabledParam(type="disabled"),
        )

    # 4.6+ models use adaptive thinking with effort levels
    if _anthropic_uses_adaptive_thinking(model):
        return AnthropicModelSettings(
            anthropic_thinking=BetaThinkingConfigAdaptiveParam(type="adaptive"),
            anthropic_effort=ANTHROPIC_EFFORT_MAP[reasoning_level],
        )

    # Older models: budget-based extended thinking
    budget_tokens, max_tokens = ANTHROPIC_THINKING_BUDGETS[reasoning_level]
    return AnthropicModelSettings(
        anthropic_thinking=BetaThinkingConfigEnabledParam(type="enabled", budget_tokens=budget_tokens),
        max_tokens=max_tokens,
    )


def build_google_settings(reasoning_level: str) -> GoogleModelSettings:
    """Build Google model settings with thinking level."""
    level_map = {
        "none": "NONE",
        "minimal": "MINIMAL",
        "low": "LOW",
        "medium": "MEDIUM",
        "high": "HIGH",
    }
    return GoogleModelSettings(
        google_thinking_config={"thinking_level": level_map[reasoning_level]},
    )


def build_openrouter_settings(reasoning_level: str) -> OpenRouterModelSettings:
    """Build OpenRouter model settings with reasoning effort.

    OpenRouter supports effort-based reasoning (low, medium, high) similar to OpenAI.
    We map our "minimal" level to "low" since OpenRouter doesn't have a minimal tier.
    For "none", we disable reasoning explicitly with {"enabled": False}.
    """
    if reasoning_level == "none":
        return OpenRouterModelSettings(
            openrouter_reasoning={"enabled": False},
        )
    # Map minimal → low for OpenRouter (it only supports low/medium/high)
    effort = "low" if reasoning_level == "minimal" else reasoning_level
    return OpenRouterModelSettings(
        openrouter_reasoning={"effort": effort},
    )


def build_ollama_settings(model: str, reasoning_level: str) -> OpenAIChatModelSettings | None:
    """Build Ollama settings using model-specific thinking support.

    Qwen3.5 and nemotron-cascade-2 use ``reasoning_effort`` on the
    OpenAI-compatible API to control or disable thinking. Qwen3 and gpt-oss use
    ``extra_body.think``.
    """
    if ":" not in model:
        return None

    _, raw_model_id = model.split(":", maxsplit=1)
    lowered = raw_model_id.lower()

    if lowered.startswith(("qwen3.5", "nemotron-cascade-2")):
        # Qwen3.5 thinks by default — must explicitly set reasoning_effort
        # to "none" to disable, or to "low"/"medium"/"high" to control level.
        # Ollama exposes nemotron-cascade-2 through the same reasoning_effort
        # surface on /v1/chat/completions.
        effort = "none" if reasoning_level == "none" else reasoning_level
        if effort == "minimal":
            effort = "low"
        return OpenAIChatModelSettings(openai_reasoning_effort=effort)  # type: ignore[typeddict-item]

    if lowered.startswith("qwen3:30b") and "thinking" in lowered:
        return OpenAIChatModelSettings(extra_body={"think": reasoning_level != "none"})

    if lowered.startswith("gpt-oss:120b"):
        if reasoning_level == "none":
            return None
        think_level = "low" if reasoning_level == "minimal" else reasoning_level
        return OpenAIChatModelSettings(extra_body={"think": think_level})

    return None



def get_model_settings(model: str, reasoning: str | None = None) -> ModelSettings | None:
    """Build provider-appropriate ModelSettings for the agent.

    Pure builder — callers supply a pre-resolved reasoning level (from
    ``resolve_runtime_reasoning()``).  If *reasoning* is ``None``, returns
    ``None`` (no settings needed).

    Provider-specific normalization (Google family constraints, Ollama
    think modes) is still applied here because the builder must produce
    correct provider settings regardless of how the level was resolved.

    Args:
        model: The model identifier (e.g., "openai:gpt-5-mini")
        reasoning: Pre-resolved reasoning level, or None for no settings

    Returns:
        Provider-specific ModelSettings, or None if no settings needed
    """
    if reasoning is None:
        return None

    provider = provider_from_model_id(model)
    if provider is None:
        return None

    level = reasoning
    if provider == "google":
        level = _resolve_google_reasoning_for_model(model, level)
    elif provider == "ollama":
        level = _resolve_ollama_reasoning_for_model(
            model,
            level,
            allow_unknown_model_reasoning=True,
        )

    builders = {
        "openai": build_openai_settings,
        "anthropic": lambda v: build_anthropic_settings(v, model=model),
        "google": build_google_settings,
        "openrouter": build_openrouter_settings,
        "ollama": lambda v: build_ollama_settings(model, v),
    }

    builder = builders.get(provider)
    if builder is None:
        return None

    return builder(level)


def model_reasoning_capabilities(model: str) -> tuple[list[str], str]:
    """Return model-aware (supported_levels, default_reasoning) capability metadata."""
    provider = provider_from_model_id(model)
    if provider is None:
        return [], "none"

    default = PROVIDER_DEFAULT_REASONING.get(provider, "none")
    if provider == "google":
        supported = _google_supported_reasoning_for_model(model)
        if supported is None:
            return sorted(PROVIDER_SUPPORTED_REASONING.get(provider, set())), default
        effective = set(supported)
        effective.add("none")
        return sorted(effective), default

    if provider == "ollama":
        supported = _ollama_supported_reasoning_for_model(model)
        if supported is None:
            return ["none"], default
        effective = set(supported)
        if "low" in effective:
            effective.add("minimal")
        return sorted(effective), default

    if provider == "openai":
        supported = _openai_supported_reasoning_for_model(model)
        if supported is None:
            return sorted(PROVIDER_SUPPORTED_REASONING.get(provider, set())), default
        effective = set(supported)
        if "low" in effective:
            effective.add("minimal")
        return sorted(effective), default

    return sorted(PROVIDER_SUPPORTED_REASONING.get(provider, set())), default
