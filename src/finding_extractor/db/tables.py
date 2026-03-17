"""SQLModel table definitions for the persistence layer."""

from __future__ import annotations

from typing import get_args

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from finding_extractor.models import CorrectionStatus, CorrectionType, JobStatus


def _literal_check(column: str, literal_type: object) -> str:
    """Build SQL CHECK text from a Literal alias."""
    values = ", ".join(f"'{value}'" for value in get_args(literal_type))
    return f"{column} IN ({values})"


class ReportRow(SQLModel, table=True):
    """Deduplicated source report content."""

    __tablename__ = "reports"

    id: str = Field(primary_key=True)
    text_hash: str = Field(unique=True, index=True)
    report_text: str
    source_ref: str | None = None
    patient_id: str | None = None
    section_structure_json: str | None = None
    created_at: str


class ExtractionRow(SQLModel, table=True):
    """Single extraction run for a given report."""

    __tablename__ = "extractions"

    id: str = Field(primary_key=True)
    report_id: str = Field(foreign_key="reports.id", index=True)
    created_at: str = Field(index=True)
    model_name: str
    reasoning_effort: str | None = None
    study_description_hint: str | None = None
    study_description: str | None = None
    study_date: str | None = None
    modality: str | None = None
    body_region: str | None = None
    body_part: str | None = None
    contrast: str | None = None
    laterality: str | None = None
    finding_count: int = 0
    coded_finding_count: int | None = None
    unresolved_finding_count: int | None = None
    coding_model: str | None = None
    coding_reasoning: str | None = None
    coding_completed_at: str | None = None
    coding_duration_ms: int | None = None
    coding_trace_id: str | None = None
    diagnostics_json: str | None = None
    trace_id: str | None = None
    extraction_json: str
    validation_json: str | None = None
    # Token usage columns
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    model_requests: int | None = None
    duration_ms: int | None = None
    usage_details_json: str | None = None


class CorrectionRow(SQLModel, table=True):
    """Human correction suggestions/comments for an extraction."""

    __tablename__ = "corrections"
    __table_args__ = (
        CheckConstraint(
            _literal_check("correction_type", CorrectionType),
            name="check_correction_type",
        ),
        CheckConstraint(
            _literal_check("status", CorrectionStatus),
            name="check_correction_status",
        ),
    )

    id: str = Field(primary_key=True)
    extraction_id: str = Field(foreign_key="extractions.id", index=True)
    target_finding_index: int | None = None
    target_json_path: str | None = None
    correction_type: str
    status: str
    proposed_finding_json: str | None = None
    attribute_overrides_json: str | None = None
    comment: str | None = None
    created_by: str | None = None
    username: str | None = Field(default=None, foreign_key="users.username")
    created_at: str


class JobRow(SQLModel, table=True):
    """Extraction job status row for async API polling."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            _literal_check("status", JobStatus),
            name="check_job_status",
        ),
    )

    id: str = Field(primary_key=True)
    report_id: str = Field(foreign_key="reports.id", index=True)
    status: str = Field(index=True)
    created_at: str = Field(index=True)
    started_at: str | None = None
    completed_at: str | None = None
    extraction_id: str | None = Field(default=None, foreign_key="extractions.id")
    error: str | None = None
    status_message: str | None = None
    warning_payload_json: str | None = None


class UserRow(SQLModel, table=True):
    """User accounts for correction attribution."""

    __tablename__ = "users"

    username: str = Field(primary_key=True)
    name: str
    email: str
    created_at: str
