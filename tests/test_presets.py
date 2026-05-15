"""Tests for extraction presets and provider reasoning capabilities."""

import pytest

from finding_extractor.llm.model_settings import (
    EXTRACTION_PRESETS,
    PRESET_NAMES,
    ExtractionPreset,
    get_preset,
    model_reasoning_capabilities,
    validate_all_presets,
)


class TestPresetDefinitions:
    """Verify preset registry invariants."""

    def test_all_presets_pass_model_policy_validation(self):
        """Every preset model must pass validate_model_id."""
        validate_all_presets()

    def test_preset_names_match_dict_keys(self):
        """PRESET_NAMES tuple must mirror EXTRACTION_PRESETS keys."""
        assert set(PRESET_NAMES) == set(EXTRACTION_PRESETS.keys())

    def test_preset_name_field_matches_key(self):
        """Each preset's .name must equal its dict key."""
        for key, preset in EXTRACTION_PRESETS.items():
            assert preset.name == key

    def test_required_fields_present(self):
        """Every preset must have non-empty model, reasoning, and description."""
        for preset in EXTRACTION_PRESETS.values():
            assert preset.model
            assert preset.reasoning
            assert preset.description

    def test_presets_are_frozen(self):
        """Presets should be immutable (frozen dataclass)."""
        preset = EXTRACTION_PRESETS["fast"]
        with pytest.raises(AttributeError):
            preset.model = "openai:gpt-5"  # type: ignore[misc]


class TestPresetLookup:
    """Verify get_preset behavior."""

    def test_known_preset_returns_correct_object(self):
        preset = get_preset("fast")
        assert isinstance(preset, ExtractionPreset)
        assert preset.name == "fast"
        assert preset.model == "google-gla:gemini-3-flash-preview"
        assert preset.reasoning == "low"

    def test_case_insensitive_lookup(self):
        assert get_preset("BALANCED").name == "balanced"
        assert get_preset("Quality").name == "quality"

    def test_unknown_preset_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            get_preset("nonexistent")


class TestModelReasoningCapabilities:
    """Verify model-aware reasoning capability metadata helper."""

    def test_openai_model_supports_all_levels(self):
        supported, default = model_reasoning_capabilities("openai:gpt-5-mini")
        assert "none" in supported
        assert "medium" in supported
        assert "high" in supported
        assert default == "medium"
        assert supported == sorted(supported)

    def test_ollama_qwen3_instruct_supports_none_only(self):
        supported, default = model_reasoning_capabilities("ollama:qwen3:30b-instruct")
        assert supported == ["none"]
        assert default == "none"

    def test_ollama_qwen3_thinking_supports_all_levels(self):
        supported, default = model_reasoning_capabilities("ollama:qwen3:30b-thinking")
        assert set(supported) == {"none", "minimal", "low", "medium", "high"}
        assert default == "none"

    def test_unknown_provider_returns_empty(self):
        supported, default = model_reasoning_capabilities("unknown_provider:model")
        assert supported == []
        assert default == "none"

    def test_anthropic_supports_all_levels(self):
        supported, default = model_reasoning_capabilities("anthropic:claude-opus-4-6")
        assert set(supported) == {"none", "minimal", "low", "medium", "high"}
        assert default == "medium"

    def test_google_pro_support_is_model_specific(self):
        supported, default = model_reasoning_capabilities("google-gla:gemini-3.1-pro-preview")
        assert set(supported) == {"none", "low", "high"}
        assert default == "low"
