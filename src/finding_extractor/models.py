"""Pydantic models for radiology report finding extraction."""

from typing import Literal

from pydantic import BaseModel, Field


class ExamInfo(BaseModel):
    """Metadata about the imaging exam this extraction came from."""

    study_description: str = Field(
        description='Study description, e.g., "CT Abdomen and Pelvis WO contrast"'
    )
    study_date: str | None = Field(
        default=None,
        description="ISO date if known (YYYY-MM-DD)",
    )
    modality: str | None = Field(
        default=None,
        description='Modality code: "CT", "XR", "MR", "US", "NM", etc.',
    )
    body_part: str | None = Field(
        default=None,
        description='Body part examined: "abdomen", "chest", "brain", "shoulder", etc.',
    )


class FindingLocation(BaseModel):
    """Where the finding is occurring.

    Separate from other attributes because location is often implied by the exam type
    rather than stated explicitly in the report text.
    """

    body_region: str = Field(
        description='Body region: "chest", "abdomen", "pelvis", "head", "neck", "upper extremity", "lower extremity", "breast"',
    )
    specific_anatomy: str | None = Field(
        default=None,
        description='Specific anatomy: "right lower lobe", "left kidney interpolar region", "T9 vertebral body"',
    )
    laterality: str | None = Field(
        default=None,
        description='Laterality: "left", "right", "bilateral", or None',
    )


class FindingAttribute(BaseModel):
    """Any descriptive property of a finding beyond presence and location.

    Flexible key-value structure for attributes like size, acuity, change from prior,
    severity, count, and morphology.
    """

    key: str = Field(
        description='Attribute key: "size", "acuity", "change_from_prior", "severity", "count", "morphology"'
    )
    value: str = Field(
        description='Attribute value: "3 mm", "acute", "stable", "moderate", "2", "nonobstructing"'
    )


class ExtractedFinding(BaseModel):
    """The core output model for each finding extracted from a radiology report.

    Key design points:
    - finding_name: concise, reusable clinical term (not a sentence)
    - presence: present/absent/indeterminate/possible. "possible" covers hedged language
      like "raising the possibility of", "suggestive of", "cannot exclude"
    - Both present and absent findings extracted ("no ascites" → ascites/absent)
    - report_text must be a verbatim excerpt — quote, not paraphrase
    - Multiple instances of same finding type → separate entries
    """

    finding_name: str = Field(
        description='Concise clinical term: "renal calculus", "hepatic steatosis"'
    )
    presence: Literal["present", "absent", "indeterminate", "possible"] = Field(
        description="Presence status: present, absent, indeterminate, or possible (for hedged language)"
    )
    location: FindingLocation | None = Field(
        default=None,
        description="Location of the finding, if applicable",
    )
    attributes: list[FindingAttribute] = Field(
        default_factory=list,
        description="Descriptive attributes of the finding (size, acuity, change_from_prior, etc.)",
    )
    report_text: str = Field(
        description="Verbatim quote from the report text that supports this finding"
    )


class NonFindingText(BaseModel):
    """Segments of report text identified as not containing findings.

    This lets us account for every piece of text in the report — findings go into
    ExtractedFinding.report_text, everything else goes here.
    """

    text: str = Field(description="The verbatim text segment")
    category: str = Field(
        description='Category: "metadata", "technique", "indication", "comparison", "clinical_history", "other"'
    )


class ReportExtraction(BaseModel):
    """Top-level output containing all extracted findings from a radiology report."""

    exam_info: ExamInfo = Field(description="Metadata about the imaging exam")
    findings: list[ExtractedFinding] = Field(
        default_factory=list,
        description="All findings extracted from the report (present, absent, possible, indeterminate)",
    )
    non_finding_text: list[NonFindingText] = Field(
        default_factory=list,
        description="Report segments that don't contain clinical findings",
    )


class ValidationResult(BaseModel):
    """Result of post-extraction validation.

    Contains warnings and errors detected during validation without blocking execution.
    The caller decides whether to retry or accept the extraction.
    """

    is_valid: bool = Field(description="Whether the extraction passed all critical checks")
    verbatim_errors: list[str] = Field(
        default_factory=list,
        description="Errors where report_text doesn't appear verbatim in the original report",
    )
    coverage_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about text segments that may have been skipped",
    )
