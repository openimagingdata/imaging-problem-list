"""Tests for finding extractor agent and extraction logic."""

from typing import Any, cast

import pytest

from finding_extractor.extractor.agent import (
    ExtractorDeps,
    _emit_progress,
    build_prompt,
    check_verbatim,
    create_agent,
    validate_extraction,
)
from finding_extractor.llm.model_settings import (
    VALID_REASONING_LEVELS,
    _anthropic_uses_adaptive_thinking,
    get_model_settings,
    resolve_runtime_reasoning,
    validate_reasoning,
    validate_reasoning_for_model,
)
from finding_extractor.llm.policy import provider_from_model_id
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    ExtractionResult,
    ExtractionUsage,
    Finding,
    FindingLocation,
    NonFindingText,
)


class TestProviderFromModelId:
    """Test cases for canonical provider detection from model strings."""

    def test_openai_prefix(self):
        assert provider_from_model_id("openai:gpt-5-mini") == "openai"

    def test_openai_chat_prefix(self):
        assert provider_from_model_id("openai-chat:gpt-5-mini") == "openai"

    def test_openai_responses_prefix(self):
        assert provider_from_model_id("openai-responses:gpt-5") == "openai"

    def test_anthropic_prefix(self):
        assert provider_from_model_id("anthropic:claude-sonnet-4-5") == "anthropic"

    def test_google_gla_prefix(self):
        assert provider_from_model_id("google-gla:gemini-3-flash-preview") == "google"

    def test_google_vertex_prefix_not_supported(self):
        assert provider_from_model_id("google-vertex:gemini-3-pro-preview") is None

    def test_ollama_prefix(self):
        assert provider_from_model_id("ollama:llama4") == "ollama"

    def test_openrouter_prefix(self):
        assert provider_from_model_id("openrouter:anthropic/claude-sonnet-4-5") == "openrouter"

    def test_bare_model_name(self):
        assert provider_from_model_id("gpt-5-mini") is None

    def test_unknown_prefix(self):
        assert provider_from_model_id("unknown:some-model") is None


class TestModelSettings:
    """Test cases for model settings configuration."""

    def test_default_model_settings(self):
        """Test that OpenAI model settings are created with explicit reasoning."""
        settings = get_model_settings("openai:gpt-5-mini", reasoning="medium")
        assert settings is not None

    def test_no_reasoning_returns_none(self):
        """Test that None reasoning returns None settings."""
        settings = get_model_settings("openai:gpt-5-mini")
        assert settings is None

    def test_reasoning_effort_override(self):
        """Test that reasoning effort can be overridden."""
        settings = get_model_settings("openai:gpt-5-mini", reasoning="high")
        assert settings is not None


class TestMultiProviderSettings:
    """Test cases for multi-provider model settings."""

    def test_openai_settings_with_reasoning(self):
        """Test OpenAI settings include reasoning effort."""
        settings = get_model_settings("openai:gpt-5-mini", reasoning="medium")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openai_reasoning_effort"] == "medium"

    def test_anthropic_settings_high(self):
        """Test Anthropic settings with high reasoning enable thinking."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["type"] == "enabled"
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 10240
        assert provider_settings["max_tokens"] == 16384

    def test_anthropic_settings_none(self):
        """Test Anthropic settings with none disables thinking."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["type"] == "disabled"

    def test_google_settings_medium(self):
        """Test Google settings with medium reasoning set thinking level."""
        settings = get_model_settings("google-gla:gemini-3-flash-preview", reasoning="medium")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "MEDIUM"

    def test_google_settings_none(self):
        """Gemini 3 Flash maps 'none' to MINIMAL thinking."""
        settings = get_model_settings("google-gla:gemini-3-flash-preview", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "MINIMAL"

    def test_google_explicit_reasoning_low(self):
        """Google with explicit low reasoning resolves to LOW."""
        settings = get_model_settings("google-gla:gemini-3-flash-preview", reasoning="low")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "LOW"

    def test_ollama_ignores_reasoning(self):
        """Test Ollama returns None (no thinking support)."""
        settings = get_model_settings("ollama:llama4", reasoning="none")
        assert settings is None

    def test_unknown_provider_returns_none(self):
        """Test unknown provider returns None."""
        settings = get_model_settings("unknown:some-model", reasoning="medium")
        assert settings is None

    def test_explicit_reasoning_openai(self):
        """Test explicit medium reasoning for OpenAI produces settings."""
        settings = get_model_settings("openai:gpt-5-mini", reasoning="medium")
        assert settings is not None

    def test_explicit_reasoning_anthropic(self):
        """Test explicit medium reasoning for Anthropic produces settings."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="medium")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["type"] == "enabled"
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 4096

    def test_none_reasoning_ollama(self):
        """Test none reasoning for Ollama returns None."""
        settings = get_model_settings("ollama:llama4", reasoning="none")
        assert settings is None

    def test_openrouter_settings_high(self):
        """Test OpenRouter settings with high reasoning."""
        settings = get_model_settings("openrouter:anthropic/claude-sonnet-4-5", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openrouter_reasoning"]["effort"] == "high"

    def test_openrouter_settings_minimal_maps_to_low(self):
        """Test OpenRouter maps 'minimal' reasoning to 'low' effort."""
        settings = get_model_settings("openrouter:openai/gpt-5", reasoning="minimal")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openrouter_reasoning"]["effort"] == "low"

    def test_openrouter_settings_none(self):
        """Test OpenRouter settings with none disables reasoning."""
        settings = get_model_settings("openrouter:meta-llama/llama-2-70b-chat", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openrouter_reasoning"]["enabled"] is False

    def test_openrouter_explicit_medium_reasoning(self):
        """Test explicit medium reasoning for OpenRouter produces settings."""
        settings = get_model_settings("openrouter:anthropic/claude-sonnet-4-5", reasoning="medium")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openrouter_reasoning"]["effort"] == "medium"

    def test_anthropic_budget_minimal(self):
        """Test Anthropic minimal reasoning budget."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="minimal")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 1024
        assert provider_settings["max_tokens"] == 8192

    def test_anthropic_budget_low(self):
        """Test Anthropic low reasoning budget."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="low")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 1024

    def test_anthropic_budget_medium(self):
        """Test Anthropic medium reasoning budget."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="medium")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 4096

    def test_anthropic_budget_high(self):
        """Test Anthropic high reasoning budget."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["anthropic_thinking"]["budget_tokens"] == 10240
        assert provider_settings["max_tokens"] == 16384

    # -- Anthropic adaptive thinking (4.6+ models) --

    def test_anthropic_opus_46_adaptive_high(self):
        """Opus 4.6 uses adaptive thinking with effort level."""
        settings = get_model_settings("anthropic:claude-opus-4-6", reasoning="high")
        assert settings is not None
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "adaptive"
        assert s["anthropic_effort"] == "high"
        assert "budget_tokens" not in s["anthropic_thinking"]

    def test_anthropic_opus_46_adaptive_medium(self):
        settings = get_model_settings("anthropic:claude-opus-4-6", reasoning="medium")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "adaptive"
        assert s["anthropic_effort"] == "medium"

    def test_anthropic_opus_46_adaptive_low(self):
        settings = get_model_settings("anthropic:claude-opus-4-6", reasoning="low")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "adaptive"
        assert s["anthropic_effort"] == "low"

    def test_anthropic_opus_46_adaptive_minimal(self):
        """Minimal maps to 'low' effort on adaptive models."""
        settings = get_model_settings("anthropic:claude-opus-4-6", reasoning="minimal")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "adaptive"
        assert s["anthropic_effort"] == "low"

    def test_anthropic_opus_46_none_disables(self):
        """'none' still disables thinking on adaptive models."""
        settings = get_model_settings("anthropic:claude-opus-4-6", reasoning="none")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "disabled"
        assert "anthropic_effort" not in s

    def test_anthropic_sonnet_46_uses_adaptive(self):
        """Future Sonnet 4.6 should also use adaptive thinking."""
        settings = get_model_settings("anthropic:claude-sonnet-4-6", reasoning="high")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "adaptive"
        assert s["anthropic_effort"] == "high"

    def test_anthropic_sonnet_45_still_uses_budget(self):
        """Pre-4.6 models keep budget-based extended thinking."""
        settings = get_model_settings("anthropic:claude-sonnet-4-5", reasoning="high")
        s = cast(dict[str, Any], settings)
        assert s["anthropic_thinking"]["type"] == "enabled"
        assert s["anthropic_thinking"]["budget_tokens"] == 10240

    def test_google_thinking_minimal(self):
        """Gemini 3 Pro rejects minimal thinking level."""
        with pytest.raises(ValueError, match="not supported by google-gla:gemini-3.1-pro-preview"):
            get_model_settings("google-gla:gemini-3.1-pro-preview", reasoning="minimal")

    def test_google_thinking_low(self):
        """Test Google low thinking level."""
        settings = get_model_settings("google-gla:gemini-3.1-pro-preview", reasoning="low")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "LOW"

    def test_google_thinking_high(self):
        """Test Google high thinking level."""
        settings = get_model_settings("google-gla:gemini-3.1-pro-preview", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "HIGH"

    def test_google_pro_none_maps_to_low(self):
        """Gemini 3 Pro maps 'none' to LOW as nearest supported level."""
        settings = get_model_settings("google-gla:gemini-3.1-pro-preview", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["google_thinking_config"]["thinking_level"] == "LOW"

    def test_ollama_qwen3_30b_thinking_settings_high(self):
        """Qwen3 30b thinking models map non-none reasoning to think=true."""
        settings = get_model_settings("ollama:qwen3:30b-thinking", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["extra_body"]["think"] is True

    def test_ollama_qwen3_30b_thinking_settings_none(self):
        """Qwen3 30b thinking models map reasoning=none to think=false."""
        settings = get_model_settings("ollama:qwen3:30b-thinking", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["extra_body"]["think"] is False

    def test_ollama_qwen3_30b_instruct_settings_none(self):
        """Qwen3 30b instruct does not require extra model settings."""
        settings = get_model_settings("ollama:qwen3:30b-instruct", reasoning="none")
        assert settings is None

    def test_ollama_gpt_oss_120b_settings_high(self):
        """GPT-OSS 120b maps reasoning tiers to think level strings."""
        settings = get_model_settings("ollama:gpt-oss:120b", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["extra_body"]["think"] == "high"

    def test_ollama_gpt_oss_120b_settings_minimal_maps_low(self):
        """GPT-OSS 120b normalizes minimal to low."""
        settings = get_model_settings("ollama:gpt-oss:120b", reasoning="minimal")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["extra_body"]["think"] == "low"

    def test_ollama_nemotron_cascade_2_settings_none(self):
        """nemotron-cascade-2 uses reasoning_effort on Ollama's OpenAI API."""
        settings = get_model_settings("ollama:nemotron-cascade-2", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openai_reasoning_effort"] == "none"

    def test_ollama_nemotron_cascade_2_settings_high(self):
        """nemotron-cascade-2 accepts tiered reasoning levels."""
        settings = get_model_settings("ollama:nemotron-cascade-2", reasoning="high")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openai_reasoning_effort"] == "high"

    def test_ollama_nemotron_cascade_2_settings_minimal_maps_low(self):
        """nemotron-cascade-2 normalizes minimal to low."""
        settings = get_model_settings("ollama:nemotron-cascade-2", reasoning="minimal")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openai_reasoning_effort"] == "low"


class TestAnthropicAdaptiveDetection:
    """Unit tests for _anthropic_uses_adaptive_thinking helper."""

    def test_opus_46_is_adaptive(self):
        assert _anthropic_uses_adaptive_thinking("anthropic:claude-opus-4-6") is True

    def test_sonnet_45_is_not_adaptive(self):
        assert _anthropic_uses_adaptive_thinking("anthropic:claude-sonnet-4-5") is False

    def test_sonnet_46_is_adaptive(self):
        assert _anthropic_uses_adaptive_thinking("anthropic:claude-sonnet-4-6") is True

    def test_unknown_model_is_not_adaptive(self):
        assert _anthropic_uses_adaptive_thinking("anthropic:unknown-model") is False

    def test_bare_model_name(self):
        assert _anthropic_uses_adaptive_thinking("claude-opus-4-6") is True


class TestBuildPrompt:
    """Test cases for prompt building."""

    def test_prompt_without_study_description(self):
        """Test building prompt without exam description."""
        report = "This is a test report."
        prompt = build_prompt(report)
        assert "RADIOLOGY REPORT:" in prompt
        assert report in prompt
        assert "Exam Description:" not in prompt

    def test_prompt_with_study_description(self):
        """Test building prompt with exam description."""
        report = "This is a test report."
        exam_desc = "CT Abdomen"
        prompt = build_prompt(report, exam_desc)
        assert "Exam Description: CT Abdomen" in prompt
        assert report in prompt

    def test_structured_report_includes_section_hint(self):
        """Structured report with sections gets a REPORT STRUCTURE hint."""
        report = "Findings:\nNormal.\n\nImpression:\nNo acute finding."
        prompt = build_prompt(report)
        assert "REPORT STRUCTURE" in prompt
        assert "FINDINGS" in prompt
        assert "IMPRESSION" in prompt

    def test_unstructured_report_no_section_hint(self):
        """Unstructured report without recognizable headers gets no hint."""
        report = "The heart is normal. No effusion."
        prompt = build_prompt(report)
        assert "REPORT STRUCTURE" not in prompt


class TestValidateExtraction:
    """Test cases for post-extraction validation (coverage analysis only).

    Verbatim quote checking is handled by the agent's output validator
    (which retries the model on failure via ModelRetry), so validate_extraction()
    only performs coverage analysis.
    """

    def test_valid_extraction_is_always_valid(self):
        """validate_extraction reports no verbatim errors (verbatim is agent-enforced)."""
        report_text = "The patient has pneumonia in the right lung."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    location=FindingLocation(
                        body_region="chest",
                        specific_anatomy="right lung",
                        laterality="right",
                    ),
                    report_text="The patient has pneumonia in the right lung.",
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        assert result.verbatim_errors == []

    def test_no_verbatim_errors_even_with_paraphrased_quote(self):
        """validate_extraction does not re-check verbatim quotes (agent handles that)."""
        report_text = "The patient has pneumonia in the right lung."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Patient has pneumonia in right lung.",  # Paraphrased
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        assert result.verbatim_errors == []

    def test_coverage_warning(self):
        """Test that coverage warnings are generated for unaccounted text."""
        report_text = "Line one.\nLine two.\nLine three."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Test"),
            findings=[
                Finding(
                    finding_name="test",
                    presence="present",
                    report_text="Line one.",
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        assert len(result.coverage_warnings) > 0


class TestOutputValidator:
    """Test cases for the check_verbatim helper used by the output validator."""

    def test_validator_accepts_verbatim_quotes(self):
        """Test that verbatim quotes pass validation."""
        report = "The patient has pneumonia in the right lung. No pleural effusion."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    location=FindingLocation(
                        body_region="chest",
                        specific_anatomy="right lung",
                        laterality="right",
                    ),
                    report_text="The patient has pneumonia in the right lung.",
                ),
            ],
            non_finding_text=[],
        )
        errors = check_verbatim(report, extraction)
        assert errors == []

    def test_validator_rejects_paraphrased_quotes(self):
        """Test that paraphrased quotes are rejected."""
        report = "The patient has pneumonia in the right lung."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Patient has pneumonia in right lung.",  # paraphrased
                ),
            ],
        )
        errors = check_verbatim(report, extraction)
        assert len(errors) == 1
        assert "pneumonia" in errors[0]

    def test_validator_rejects_paraphrased_non_finding(self):
        """Test that paraphrased non-finding text is rejected."""
        report = "Technique: CT of the abdomen and pelvis without contrast."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT"),
            non_finding_text=[
                NonFindingText(
                    text="Technique: CT abdomen pelvis without contrast.",  # paraphrased
                    category="technique",
                ),
            ],
        )
        errors = check_verbatim(report, extraction)
        assert len(errors) == 1
        assert "technique" in errors[0]

    def test_validator_reports_multiple_errors(self):
        """Test that multiple errors are collected."""
        report = "The lungs are clear. No effusion."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="clear lungs",
                    presence="absent",
                    report_text="Lungs are clear.",  # minor case/article difference — accepted
                ),
                Finding(
                    finding_name="pleural effusion",
                    presence="absent",
                    report_text="No pleural effusion.",  # "pleural" not in source — rejected
                ),
                Finding(
                    finding_name="pneumothorax",
                    presence="absent",
                    report_text="No pneumothorax seen.",  # "pneumothorax" not in source — rejected
                ),
            ],
        )
        errors = check_verbatim(report, extraction)
        assert len(errors) == 2

    def test_validator_accepts_whitespace_equivalent_quotes(self):
        """Whitespace-only formatting differences should still count as verbatim."""
        report = "Findings: Mild bibasilar atelectasis."
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="atelectasis",
                    presence="present",
                    report_text="Findings:\n  Mild   bibasilar   atelectasis.",
                ),
            ],
        )
        errors = check_verbatim(report, extraction)
        assert errors == []

class TestCreateAgent:
    """Test create_agent wiring for resilient model composition."""

    def test_create_agent_passes_resilient_model_runtime(self, monkeypatch):
        """create_agent should delegate model wiring to shared resilient agent helper."""
        captured: dict[str, Any] = {}

        class FakeAgent:
            def output_validator(self, fn):
                return fn

        def fake_create_resilient_agent(**kwargs):
            captured["kwargs"] = kwargs
            return FakeAgent()

        monkeypatch.setattr(
            "finding_extractor.extractor.agent.create_resilient_agent",
            fake_create_resilient_agent,
        )

        create_agent(reasoning="low")

        assert captured["kwargs"]["model_name"] == "google-gla:gemini-3-flash-preview"
        assert captured["kwargs"]["reasoning"] == "low"
        assert captured["kwargs"]["output_type"] is ExtractedReportFindings
        assert captured["kwargs"]["deps_type"] is ExtractorDeps
        assert captured["kwargs"]["output_retries"] == 3

    def test_create_agent_skips_model_settings_when_runtime_uses_pinned_fallback(self, monkeypatch):
        """create_agent should respect explicit model override when creating resilient agent."""
        captured: dict[str, Any] = {}

        class FakeAgent:
            def output_validator(self, fn):
                return fn

        def fake_create_resilient_agent(**kwargs):
            captured["kwargs"] = kwargs
            return FakeAgent()

        monkeypatch.setattr(
            "finding_extractor.extractor.agent.create_resilient_agent", fake_create_resilient_agent
        )

        create_agent("openai:gpt-5-mini")

        assert captured["kwargs"]["model_name"] == "openai:gpt-5-mini"


class TestReasoningValidation:
    """Test cases for reasoning level validation."""

    def test_validate_reasoning_valid_values(self):
        """All valid reasoning levels should be accepted without error."""
        for level in VALID_REASONING_LEVELS:
            validate_reasoning(level)  # should not raise

    def test_validate_reasoning_invalid_value(self):
        """Invalid reasoning values should raise ValueError."""
        for bad in ("turbo", "", "MEDIUM", "auto"):
            with pytest.raises(ValueError, match="Invalid reasoning level"):
                validate_reasoning(bad)

    def test_validate_reasoning_for_model_ollama_rejects_high(self):
        """Ollama models only support reasoning='none'."""
        with pytest.raises(ValueError, match="not supported by ollama"):
            validate_reasoning_for_model("ollama:llama4", "high")

    def test_validate_reasoning_for_model_ollama_rejects_medium(self):
        """Ollama models only support reasoning='none'."""
        with pytest.raises(ValueError, match="not supported by ollama"):
            validate_reasoning_for_model("ollama:llama4", "medium")

    def test_validate_reasoning_for_model_ollama_accepts_none(self):
        """Ollama models accept reasoning='none'."""
        validate_reasoning_for_model("ollama:llama4", "none")  # should not raise

    def test_validate_reasoning_for_model_ollama_qwen_thinking_accepts_high(self):
        """Qwen3 30b thinking accepts high reasoning."""
        validate_reasoning_for_model("ollama:qwen3:30b-thinking", "high")

    def test_validate_reasoning_for_model_ollama_qwen_instruct_rejects_high(self):
        """Qwen3 30b instruct rejects non-none reasoning."""
        with pytest.raises(ValueError, match="not supported by ollama:qwen3:30b-instruct"):
            validate_reasoning_for_model("ollama:qwen3:30b-instruct", "high")

    def test_validate_reasoning_for_model_ollama_nemotron_cascade_2_accepts_high(self):
        """nemotron-cascade-2 accepts tiered reasoning."""
        validate_reasoning_for_model("ollama:nemotron-cascade-2", "high")

    def test_validate_reasoning_for_model_openai_accepts_all(self):
        """OpenAI models accept all reasoning levels."""
        for level in VALID_REASONING_LEVELS:
            validate_reasoning_for_model("openai:gpt-5-mini", level)

    def test_validate_reasoning_for_model_anthropic_accepts_all(self):
        """Anthropic models accept all reasoning levels."""
        for level in VALID_REASONING_LEVELS:
            validate_reasoning_for_model("anthropic:claude-sonnet-4-5", level)

    def test_validate_reasoning_for_model_google_accepts_all(self):
        """Gemini 3 Flash accepts all user-facing reasoning levels."""
        for level in VALID_REASONING_LEVELS:
            validate_reasoning_for_model("google-gla:gemini-3-flash-preview", level)

    def test_validate_reasoning_for_model_google_pro_rejects_minimal(self):
        """Gemini 3 Pro does not support minimal thinking."""
        with pytest.raises(ValueError, match="supported levels: high, low"):
            validate_reasoning_for_model("google-gla:gemini-3.1-pro-preview", "minimal")

    def test_validate_reasoning_for_model_openrouter_accepts_all(self):
        """OpenRouter models accept all reasoning levels (including minimal)."""
        for level in VALID_REASONING_LEVELS:
            validate_reasoning_for_model("openrouter:anthropic/claude-sonnet-4-5", level)

    def test_validate_reasoning_for_model_unknown_provider_passes(self):
        """Unknown providers are not validated (deferred to runtime)."""
        validate_reasoning_for_model("unknown:model", "high")  # should not raise


class TestOpenAINoneSettings:
    """Verify reasoning='none' returns explicit settings for OpenAI."""

    def test_openai_none_returns_explicit_settings(self):
        """OpenAI with reasoning='none' should return settings, not None."""
        settings = get_model_settings("openai:gpt-5-mini", reasoning="none")
        assert settings is not None
        provider_settings = cast(dict[str, Any], settings)
        assert provider_settings["openai_reasoning_effort"] == "none"


class TestExtractionResult:
    """Test ExtractionResult and ExtractionUsage data classes."""

    def test_extraction_result_fields(self):
        """ExtractionResult bundles extraction and usage."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Test"),
        )
        usage = ExtractionUsage(
            requests=1,
            input_tokens=100,
            output_tokens=50,
            duration_ms=1234,
        )
        result = ExtractionResult(report_findings=extraction, usage=usage)
        assert result.report_findings is extraction
        assert result.usage is usage
        assert result.usage.duration_ms == 1234

    def test_extraction_result_none_usage(self):
        """ExtractionResult with no usage is valid."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Test"),
        )
        result = ExtractionResult(report_findings=extraction, usage=None)
        assert result.usage is None

    def test_extraction_usage_defaults(self):
        """ExtractionUsage defaults to zero for all fields."""
        usage = ExtractionUsage()
        assert usage.requests == 0
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_read_tokens == 0
        assert usage.cache_write_tokens == 0
        assert usage.duration_ms is None
        assert usage.details == {}


class TestResolveEffectiveReasoning:
    """Test cases for reasoning resolution and validation (via resolve_runtime_reasoning)."""

    def test_explicit_reasoning_overrides_default(self, monkeypatch):
        """Explicit reasoning should take precedence over env default."""
        monkeypatch.setenv("IPL_REASONING", "low")
        level = resolve_runtime_reasoning("openai:gpt-5-mini", "high")
        assert level == "high"

    def test_env_default_used_when_no_explicit(self, monkeypatch):
        """When no explicit reasoning, env default should be used."""
        monkeypatch.setenv("IPL_REASONING", "low")
        level = resolve_runtime_reasoning("openai:gpt-5-mini")
        assert level == "low"

    def test_provider_default_used_when_no_env(self):
        """When no explicit or env default, provider default is used."""
        level = resolve_runtime_reasoning("openai:gpt-5-mini")
        assert level == "medium"

    def test_google_provider_default_is_low(self):
        """Gemini provider default resolves to low when no override is supplied."""
        level = resolve_runtime_reasoning("google-gla:gemini-3-flash-preview")
        assert level == "low"

    def test_ollama_default_is_none(self):
        """Ollama provider default reasoning is 'none'."""
        level = resolve_runtime_reasoning("ollama:llama4")
        assert level == "none"

    def test_ollama_with_incompatible_env_default_raises(self, monkeypatch):
        """Ollama + env default 'high' should fail fast."""
        monkeypatch.setenv("IPL_REASONING", "high")
        with pytest.raises(ValueError, match="not supported by ollama"):
            resolve_runtime_reasoning("ollama:llama4")

    def test_ollama_with_incompatible_explicit_raises(self):
        """Ollama + explicit 'medium' should fail fast."""
        with pytest.raises(ValueError, match="not supported by ollama"):
            resolve_runtime_reasoning("ollama:llama4", "medium")

    def test_ollama_qwen3_30b_thinking_accepts_explicit_high(self):
        """Ollama Qwen thinking models should accept high reasoning at preflight."""
        level = resolve_runtime_reasoning("ollama:qwen3:30b-thinking", "high")
        assert level == "high"

    def test_ollama_nemotron_cascade_2_accepts_explicit_medium(self):
        """nemotron-cascade-2 should accept explicit reasoning tiers at preflight."""
        level = resolve_runtime_reasoning("ollama:nemotron-cascade-2", "medium")
        assert level == "medium"

    def test_unknown_provider_returns_none_without_defaults(self):
        """Unknown provider with no reasoning returns None."""
        level = resolve_runtime_reasoning(
            "unknown:model", allow_unknown_model_reasoning=True
        )
        assert level is None

    def test_unknown_provider_with_explicit_reasoning(self):
        """Unknown provider with explicit reasoning validates and returns it."""
        level = resolve_runtime_reasoning(
            "unknown:model", "high", allow_unknown_model_reasoning=True
        )
        assert level == "high"


class TestResolveRuntimeReasoning:
    """Test cases for runtime-compatible reasoning resolution."""

    def test_openai_gpt52_minimal_normalizes_to_low(self):
        level = resolve_runtime_reasoning("openai:gpt-5.2", "minimal")
        assert level == "low"

    def test_google_none_normalizes_to_minimal_for_flash(self):
        level = resolve_runtime_reasoning("google-gla:gemini-3-flash-preview", "none")
        assert level == "minimal"

    def test_unknown_openai_family_fails_fast_by_default(self):
        with pytest.raises(ValueError, match="Cannot verify reasoning compatibility"):
            resolve_runtime_reasoning("openai:gpt-6", "minimal")

    def test_unknown_openai_family_allows_override(self):
        level = resolve_runtime_reasoning(
            "openai:gpt-6",
            "minimal",
            allow_unknown_model_reasoning=True,
        )
        assert level == "minimal"

    def test_ollama_gpt_oss_minimal_normalizes_to_low(self):
        level = resolve_runtime_reasoning("ollama:gpt-oss:120b", "minimal")
        assert level == "low"

    def test_ollama_nemotron_cascade_2_minimal_normalizes_to_low(self):
        level = resolve_runtime_reasoning("ollama:nemotron-cascade-2", "minimal")
        assert level == "low"

    def test_ollama_unknown_family_fails_fast_by_default(self):
        with pytest.raises(ValueError, match="Cannot verify reasoning compatibility"):
            resolve_runtime_reasoning("ollama:mistral-small3.2", "low")

    def test_ollama_unknown_family_allows_override(self):
        level = resolve_runtime_reasoning(
            "ollama:mistral-small3.2",
            "low",
            allow_unknown_model_reasoning=True,
        )
        assert level == "low"


class TestEmitStatus:
    """Test cases for the _emit_progress helper."""

    @pytest.mark.asyncio
    async def test_emit_progress_noop_when_no_callback(self):
        """_emit_progress with progress_callback=None should not raise."""
        deps = ExtractorDeps(report_text="test")
        await _emit_progress(deps, "some message")  # should not raise

    @pytest.mark.asyncio
    async def test_emit_progress_calls_callback(self):
        """_emit_progress should invoke the callback with the message."""
        messages: list[str] = []

        async def capture(msg: str) -> None:
            messages.append(msg)

        deps = ExtractorDeps(report_text="test", progress_callback=capture)
        await _emit_progress(deps, "hello")
        await _emit_progress(deps, "world")
        assert messages == ["hello", "world"]
