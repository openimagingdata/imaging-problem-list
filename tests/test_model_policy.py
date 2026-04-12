"""Tests for runtime model-id validation policy and local-only mode."""

import pytest

from finding_extractor.core.config import ExtractorSettings, clear_settings_cache
from finding_extractor.llm.model_settings import ollama_needs_native_output
from finding_extractor.llm.policy import validate_model_id


def test_validate_model_id_accepts_openai():
    validate_model_id("openai:gpt-5-mini")


def test_validate_model_id_accepts_ollama():
    validate_model_id("ollama:llama3.3")


def test_validate_model_id_accepts_anthropic_45():
    validate_model_id("anthropic:claude-sonnet-4-5")


def test_validate_model_id_accepts_gemini3_gla():
    validate_model_id("google-gla:gemini-3.1-pro-preview")


def test_validate_model_id_rejects_google_vertex():
    with pytest.raises(ValueError, match="google-vertex models are not allowed"):
        validate_model_id("google-vertex:gemini-3-pro")


def test_validate_model_id_rejects_old_anthropic():
    with pytest.raises(ValueError, match="anthropic model must be version 4.5 or 4.6"):
        validate_model_id("anthropic:claude-sonnet-4-0")


def test_validate_model_id_rejects_old_gemini():
    with pytest.raises(ValueError, match="google model must be gemini-3\\* pro/flash"):
        validate_model_id("google-gla:gemini-2.5-pro")


def test_validate_model_id_accepts_openrouter():
    validate_model_id("openrouter:anthropic/claude-sonnet-4-5")


def test_validate_model_id_accepts_openrouter_openai_model():
    validate_model_id("openrouter:openai/gpt-5")


def test_validate_model_id_rejects_bad_format():
    with pytest.raises(ValueError, match="model must use"):
        validate_model_id("gpt-5-mini")


# ---------------------------------------------------------------------------
# ollama_needs_native_output
# ---------------------------------------------------------------------------


class TestOllamaNeedsNativeOutput:
    """Detect which Ollama families need NativeOutput mode."""

    def test_non_ollama_models_never_need_native(self):
        assert ollama_needs_native_output("openai:gpt-5.2") is False
        assert ollama_needs_native_output("anthropic:claude-opus-4-6") is False
        assert ollama_needs_native_output("google-gla:gemini-3-flash-preview") is False

    def test_gpt_oss_uses_tools(self):
        assert ollama_needs_native_output("ollama:gpt-oss:120b") is False
        assert ollama_needs_native_output("ollama:gpt-oss:20b") is False

    def test_llama_uses_tools(self):
        assert ollama_needs_native_output("ollama:llama3.3:latest") is False
        assert ollama_needs_native_output("ollama:llama4:latest") is False

    def test_qwen_uses_tools(self):
        assert ollama_needs_native_output("ollama:qwen3:30b-instruct") is False
        assert ollama_needs_native_output("ollama:qwen3.5:27b") is False
        assert ollama_needs_native_output("ollama:qwen3.5:35b-a3b-mlx-bf16") is False

    def test_nemotron_uses_tools(self):
        assert ollama_needs_native_output("ollama:nemotron-3-super:120b") is False

    def test_nemotron_cascade_2_needs_native(self):
        assert ollama_needs_native_output("ollama:nemotron-cascade-2") is True

    def test_gemma4_needs_native(self):
        assert ollama_needs_native_output("ollama:gemma4:26b") is True
        assert ollama_needs_native_output("ollama:gemma4:31b") is True

    def test_gemma3_needs_native(self):
        assert ollama_needs_native_output("ollama:gemma3:27b") is True

    def test_deepseek_needs_native(self):
        assert ollama_needs_native_output("ollama:deepseek-r1:70b") is True
        assert ollama_needs_native_output("ollama:deepseek-r1:32b") is True

    def test_medgemma_needs_native(self):
        assert ollama_needs_native_output("ollama:MedAIBase/MedGemma1.0:27b") is True
        assert ollama_needs_native_output("ollama:alibayram/medgemma:27b") is True

    def test_custom_modelfile_names_need_native(self):
        assert ollama_needs_native_output("ollama:gemma4-radextract") is True

    def test_unknown_ollama_family_conservative_default(self):
        assert ollama_needs_native_output("ollama:some-unknown-model:7b") is True


# ---------------------------------------------------------------------------
# Local-only mode tests
# ---------------------------------------------------------------------------


class TestLocalOnlyMode:
    """Tests for the local_only_mode settings enforcement."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_settings_cache()
        yield
        clear_settings_cache()

    def _make_settings(self, **overrides) -> ExtractorSettings:
        """Build settings with local-only defaults, applying overrides."""
        defaults = {
            "local_only_mode": True,
            "default_model": "ollama:qwen3.5:35b-a3b",
            "fallback_model": None,
            "reviewer_model": None,
            "coding_model": "ollama:qwen3.5:35b-a3b",
            "coding_term_model": None,
            "coding_fallback_model": None,
            "ollama_base_url": "http://localhost:11434/v1",
        }
        defaults.update(overrides)
        return ExtractorSettings(**defaults)

    def test_accepts_all_ollama_models(self):
        settings = self._make_settings()
        assert settings.local_only_mode is True

    def test_clears_cloud_fallback_model(self):
        settings = self._make_settings(fallback_model="openai:gpt-5.2")
        assert settings.fallback_model is None

    def test_keeps_ollama_fallback_model(self):
        settings = self._make_settings(fallback_model="ollama:qwen3.5:9b")
        assert settings.fallback_model == "ollama:qwen3.5:9b"

    def test_disables_cloud_reviewer(self):
        settings = self._make_settings(
            reviewer_enabled=True,
            reviewer_model="anthropic:claude-opus-4-6",
        )
        assert settings.reviewer_enabled is False
        assert settings.reviewer_model is None

    def test_keeps_ollama_reviewer(self):
        settings = self._make_settings(
            reviewer_enabled=True,
            reviewer_model="ollama:qwen3.5:27b",
        )
        assert settings.reviewer_enabled is True
        assert settings.reviewer_model == "ollama:qwen3.5:27b"

    def test_forces_logfire_disabled(self):
        settings = self._make_settings(logfire_enabled=True)
        assert settings.logfire_enabled is False

    def test_clears_logfire_token(self):
        settings = self._make_settings(logfire_token="pylf_v1_test_token")
        assert settings.logfire_token is None

    def test_does_not_enforce_when_disabled(self):
        """When local_only_mode is False, cloud models are allowed."""
        settings = ExtractorSettings(
            local_only_mode=False,
            default_model="openai:gpt-5.2",
        )
        assert settings.local_only_mode is False
