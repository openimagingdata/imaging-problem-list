"""Pydantic models for radiology report finding extraction."""

from datetime import date
from typing import Literal

from pydantic import Field

from finding_extractor.core.base_model import StrictBaseModel

ReasoningLevel = Literal["none", "minimal", "low", "medium", "high"]
ReliabilityMode = Literal["strict", "lenient"]

CorrectionType = Literal["add_finding", "update_finding", "comment"]
CorrectionStatus = Literal["pending", "accepted", "rejected", "applied"]
JobStatus = Literal["pending", "running", "completed", "completed_with_warnings", "failed"]
Presence = Literal["present", "absent", "indeterminate", "possible"]
WarningReasonCategory = Literal["validation_failed", "verbatim_mismatch", "coverage_gap"]
UnresolvedReason = Literal["no_match", "search_low_confidence", "coding_error"]

Modality = Literal["CT", "XR", "MR", "US", "NM", "PET", "FLUORO", "MG", "DXA", "IR"]
BodyRegion = Literal[
    "chest",
    "abdomen",
    "pelvis",
    "head",
    "neck",
    "spine",
    "upper extremity",
    "lower extremity",
    "breast",
]
Contrast = Literal["with", "without", "without and with"]


class ExamInfo(StrictBaseModel):
    """Metadata about the imaging exam this extraction came from."""

    study_description: str = Field(
        description='Study description, e.g., "CT Abdomen and Pelvis With IV Contrast"'
    )
    study_date: date | None = Field(
        default=None,
        description="ISO date if known (YYYY-MM-DD)",
    )
    modality: Modality | None = Field(
        default=None,
        description='Modality code: "CT", "XR", "MR", "US", "NM", "PET", "FLUORO", "MG", "DXA", "IR".',
    )
    body_region: BodyRegion | None = Field(
        default=None,
        description='Constrained body region category: "chest", "abdomen", "head", etc.',
    )
    body_part: str | None = Field(
        default=None,
        description='Specific body part examined: "abdomen, pelvis", "brain", "shoulder", etc.',
    )
    contrast: Contrast | None = Field(
        default=None,
        description='Contrast status: "with", "without", "without and with", or null if N/A.',
    )
    laterality: Literal["left", "right", "bilateral"] | None = Field(
        default=None,
        description="Laterality of the examined body part, if applicable.",
    )


class FindingLocation(StrictBaseModel):
    """Where the finding is occurring.

    Separate from other attributes because location is often implied by the exam type
    rather than stated explicitly in the report text.
    """

    body_region: BodyRegion = Field(
        description="Body region",
    )
    specific_anatomy: str | None = Field(
        default=None,
        description='Specific anatomy: "right lower lobe", "left kidney interpolar region", "T9 vertebral body"',
    )
    laterality: Literal["left", "right", "bilateral"] | None = Field(
        default=None,
        description="Laterality, or None if not applicable",
    )


class FindingAttribute(StrictBaseModel):
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


class Finding(StrictBaseModel):
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
    presence: Presence = Field(
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
    source_section: Literal["findings", "impression", "both"] | None = Field(
        default=None,
        description=(
            "Which report section this finding was extracted from: "
            '"findings" (body/comment), "impression" (impression/conclusion), '
            '"both" (mentioned in both sections). '
            "null if section boundaries cannot be determined."
        ),
    )
    coding: "FindingCodingBundle | None" = Field(
        default=None,
        description="Inline coding status for finding and anatomic location.",
    )


class NonFindingText(StrictBaseModel):
    """Segments of report text identified as not containing findings.

    This lets us account for every piece of text in the report — findings go into
    Finding.report_text, everything else goes here.
    """

    text: str = Field(description="The verbatim text segment")
    category: Literal[
        "metadata",
        "technique",
        "indication",
        "comparison",
        "clinical_history",
        "impression",
        "other",
    ] = Field(
        description="Category of the non-finding text segment",
    )


class ExtractedReportFindings(StrictBaseModel):
    """Top-level output containing all extracted findings from a radiology report."""

    exam_info: ExamInfo = Field(description="Metadata about the imaging exam")
    findings: list[Finding] = Field(
        default_factory=list,
        description="All findings extracted from the report (present, absent, possible, indeterminate)",
    )
    non_finding_text: list[NonFindingText] = Field(
        default_factory=list,
        description="Report segments that don't contain clinical findings",
    )


class ChunkFinding(StrictBaseModel):
    """One finding extracted from a single chunk."""

    finding_name: str = Field(description="Concise clinical finding label.")
    presence: Presence = Field(description="present, absent, possible, or indeterminate.")
    location: FindingLocation | None = Field(
        default=None,
        description="Optional anatomic location.",
    )
    attributes: list[FindingAttribute] = Field(
        default_factory=list,
        description="Loose descriptive key/value attributes (for example: size, change_from_prior).",
    )
    report_text: str = Field(description="Verbatim evidence quote from the target chunk.")


class ExtractedChunkFindings(StrictBaseModel):
    """Chunk-level extraction output used by sub-agent calls."""

    findings: list[ChunkFinding] = Field(
        default_factory=list,
        description="Findings extracted from the target chunk.",
    )


class ValidationResult(StrictBaseModel):
    """Result of post-extraction validation.

    Contains warnings and errors detected during validation without blocking execution.
    The caller decides whether to retry or accept the extraction.
    """

    verbatim_errors: list[str] = Field(
        default_factory=list,
        description="Errors where report_text doesn't appear verbatim in the original report",
    )
    coverage_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about text segments that may have been skipped",
    )


class JobWarningPayload(StrictBaseModel):
    """Deterministic warning payload emitted for warning-capable job terminals."""

    schema_version: Literal["v1"] = "v1"
    reliability_mode: ReliabilityMode
    reason_categories: list[WarningReasonCategory] = Field(default_factory=list)
    dropped_findings_count: int = 0
    dropped_non_finding_count: int = 0
    validation_error_count: int = 0
    coverage_warning_count: int = 0
    section_failure_count: int = 0


class ExtractionUsage(StrictBaseModel):
    """Token and request usage captured from an extraction agent run."""

    requests: int = Field(default=0, description="Number of provider requests made.")
    input_tokens: int = Field(default=0, description="Total input tokens sent.")
    output_tokens: int = Field(default=0, description="Total output tokens received.")
    cache_read_tokens: int = Field(default=0, description="Provider cache-read token count.")
    cache_write_tokens: int = Field(default=0, description="Provider cache-write token count.")
    duration_ms: int | None = Field(
        default=None, description="Elapsed runtime duration in milliseconds."
    )
    details: dict[str, int] = Field(
        default_factory=dict,
        description="Provider-specific usage counters.",
    )


class ExtractionResult(StrictBaseModel):
    """Extraction payload and usage from one extraction call."""

    report_findings: ExtractedReportFindings = Field(description="Structured extraction output.")
    usage: ExtractionUsage | None = Field(
        default=None,
        description="Token/request usage for this call.",
    )


class ChunkExtractionResult(StrictBaseModel):
    """Chunk extraction payload and usage from one chunk call."""

    chunk_findings: ExtractedChunkFindings = Field(description="Chunk-scoped extraction output.")
    usage: ExtractionUsage | None = Field(
        default=None,
        description="Token/request usage for this chunk call.",
    )


CodingMethod = Literal["exact", "synonym", "search", "agent", "batch", "unresolved"]
LocationCodingMethod = Literal["search", "agent", "batch", "unresolved"]


class AlternateCode(StrictBaseModel):
    """A candidate OIFM code from search results."""

    oifm_id: str
    name: str


class LocationAlternateCode(StrictBaseModel):
    """A candidate anatomic location code from search results."""

    location_id: str
    location_name: str


class FindingCode(StrictBaseModel):
    """Inline OIFM coding status for one finding."""

    status: Literal["coded", "unmapped"] = "unmapped"
    oifm_id: str | None = None
    oifm_name: str | None = None
    method: CodingMethod = "unresolved"
    reason: UnresolvedReason | None = None
    candidates: list[AlternateCode] = Field(default_factory=list)


class LocationCode(StrictBaseModel):
    """Inline anatomic-location coding status for one finding."""

    status: Literal["coded", "unmapped"] = "unmapped"
    location_id: str | None = None
    location_name: str | None = None
    method: LocationCodingMethod = "unresolved"
    reason: UnresolvedReason | None = None
    candidates: list[LocationAlternateCode] = Field(default_factory=list)


class FindingCodingBundle(StrictBaseModel):
    """Inline coding payload attached to a finding."""

    finding_code: FindingCode = Field(default_factory=FindingCode)
    location_code: LocationCode = Field(default_factory=LocationCode)


class PipelineDiagnostics(StrictBaseModel):
    """Machine-parseable run diagnostics for stage/chunk orchestration."""

    mode: str
    total_chunks: int
    initial_failed_chunks: int
    remaining_failed_chunks: int
    total_chunk_attempts: int
    failed_chunk_ids: tuple[str, ...]
    failed_chunk_error_types: tuple[str, ...]
    reviewer_requested_chunks: int = 0
    reviewer_reextracted_chunks: int = 0
    # Deprecated — retained for backward compatibility with stored diagnostics JSON.
    # Always 0 for new extractions (chunk repair was removed).
    repaired_chunks: int = 0
    repair_attempts_used: int = 0

