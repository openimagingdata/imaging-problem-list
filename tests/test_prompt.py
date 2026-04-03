"""Tests for the prompt module — composable blocks and example loading."""

from finding_extractor.examples import load_example, load_examples
from finding_extractor.extractor.prompt import (
    ATTRIBUTES_BLOCK,
    CORE_INSTRUCTIONS_BLOCK,
    DEDUPLICATION_BLOCK,
    LOCATION_BLOCK,
    NON_FINDING_BLOCK,
    OUTPUT_FORMAT_BLOCK,
    PRESENCE_BLOCK,
    ROLE_BLOCK,
    build_system_prompt,
    format_examples,
)
from finding_extractor.models import ExtractedReportFindings


class TestPromptBlocks:
    """Each block constant is non-empty and contains expected keywords."""

    def test_role_block(self):
        assert len(ROLE_BLOCK) > 0
        assert "medical AI" in ROLE_BLOCK
        assert "radiology" in ROLE_BLOCK

    def test_core_instructions_block(self):
        assert "CORE INSTRUCTIONS" in CORE_INSTRUCTIONS_BLOCK
        assert "Read systematically" in CORE_INSTRUCTIONS_BLOCK
        assert "Extract ALL findings" in CORE_INSTRUCTIONS_BLOCK

    def test_presence_block(self):
        assert "PRESENCE VALUES" in PRESENCE_BLOCK
        for val in ("present", "absent", "indeterminate", "possible"):
            assert val in PRESENCE_BLOCK

    def test_attributes_block(self):
        assert "ATTRIBUTE KEYS" in ATTRIBUTES_BLOCK
        for key in ("size", "acuity", "change_from_prior", "severity", "count", "morphology"):
            assert key in ATTRIBUTES_BLOCK

    def test_location_block(self):
        assert "LOCATION GUIDANCE" in LOCATION_BLOCK
        assert "body_region" in LOCATION_BLOCK
        assert "specific_anatomy" in LOCATION_BLOCK
        assert "laterality" in LOCATION_BLOCK

    def test_non_finding_block(self):
        assert "NON-FINDING TEXT" in NON_FINDING_BLOCK
        for cat in ("metadata", "technique", "indication", "comparison", "clinical_history"):
            assert cat in NON_FINDING_BLOCK

    def test_deduplication_block(self):
        assert "SECTION PRIORITY" in DEDUPLICATION_BLOCK
        assert "Impression" in DEDUPLICATION_BLOCK
        assert "non_finding_text" in DEDUPLICATION_BLOCK
        assert "source_section" in DEDUPLICATION_BLOCK
        assert "UNIQUE" in DEDUPLICATION_BLOCK

    def test_attributes_block_additional_keys(self):
        """Expanded attribute keys include additional keys and anti-pattern guidance."""
        assert "obstruction" in ATTRIBUTES_BLOCK
        assert "characterization" in ATTRIBUTES_BLOCK
        assert "Do NOT use" in ATTRIBUTES_BLOCK

    def test_presence_block_disambiguation(self):
        """Presence block includes hedging language disambiguation."""
        assert "Distinguishing" in PRESENCE_BLOCK
        assert "decreased attenuation" in PRESENCE_BLOCK

    def test_non_finding_block_impression_instruction(self):
        """Impression entry cross-references SECTION PRIORITY instead of restating rules."""
        assert "SECTION PRIORITY" in NON_FINDING_BLOCK

    def test_output_format_block(self):
        assert "OUTPUT FORMAT" in OUTPUT_FORMAT_BLOCK
        assert "VERBATIM" in OUTPUT_FORMAT_BLOCK
        assert "ExtractedReportFindings" in OUTPUT_FORMAT_BLOCK

    def test_output_format_block_source_section(self):
        """OUTPUT_FORMAT_BLOCK includes source_section field guidance."""
        assert "source_section" in OUTPUT_FORMAT_BLOCK
        assert "SECTION PRIORITY" in OUTPUT_FORMAT_BLOCK


class TestLoadExamples:
    """Example loading from YAML."""

    def test_load_ct_abdomen(self):
        report_text, extraction = load_example("ct_abdomen")
        assert isinstance(report_text, str)
        assert len(report_text) > 100
        assert isinstance(extraction, ExtractedReportFindings)
        assert len(extraction.findings) > 0
        assert extraction.exam_info.modality == "CT"

    def test_load_xr_chest(self):
        report_text, extraction = load_example("xr_chest")
        assert isinstance(report_text, str)
        assert len(report_text) > 100
        assert isinstance(extraction, ExtractedReportFindings)
        assert len(extraction.findings) > 0
        assert extraction.exam_info.modality == "XR"

    def test_load_examples_returns_two(self):
        examples = load_examples()
        assert len(examples) == 2
        for report_text, extraction in examples:
            assert isinstance(report_text, str)
            assert isinstance(extraction, ExtractedReportFindings)

    def test_load_examples_extractions_are_valid(self):
        """Each loaded extraction has findings and non-finding text."""
        for _, extraction in load_examples():
            assert len(extraction.findings) > 0
            assert len(extraction.non_finding_text) > 0
            assert extraction.exam_info.study_description


class TestFormatExamples:
    """Example formatting for system prompt."""

    def test_format_produces_markers(self):
        examples = load_examples()
        formatted = format_examples(examples)
        assert "=== EXAMPLE 1 ===" in formatted
        assert "=== EXAMPLE 2 ===" in formatted

    def test_format_contains_json(self):
        examples = load_examples()
        formatted = format_examples(examples)
        assert "Input report:" in formatted
        assert "ExtractedReportFindings JSON" in formatted


class TestBuildSystemPrompt:
    """System prompt assembly."""

    def test_contains_all_blocks(self):
        prompt = build_system_prompt()
        assert "medical AI" in prompt  # ROLE_BLOCK
        assert "CORE INSTRUCTIONS" in prompt
        assert "SECTION PRIORITY" in prompt
        assert "PRESENCE VALUES" in prompt
        assert "ATTRIBUTE KEYS" in prompt
        assert "LOCATION GUIDANCE" in prompt
        assert "NON-FINDING TEXT" in prompt
        assert "OUTPUT FORMAT" in prompt
        assert "VERBATIM" in prompt

    def test_contains_examples(self):
        prompt = build_system_prompt()
        assert "EXAMPLE 1" in prompt
        assert "EXAMPLE 2" in prompt

    def test_blocks_in_order(self):
        prompt = build_system_prompt()
        sections = [
            "medical AI",
            "## CORE INSTRUCTIONS",
            "## SECTION PRIORITY",
            "## PRESENCE VALUES",
            "## ATTRIBUTE KEYS",
            "## LOCATION GUIDANCE",
            "## NON-FINDING TEXT",
            "EXAMPLE 1",
            "## OUTPUT FORMAT",
        ]
        positions = [prompt.index(s) for s in sections]
        assert positions == sorted(positions), f"Sections not in order: {positions}"

    def test_custom_examples(self):
        """build_system_prompt accepts explicit examples list."""
        examples = load_examples()[:1]  # just the first
        prompt = build_system_prompt(examples=examples)
        assert "EXAMPLE 1" in prompt
        assert "EXAMPLE 2" not in prompt
