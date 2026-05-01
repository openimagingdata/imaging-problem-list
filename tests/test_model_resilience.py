"""Tests for model resilience helpers (fallback + request concurrency)."""

from pydantic import BaseModel
from pydantic_ai import NativeOutput
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel

from finding_extractor.core.config import clear_settings_cache
from finding_extractor.llm.resilience import (
    VLLM_PLACEHOLDER_API_KEY,
    PinnedModelSettingsModel,
    ProviderConcurrencyLimitedModel,
    build_resilient_model,
    clear_provider_limiters,
    get_provider_request_limiter,
    infer_runtime_model,
    provider_scope_key,
    resolve_output_type,
    should_fallback_on_exception,
)


def test_provider_scope_key_uses_provider_for_known_model_ids():
    assert provider_scope_key("openai:gpt-5-mini") == "openai"
    assert provider_scope_key("anthropic:claude-sonnet-4-5") == "anthropic"


def test_provider_scope_key_uses_prefix_for_unknown_models():
    assert provider_scope_key("custom-provider:model-a") == "custom-provider"
    assert provider_scope_key("custom-model") == "custom-model"


def test_get_provider_request_limiter_is_shared_per_provider_and_limit():
    clear_provider_limiters()
    limiter_a = get_provider_request_limiter("openai:gpt-5-mini", 4)
    limiter_b = get_provider_request_limiter("openai:gpt-5", 4)
    limiter_c = get_provider_request_limiter("openai:gpt-5-mini", 2)
    assert limiter_a is limiter_b
    assert limiter_a is not limiter_c


def test_should_fallback_on_exception_handles_provider_and_timeout_failures():
    provider_error = ModelHTTPError(status_code=429, model_name="openai:gpt-5-mini")
    assert should_fallback_on_exception(provider_error) is True
    assert should_fallback_on_exception(TimeoutError("timeout")) is True
    assert should_fallback_on_exception(UnexpectedModelBehavior("bad output")) is False


def test_build_resilient_model_without_fallback_keeps_agent_level_settings(monkeypatch):
    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: {"model": model, "reasoning": reasoning},
    )

    runtime = build_resilient_model("test", reasoning="low")

    assert runtime.model_settings == {"model": "test", "reasoning": "low"}
    assert runtime.model.model_name == "test"


def test_build_resilient_model_with_fallback_uses_pinned_settings_and_shared_limiter(
    monkeypatch,
):
    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: {"model": model, "reasoning": reasoning},
    )

    runtime = build_resilient_model(
        "test",
        reasoning="high",
        fallback_model_name="test",
        provider_request_max_concurrency=3,
    )

    assert runtime.model_settings is None
    assert isinstance(runtime.model, FallbackModel)

    primary = runtime.model.models[0]
    fallback = runtime.model.models[1]
    assert isinstance(primary, PinnedModelSettingsModel)
    assert isinstance(fallback, PinnedModelSettingsModel)
    assert primary._pinned_model_settings == {"model": "test", "reasoning": "high"}
    assert fallback._pinned_model_settings == {"model": "test", "reasoning": "high"}

    assert isinstance(primary.wrapped, ProviderConcurrencyLimitedModel)
    assert isinstance(fallback.wrapped, ProviderConcurrencyLimitedModel)
    assert primary.wrapped._limiter is fallback.wrapped._limiter


def test_build_resilient_model_carries_model_name(monkeypatch):
    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: None,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    runtime = build_resilient_model("ollama:gpt-oss:120b")
    assert runtime.model_name == "ollama:gpt-oss:120b"


def test_infer_runtime_model_builds_openai_compatible_vllm_model(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("VLLM_GEMMA4_31B_BASE_URL", "https://example.org/gemma/v1/chat/completions")
    model = infer_runtime_model("vllm:google/gemma-4-31B-it")
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "google/gemma-4-31B-it"


def test_infer_runtime_model_canonicalizes_vllm_served_model_name(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("VLLM_GEMMA4_31B_BASE_URL", "https://example.org/gemma/v1")
    model = infer_runtime_model("vllm:google/gemma-4-31b-it")
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "google/gemma-4-31B-it"


def test_infer_runtime_model_does_not_reuse_openai_api_key_for_vllm(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    monkeypatch.setenv("VLLM_GPT_OSS_120B_BASE_URL", "https://example.org/gpt-oss/v1")
    model = infer_runtime_model("vllm:openai/gpt-oss-120b")
    assert isinstance(model, OpenAIChatModel)
    assert model.client.api_key == VLLM_PLACEHOLDER_API_KEY


def test_infer_runtime_model_uses_vllm_api_key_when_configured(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("VLLM_API_KEY", "vllm-test-key")
    monkeypatch.setenv("VLLM_GPT_OSS_120B_BASE_URL", "https://example.org/gpt-oss/v1")
    model = infer_runtime_model("vllm:openai/gpt-oss-120b")
    assert isinstance(model, OpenAIChatModel)
    assert model.client.api_key == "vllm-test-key"


def test_build_resilient_model_wraps_vllm_model(monkeypatch):
    clear_provider_limiters()
    clear_settings_cache()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: None,
    )
    monkeypatch.setenv("VLLM_GPT_OSS_120B_BASE_URL", "https://example.org/gpt-oss/v1")
    runtime = build_resilient_model("vllm:openai/gpt-oss-120b")
    assert runtime.model_name == "vllm:openai/gpt-oss-120b"
    assert isinstance(runtime.model, OpenAIChatModel)


# ---------------------------------------------------------------------------
# resolve_output_type
# ---------------------------------------------------------------------------


class _DummyOutput(BaseModel):
    value: str


class TestResolveOutputType:
    """Wrap output_type in NativeOutput for models that need it."""

    def test_no_wrap_for_non_ollama(self):
        result = resolve_output_type(_DummyOutput, "openai:gpt-5.2")
        assert result is _DummyOutput

    def test_no_wrap_for_tool_capable_ollama(self):
        result = resolve_output_type(_DummyOutput, "ollama:gpt-oss:120b")
        assert result is _DummyOutput

    def test_wraps_for_native_needed_ollama(self):
        result = resolve_output_type(_DummyOutput, "ollama:medgemma:27b")
        assert isinstance(result, NativeOutput)

    def test_wraps_for_nemotron_cascade_2(self):
        result = resolve_output_type(_DummyOutput, "ollama:nemotron-cascade-2")
        assert isinstance(result, NativeOutput)

    def test_wraps_when_fallback_needs_native(self):
        result = resolve_output_type(
            _DummyOutput, "ollama:gpt-oss:120b", fallback_model_name="ollama:medgemma:27b"
        )
        assert isinstance(result, NativeOutput)

    def test_wraps_for_vllm(self):
        result = resolve_output_type(_DummyOutput, "vllm:google/gemma-4-31B-it")
        assert isinstance(result, NativeOutput)

    def test_no_wrap_when_both_tool_capable(self):
        result = resolve_output_type(
            _DummyOutput, "ollama:gpt-oss:120b", fallback_model_name="ollama:gpt-oss:20b"
        )
        assert result is _DummyOutput

    def test_no_wrap_when_fallback_is_none(self):
        result = resolve_output_type(_DummyOutput, "ollama:gpt-oss:120b", fallback_model_name=None)
        assert result is _DummyOutput


# ---------------------------------------------------------------------------
# Coding agent factories apply resolve_output_type
# ---------------------------------------------------------------------------


def test_coding_agents_use_resolve_output_type_for_native_ollama(monkeypatch):
    """Coding agent factories wrap output_type for Ollama models needing native output."""
    from finding_extractor.coding.agents import (
        create_finding_selector_agent,
        create_finding_term_agent,
        create_location_selector_agent,
        create_location_term_agent,
    )

    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: None,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    runtime = build_resilient_model("ollama:medgemma:27b")

    # Each factory should produce an agent whose output schema uses NativeOutput
    for factory in [
        lambda r: create_finding_term_agent(r),
        lambda r: create_location_term_agent(r),
        lambda r: create_finding_selector_agent(r),
        lambda r: create_location_selector_agent(r),
    ]:
        agent = factory(runtime)
        # The agent's output schema should be native mode, not tool mode
        assert agent._output_schema.mode == "native", (
            f"Expected native output mode for {agent.name} with Ollama medgemma"
        )


def test_coding_agents_preserve_tool_mode_for_tool_capable_ollama(monkeypatch):
    """Coding agent factories keep tool mode for tool-capable Ollama models."""
    from finding_extractor.coding.agents import create_finding_term_agent

    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: None,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    runtime = build_resilient_model("ollama:gpt-oss:120b")
    agent = create_finding_term_agent(runtime)
    assert agent._output_schema.mode != "native"


def test_coding_agents_wrap_native_when_fallback_needs_it(monkeypatch):
    """Coding agents use native output when the fallback model needs it."""
    from finding_extractor.coding.agents import create_finding_term_agent

    clear_provider_limiters()
    monkeypatch.setattr(
        "finding_extractor.llm.resilience.get_model_settings",
        lambda model, reasoning=None: None,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    runtime = build_resilient_model(
        "ollama:gpt-oss:120b", fallback_model_name="ollama:medgemma:27b"
    )
    assert runtime.fallback_model_name == "ollama:medgemma:27b"
    agent = create_finding_term_agent(runtime)
    assert agent._output_schema.mode == "native"
