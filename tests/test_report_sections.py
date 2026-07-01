"""Tests for deterministic section detection in radiology reports."""

from finding_extractor.extractor.report_sections import (
    parse_report_sections,
    sections_from_json,
    sections_to_json,
)

# ---------------------------------------------------------------------------
# Sample reports
# ---------------------------------------------------------------------------

STRUCTURED_REPORT = """\
History: flank pain, h/o stones

Technique: CT of the abdomen and pelvis without contrast.

Comparison: 06/04/2024

Comment:
The liver is unremarkable.
There is no hydronephrosis.

Impression:
No acute finding."""

MARKDOWN_BOLD_REPORT = """\
### **Findings:**
The lungs are clear.

### **Impression:**
No acute findings."""

BOLD_ONLY_REPORT = """\
**Technique:**
CT abdomen pelvis without contrast.

**Findings:**
Normal exam.

**Impression:**
No acute findings."""

ALLCAPS_REPORT = """\
TECHNIQUE:
CT without contrast.

FINDINGS:
Normal.

IMPRESSION:
Normal exam."""

UNSTRUCTURED_REPORT = """\
The heart is normal.
There is no pleural effusion.
Normal exam."""

IMPRESSION_ONLY_REPORT = """\
Impression:
No acute findings."""


# ---------------------------------------------------------------------------
# TestHeaderMatching
# ---------------------------------------------------------------------------


class TestHeaderMatching:
    """Validate header pattern matching against known section names."""

    def test_markdown_heading_bold(self):
        result = parse_report_sections(MARKDOWN_BOLD_REPORT)
        assert result.has_section("findings")
        assert result.has_section("impression")

    def test_bold_only(self):
        result = parse_report_sections(BOLD_ONLY_REPORT)
        assert result.has_section("technique")
        assert result.has_section("findings")
        assert result.has_section("impression")

    def test_allcaps(self):
        result = parse_report_sections(ALLCAPS_REPORT)
        assert result.has_section("technique")
        assert result.has_section("findings")
        assert result.has_section("impression")

    def test_allcaps_with_indentation(self):
        text = """\
         FINDINGS:
         No pleural effusion.

         IMPRESSION:
         No acute cardiopulmonary process.
        """
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert result.has_section("impression")

    def test_standalone_allcaps_findings_header(self):
        text = """\
FINDINGS
No pleural effusion.
No pulmonary nodule.
"""
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert result.get_section_content("findings").strip() == text.strip()

    def test_title_case_with_content(self):
        """Title case pattern: 'History: flank pain'."""
        result = parse_report_sections(STRUCTURED_REPORT)
        assert result.has_section("clinical_history")

    def test_comment_alias_maps_to_findings(self):
        result = parse_report_sections(STRUCTURED_REPORT)
        assert result.has_section("findings")
        section = result.get_section("findings")
        assert section is not None
        assert "Comment" in section.header_text

    def test_body_alias_maps_to_findings(self):
        text = "Body:\nNo focal airspace opacity."
        result = parse_report_sections(text)
        assert result.has_section("findings")

    def test_conclusion_alias_maps_to_impression(self):
        text = "Conclusion:\nNo acute finding."
        result = parse_report_sections(text)
        assert result.has_section("impression")

    def test_impressions_plural_alias_maps_to_impression(self):
        text = "IMPRESSIONS:\n1. No acute cardiopulmonary abnormality."
        result = parse_report_sections(text)
        assert result.has_section("impression")

    def test_impresson_typo_alias_maps_to_impression(self):
        text = "IMPRESSON:\nNo pleural effusion."
        result = parse_report_sections(text)
        assert result.has_section("impression")

    def test_impression_and_recommendation_alias_maps_to_impression(self):
        text = "IMPRESSION AND RECOMMENDATION:\nNo acute finding."
        result = parse_report_sections(text)
        assert result.has_section("impression")

    def test_clinical_information_alias_maps_to_indication(self):
        text = "Clinical Information: fever and cough\n\nFindings:\nNormal."
        result = parse_report_sections(text)
        assert result.has_section("indication")

    def test_reason_for_exam_alias_maps_to_indication(self):
        text = "Reason for examination: shortness of breath\n\nFindings:\nNormal."
        result = parse_report_sections(text)
        assert result.has_section("indication")

    def test_finsings_typo_alias_maps_to_findings(self):
        text = "FINSINGS:\nNo focal airspace opacity."
        result = parse_report_sections(text)
        assert result.has_section("findings")

    def test_comparision_typo_alias_maps_to_comparison(self):
        text = "COMPARISION:\nChest radiograph from 01/01/2025."
        result = parse_report_sections(text)
        assert result.has_section("comparison")

    def test_examination_alias_maps_to_technique(self):
        text = "EXAMINATION: Chest radiograph.\n\nFINDINGS:\nNo focal opacity."
        result = parse_report_sections(text)
        assert result.has_section("technique")

    def test_hyphen_delimiter_supported(self):
        text = "FINDINGS -\nNo pleural effusion.\n\nIMPRESSION -\nNo acute finding."
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert result.has_section("impression")

    def test_findings_impression_combined_header_maps_to_findings(self):
        text = "Findings/Impression:\nNo pleural effusion or focal consolidation."
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert not result.has_section("impression")

    def test_infers_unheaded_findings_block_before_impression(self):
        text = (
            "INDICATION: flank pain\n\n"
            "COMPARISON: CT from 01/01/2024.\n\n"
            "There is a 3 mm right renal calculus.\n"
            "No hydronephrosis.\n\n"
            "IMPRESSION:\n"
            "Right nephrolithiasis.\n"
        )
        result = parse_report_sections(text)
        assert result.has_section("indication")
        assert result.has_section("comparison")
        assert result.has_section("findings")
        assert result.has_section("impression")
        findings = result.get_section_content("findings")
        assert findings is not None
        assert "3 mm right renal calculus" in findings
        assert "No hydronephrosis" in findings

    def test_subsection_not_matched(self):
        """Subsections like **Liver:** should NOT be matched."""
        text = "**Findings:**\n**Liver:** Normal.\n**Spleen:** Normal."
        result = parse_report_sections(text)
        names = result.section_names()
        assert "findings" in names
        assert len(names) == 1  # only findings, not liver/spleen

    def test_finding_text_not_matched(self):
        """Body text that happens to start with a word should not be matched."""
        text = "Findings:\nStone in right kidney measuring 3 mm."
        result = parse_report_sections(text)
        assert len(result.sections) == 1
        assert result.sections[0].name == "findings"

    def test_unknown_header_ignored(self):
        """Headers not in the whitelist are ignored."""
        text = "Protocol:\nStandard.\n\nFindings:\nNormal."
        result = parse_report_sections(text)
        names = result.section_names()
        assert "findings" in names
        # "protocol" is not in the whitelist
        assert all(n != "protocol" for n in names)

    def test_recommendation_alias(self):
        text = "Recommendation:\nCorrelate clinically."
        result = parse_report_sections(text)
        assert result.has_section("recommendation")

    def test_clinical_correlation_alias(self):
        text = "Clinical Correlation:\nCorrelate with symptoms."
        result = parse_report_sections(text)
        assert result.has_section("recommendation")

    def test_recommendations_follow_up_alias_maps_to_recommendation(self):
        text = "Recommendations and follow-up:\nRepeat CT in 3 months."
        result = parse_report_sections(text)
        assert result.has_section("recommendation")

    def test_addendum_header_maps_to_addendum(self):
        text = "Addendum:\nPrior exam now available."
        result = parse_report_sections(text)
        assert result.has_section("addendum")

    def test_title_case_does_not_consume_across_newlines(self):
        """Title case pattern must not match across newlines, preventing later headers."""
        text = "Findings: No acute findings.\n\nImpression:\nNormal study."
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert result.has_section("impression")
        assert len(result.sections) == 2

    def test_repeated_same_header_does_not_prevent_later_headers(self):
        """Multiple instances of the same header should not prevent detection of other sections."""
        text = "Findings: First note.\n\nFindings: Second note.\n\nImpression:\nNormal."
        result = parse_report_sections(text)
        assert result.has_section("findings")
        assert result.has_section("impression")
        # Should detect at least findings and impression
        names = result.section_names()
        assert "findings" in names
        assert "impression" in names

    def test_capitalized_body_text_not_mistaken_for_header(self):
        """Body text with capitals and colon should not create bogus sections."""
        text = "Findings:\nPatient Name: John Doe\nStudy Type: CT Scan\n\nImpression:\nNormal."
        result = parse_report_sections(text)
        names = result.section_names()
        # Should only detect findings and impression, not "patient name" or "study type"
        assert "findings" in names
        assert "impression" in names
        assert all(n in ["findings", "impression"] for n in names)


# ---------------------------------------------------------------------------
# TestSectionDetection
# ---------------------------------------------------------------------------


class TestSectionDetection:
    """Validate section boundary computation."""

    def test_structured_report_section_order(self):
        result = parse_report_sections(STRUCTURED_REPORT)
        names = result.section_names()
        assert "clinical_history" in names
        assert "technique" in names
        assert "comparison" in names
        assert "findings" in names
        assert "impression" in names

    def test_no_header_report_returns_empty(self):
        result = parse_report_sections(UNSTRUCTURED_REPORT)
        assert result.sections == []

    def test_section_boundaries_correct(self):
        result = parse_report_sections(ALLCAPS_REPORT)
        technique = result.get_section("technique")
        findings = result.get_section("findings")
        impression = result.get_section("impression")
        assert technique is not None
        assert findings is not None
        assert impression is not None
        # technique starts at line 0, findings at line 3, impression at line 6
        assert technique.start_line < findings.start_line
        assert findings.start_line < impression.start_line
        # end of one section is start of next
        assert technique.end_line == findings.start_line
        assert findings.end_line == impression.start_line

    def test_last_section_extends_to_end(self):
        result = parse_report_sections(ALLCAPS_REPORT)
        impression = result.get_section("impression")
        assert impression is not None
        total_lines = len(ALLCAPS_REPORT.split("\n"))
        assert impression.end_line == total_lines

    def test_multiple_sections_in_order(self):
        result = parse_report_sections(BOLD_ONLY_REPORT)
        positions = [s.start_line for s in result.sections]
        assert positions == sorted(positions)

    def test_single_section_report(self):
        result = parse_report_sections(IMPRESSION_ONLY_REPORT)
        assert len(result.sections) == 1
        assert result.sections[0].name == "impression"


# ---------------------------------------------------------------------------
# TestPreprocessedReport
# ---------------------------------------------------------------------------


class TestPreprocessedReport:
    """Validate hint formatting, accessors, and serialization."""

    def test_no_sections_hint_is_none(self):
        result = parse_report_sections(UNSTRUCTURED_REPORT)
        assert result.format_section_hint() is None

    def test_hint_contains_section_names(self):
        result = parse_report_sections(STRUCTURED_REPORT)
        hint = result.format_section_hint()
        assert hint is not None
        assert "REPORT STRUCTURE" in hint
        assert "FINDINGS" in hint
        assert "IMPRESSION" in hint

    def test_hint_with_guidance_line(self):
        """When both findings and impression exist, hint includes extraction guidance."""
        result = parse_report_sections(STRUCTURED_REPORT)
        hint = result.format_section_hint()
        assert hint is not None
        assert "source_section" in hint

    def test_impression_only_no_guidance_line(self):
        """When only impression exists (no findings), no extraction guidance line."""
        result = parse_report_sections(IMPRESSION_ONLY_REPORT)
        hint = result.format_section_hint()
        assert hint is not None
        assert "IMPRESSION" in hint
        # No guidance line since there's no findings section
        assert "source_section" not in hint

    def test_get_section_returns_none_for_missing(self):
        result = parse_report_sections(UNSTRUCTURED_REPORT)
        assert result.get_section("findings") is None

    def test_has_section_false_for_missing(self):
        result = parse_report_sections(UNSTRUCTURED_REPORT)
        assert result.has_section("findings") is False

    def test_json_serialization_round_trip(self):
        result = parse_report_sections(STRUCTURED_REPORT)
        json_str = sections_to_json(result.sections)
        assert json_str is not None

        restored = sections_from_json(json_str)
        assert len(restored) == len(result.sections)
        for orig, rest in zip(result.sections, restored, strict=True):
            assert orig.name == rest.name
            assert orig.start_line == rest.start_line
            assert orig.end_line == rest.end_line
            assert orig.header_text == rest.header_text

    def test_sections_to_json_none_when_empty(self):
        result = parse_report_sections(UNSTRUCTURED_REPORT)
        assert sections_to_json(result.sections) is None


# ---------------------------------------------------------------------------
# TestBuildPromptIntegration
# ---------------------------------------------------------------------------


class TestBuildPromptIntegration:
    """Verify build_prompt() integrates preprocessing correctly."""

    def test_structured_report_gets_hint(self):
        from finding_extractor.extractor.agent import build_prompt

        prompt = build_prompt(STRUCTURED_REPORT)
        assert "REPORT STRUCTURE" in prompt
        assert "RADIOLOGY REPORT:" in prompt
        # Hint is before the report delimiter
        hint_pos = prompt.index("REPORT STRUCTURE")
        report_pos = prompt.index("RADIOLOGY REPORT:")
        assert hint_pos < report_pos

    def test_unstructured_report_no_hint(self):
        from finding_extractor.extractor.agent import build_prompt

        prompt = build_prompt(UNSTRUCTURED_REPORT)
        assert "REPORT STRUCTURE" not in prompt
        assert "RADIOLOGY REPORT:" in prompt

    def test_verbatim_check_unaffected(self):
        """Section hints don't interfere with verbatim validation."""
        from finding_extractor.extractor.agent import build_prompt, check_verbatim
        from finding_extractor.models import (
            ExamInfo,
            ExtractedReportFindings,
            Finding,
        )

        prompt = build_prompt(STRUCTURED_REPORT)
        assert STRUCTURED_REPORT in prompt

        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT"),
            findings=[
                Finding(
                    finding_name="hydronephrosis",
                    presence="absent",
                    report_text="There is no hydronephrosis.",
                )
            ],
        )
        errors = check_verbatim(STRUCTURED_REPORT, extraction)
        assert errors == []

    def test_study_description_with_hint(self):
        from finding_extractor.extractor.agent import build_prompt

        prompt = build_prompt(STRUCTURED_REPORT, study_description="CT Abdomen")
        assert "Exam Description: CT Abdomen" in prompt
        assert "REPORT STRUCTURE" in prompt
        # study_description comes before hint
        desc_pos = prompt.index("Exam Description:")
        hint_pos = prompt.index("REPORT STRUCTURE")
        assert desc_pos < hint_pos
