"""Tests for coding prompt builders."""

from types import SimpleNamespace

from finding_extractor.coding.prompt import (
    build_finding_selector_user_prompt,
    build_finding_term_user_prompt,
    build_location_selector_user_prompt,
    build_location_term_user_prompt,
)
from finding_extractor.models import ExamInfo, Finding, FindingLocation


def _exam_info() -> ExamInfo:
    return ExamInfo(
        study_description="CT Abdomen and Pelvis With Contrast",
        modality="CT",
        body_part="abdomen, pelvis",
    )


def _finding(*, location: FindingLocation | None = None) -> Finding:
    return Finding(
        finding_name="renal calculus",
        presence="present",
        location=location,
        report_text="3 mm stone in the right kidney.",
    )


def test_build_finding_term_user_prompt_renders_exam_and_finding_context():
    """Finding-term prompts include exam metadata and indexed findings."""
    prompt = build_finding_term_user_prompt(_exam_info(), [_finding()])

    assert "## EXAM INFO" in prompt
    assert "- Study: CT Abdomen and Pelvis With Contrast" in prompt
    assert "- Modality: CT" in prompt
    assert "### Finding 0" in prompt
    assert '- report_text: "3 mm stone in the right kidney."' in prompt


def test_build_location_term_user_prompt_handles_missing_location():
    """Location-term prompts render explicit empty markers when location is absent."""
    prompt = build_location_term_user_prompt(_exam_info(), [_finding(location=None)])

    assert "- body_region: (none)" in prompt
    assert "- specific_anatomy: (none)" in prompt
    assert "- laterality: (none)" in prompt


def test_build_finding_selector_user_prompt_renders_candidate_metadata():
    """Finding selector prompts include candidate descriptions, synonyms, and tags."""
    candidate = SimpleNamespace(
        oifm_id="OIFM:100",
        name="renal calculus",
        description="Stone in the kidney or collecting system.",
        synonyms=["kidney stone"],
        tags=["abdomen", "CT"],
    )

    prompt = build_finding_selector_user_prompt(_finding(), _exam_info(), [candidate])

    assert "## CANDIDATE FINDING CODES" in prompt
    assert "1. OIFM:100" in prompt
    assert "Synonyms: kidney stone" in prompt
    assert "Tags: abdomen, CT" in prompt


def test_build_location_selector_user_prompt_renders_hierarchy_fields():
    """Location selector prompts include hierarchy context for location candidates."""
    candidate = SimpleNamespace(
        id="LOC:RIGHT_KIDNEY",
        description="right kidney",
        region="abdomen",
        laterality="right",
        containment_parent=SimpleNamespace(display="kidney"),
        partof_parent=SimpleNamespace(display="urinary system"),
    )

    prompt = build_location_selector_user_prompt(
        _finding(
            location=FindingLocation(
                body_region="abdomen",
                specific_anatomy="right kidney",
                laterality="right",
            )
        ),
        _exam_info(),
        [candidate],
    )

    assert "## CANDIDATE LOCATIONS" in prompt
    assert "1. LOC:RIGHT_KIDNEY" in prompt
    assert "Containment: kidney" in prompt
    assert "Part-of: urinary system" in prompt
