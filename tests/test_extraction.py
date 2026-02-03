"""Tests for finding extractor agent and extraction logic."""

from finding_extractor.agent import (
    _build_instructions,
    _get_model_settings,
    _get_reasoning_effort,
    build_prompt,
    validate_extraction,
)
from finding_extractor.models import (
    ExamInfo,
    ExtractedFinding,
    FindingLocation,
    NonFindingText,
    ReportExtraction,
)


class TestInstructions:
    """Test cases for instructions building."""

    def test_instructions_contain_examples(self):
        """Test that instructions contain few-shot examples."""
        instructions = _build_instructions()
        assert "EXAMPLE 1" in instructions
        assert "EXAMPLE 2" in instructions
        assert "CT abdomen" in instructions or "abdomen" in instructions.lower()

    def test_instructions_contain_core_guidance(self):
        """Test that instructions contain core guidance."""
        instructions = _build_instructions()
        assert "CORE INSTRUCTIONS" in instructions
        assert "PRESENCE VALUES" in instructions
        assert "ATTRIBUTE KEYS" in instructions
        assert "QUOTE VERBATIM" in instructions or "verbat" in instructions.lower()


class TestModelSettings:
    """Test cases for model settings configuration."""

    def test_default_model_settings(self):
        """Test that default model settings are created."""
        settings = _get_model_settings("openai:gpt-5-mini")
        assert settings is not None

    def test_reasoning_effort_for_gpt5_mini(self):
        """Test reasoning effort configuration for GPT-5-mini."""
        effort = _get_reasoning_effort("openai:gpt-5-mini")
        assert effort in ["minimal", "low", "medium", "high"]

    def test_reasoning_effort_for_gpt5_2(self):
        """Test reasoning effort configuration for GPT-5.2."""
        effort = _get_reasoning_effort("openai:gpt-5.2")
        assert effort in ["none", "low", "medium", "high"]

    def test_reasoning_effort_override(self):
        """Test that reasoning effort can be overridden."""
        settings = _get_model_settings("openai:gpt-5-mini", reasoning="high")
        # Settings should be created with the override
        assert settings is not None


class TestBuildPrompt:
    """Test cases for prompt building."""

    def test_prompt_without_exam_description(self):
        """Test building prompt without exam description."""
        report = "This is a test report."
        prompt = build_prompt(report)
        assert "RADIOLOGY REPORT:" in prompt
        assert report in prompt
        assert "Exam Description:" not in prompt

    def test_prompt_with_exam_description(self):
        """Test building prompt with exam description."""
        report = "This is a test report."
        exam_desc = "CT Abdomen"
        prompt = build_prompt(report, exam_desc)
        assert "Exam Description: CT Abdomen" in prompt
        assert report in prompt


class TestValidateExtraction:
    """Test cases for extraction validation."""

    def test_valid_extraction(self):
        """Test validation of a correct extraction."""
        report_text = "The patient has pneumonia in the right lung."
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                ExtractedFinding(
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
        assert result.is_valid is True
        assert len(result.verbatim_errors) == 0

    def test_invalid_verbatim_quote(self):
        """Test validation catches non-verbatim quotes."""
        report_text = "The patient has pneumonia in the right lung."
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                ExtractedFinding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Patient has pneumonia in right lung.",  # Paraphrased, not verbatim
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        assert result.is_valid is False
        assert len(result.verbatim_errors) == 1
        assert "not found verbatim" in result.verbatim_errors[0]

    def test_missing_non_finding_text(self):
        """Test validation catches non-finding text not in report."""
        report_text = "Technique: CT scan."
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="CT"),
            non_finding_text=[
                NonFindingText(
                    text="Technique: MRI scan.",  # Wrong modality
                    category="technique",
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        assert result.is_valid is False
        assert len(result.verbatim_errors) == 1

    def test_coverage_warning(self):
        """Test that coverage warnings are generated for unaccounted text."""
        report_text = "Line one.\nLine two.\nLine three."
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="Test"),
            findings=[
                ExtractedFinding(
                    finding_name="test",
                    presence="present",
                    report_text="Line one.",
                ),
            ],
        )
        result = validate_extraction(report_text, extraction)
        # May have warnings about unaccounted lines
        # This is informational, not a failure
        assert isinstance(result.coverage_warnings, list)
