"""Request/response models for the API layer."""

from pydantic import ConfigDict, Field

from finding_extractor.core.base_model import StrictBaseModel
from finding_extractor.models import (
    CorrectionStatus,
    CorrectionType,
    Finding,
    JobStatus,
    JobWarningPayload,
    ReliabilityMode,
)


class SubmitReportRequest(StrictBaseModel):
    """Payload for report create/upsert."""

    report_text: str = Field(min_length=1)
    source_ref: str | None = None
    patient_id: str | None = None


class TriggerExtractionRequest(StrictBaseModel):
    """Payload for queueing extraction."""

    model_config = ConfigDict(populate_by_name=True)

    model: str | None = None
    reasoning: str | None = None
    study_description: str | None = None
    reliability_mode: ReliabilityMode = "strict"
    validate_output: bool = Field(default=True, alias="validate")


class TriggerExtractionResponse(StrictBaseModel):
    """Accepted job response for async extraction."""

    job_id: str
    report_id: str
    status: JobStatus


class TriggerCodingRequest(StrictBaseModel):
    """Payload for queueing coding on an existing extraction."""

    model: str | None = None
    reasoning: str | None = None


class TriggerCodingResponse(StrictBaseModel):
    """Accepted job response for async coding."""

    job_id: str
    extraction_id: str
    status: JobStatus


class StatusEventResponse(StrictBaseModel):
    """Structured stage/status event parsed from worker status messages."""

    version: str = "v2"
    stage: str
    detail: str | None = None


class JobResponse(StrictBaseModel):
    """Job polling response."""

    job_id: str
    report_id: str
    status: JobStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    extraction_id: str | None = None
    error: str | None = None
    status_message: str | None = None
    status_event: StatusEventResponse | None = None
    warning_payload: JobWarningPayload | None = None


class CreateCorrectionRequest(StrictBaseModel):
    """Payload for correction creation.

    Note: `created_by` is deprecated in favor of `username` for formal user attribution.
    """

    correction_type: CorrectionType
    target_finding_index: int | None = None
    target_json_path: str | None = None
    proposed_finding: Finding | None = None
    attribute_overrides: dict[str, str] | None = None
    comment: str | None = None
    username: str
    status: CorrectionStatus = "pending"


class HealthResponse(StrictBaseModel):
    """Basic health/readiness response."""

    status: str


class UserResponse(StrictBaseModel):
    """User account for correction attribution."""

    username: str
    name: str
    email: str


class CorrectionResponse(StrictBaseModel):
    """Correction list/create response."""

    id: str
    extraction_id: str
    target_finding_index: int | None = None
    target_json_path: str | None = None
    correction_type: CorrectionType
    status: CorrectionStatus
    comment: str | None = None
    author: UserResponse | None = None
    created_by: str | None = None
    created_at: str


class AvailableModelResponse(StrictBaseModel):
    """Single selectable model returned from model discovery."""

    id: str
    provider: str
    tier: str
    is_default: bool = False
    supported_reasoning: list[str] = Field(default_factory=list)
    default_reasoning: str = "none"


class ModelCatalogResponse(StrictBaseModel):
    """Model discovery response with cache freshness metadata."""

    updated_at: str
    stale: bool
    refresh_interval_seconds: int
    models: list[AvailableModelResponse]
