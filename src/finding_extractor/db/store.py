"""Public persistence facade over the internal db modules."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from finding_extractor.models import (
    CorrectionStatus,
    CorrectionType,
    ExtractedReportFindings,
    ExtractionUsage,
    Finding,
    JobStatus,
    JobWarningPayload,
    PipelineDiagnostics,
    ValidationResult,
)
from finding_extractor.read_models import (
    ExtractionDetail,
    ExtractionSummary,
    ReportDetail,
    ReportSummary,
)

from . import corrections, extractions, jobs, reports, users
from .corrections import StoredCorrection
from .engine import StoreRuntime
from .jobs import StoredJob
from .tables import CorrectionRow, ExtractionRow, JobRow, ReportRow, UserRow
from .users import StoredUser


class ExtractionStore:
    """Async SQLModel-backed persistence for reports, extraction runs, and corrections."""

    EXPECTED_REVISION = StoreRuntime.EXPECTED_REVISION

    def __init__(self, db_path: Path | str):
        self._runtime = StoreRuntime(db_path)

    @property
    def db_path(self) -> Path:
        """Configured SQLite path."""
        return self._runtime.db_path

    @property
    def engine(self) -> AsyncEngine:
        """Expose async engine for tests/integration wiring."""
        return self._runtime.engine

    async def init(self) -> None:
        """Initialize database tables (idempotent)."""
        await self._runtime.init()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide an AsyncSession context manager."""
        async with self._runtime.session() as session:
            yield session

    async def check_migration_current(self) -> str | None:
        """Check DB is at the expected Alembic migration revision."""
        return await self._runtime.check_migration_current()

    async def close(self) -> None:
        """Dispose async engine and pooled connections."""
        await self._runtime.close()

    async def upsert_report(
        self, report_text: str, source_ref: str | None = None, patient_id: str | None = None
    ) -> ReportSummary:
        return await reports.upsert_report(
            self._runtime,
            report_text,
            source_ref=source_ref,
            patient_id=patient_id,
        )

    async def create_extraction(
        self,
        report_id: str,
        extraction: ExtractedReportFindings,
        model_name: str,
        reasoning_effort: str | None = None,
        study_description_hint: str | None = None,
        validation_result: ValidationResult | None = None,
        usage: ExtractionUsage | None = None,
        pipeline_diagnostics: PipelineDiagnostics | None = None,
        trace_id: str | None = None,
    ) -> ExtractionSummary:
        return await extractions.create_extraction(
            self._runtime,
            report_id=report_id,
            extraction=extraction,
            model_name=model_name,
            reasoning_effort=reasoning_effort,
            study_description_hint=study_description_hint,
            validation_result=validation_result,
            usage=usage,
            pipeline_diagnostics=pipeline_diagnostics,
            trace_id=trace_id,
        )

    async def get_report(self, report_id: str) -> ReportDetail | None:
        return await reports.get_report(self._runtime, report_id)

    async def list_reports(self, limit: int = 50, offset: int = 0) -> list[ReportSummary]:
        return await reports.list_reports(self._runtime, limit=limit, offset=offset)

    async def get_extraction(self, extraction_id: str) -> ExtractionDetail | None:
        return await extractions.get_extraction(self._runtime, extraction_id)

    async def list_extractions(self, report_id: str) -> list[ExtractionSummary]:
        return await extractions.list_extractions(self._runtime, report_id)

    async def update_extraction_coding(
        self,
        *,
        extraction_id: str,
        extraction: ExtractedReportFindings,
        coding_model: str,
        coding_reasoning: str | None,
        coding_duration_ms: int | None,
        coding_trace_id: str | None,
    ) -> ExtractionDetail:
        return await extractions.update_extraction_coding(
            self._runtime,
            extraction_id=extraction_id,
            extraction=extraction,
            coding_model=coding_model,
            coding_reasoning=coding_reasoning,
            coding_duration_ms=coding_duration_ms,
            coding_trace_id=coding_trace_id,
        )

    async def create_job(
        self,
        job_id: str,
        report_id: str,
        extraction_id: str | None = None,
        status: JobStatus = "pending",
    ) -> StoredJob:
        return await jobs.create_job(
            self._runtime,
            job_id=job_id,
            report_id=report_id,
            extraction_id=extraction_id,
            status=status,
        )

    async def get_job(self, job_id: str) -> StoredJob | None:
        return await jobs.get_job(self._runtime, job_id)

    async def update_job_status_message(self, job_id: str, message: str) -> None:
        await jobs.update_job_status_message(self._runtime, job_id, message)

    async def mark_job_running(self, job_id: str) -> None:
        await jobs.mark_job_running(self._runtime, job_id)

    async def mark_job_completed(
        self,
        job_id: str,
        extraction_id: str,
        *,
        status_message: str = "[stage:completed] extraction_complete",
    ) -> None:
        await jobs.mark_job_completed(
            self._runtime,
            job_id,
            extraction_id,
            status_message=status_message,
        )

    async def mark_job_completed_with_warnings(
        self,
        job_id: str,
        extraction_id: str,
        warning_payload: JobWarningPayload,
        *,
        status_message: str = "[stage:completed_with_warnings] extraction_complete",
    ) -> None:
        await jobs.mark_job_completed_with_warnings(
            self._runtime,
            job_id,
            extraction_id,
            warning_payload,
            status_message=status_message,
        )

    async def mark_job_failed(
        self,
        job_id: str,
        error: str,
        warning_payload: JobWarningPayload | None = None,
        *,
        status_message: str | None = None,
    ) -> None:
        await jobs.mark_job_failed(
            self._runtime,
            job_id,
            error,
            warning_payload=warning_payload,
            status_message=status_message,
        )

    async def get_finding_path(self, extraction_id: str, finding_index: int) -> str | None:
        return await extractions.get_finding_path(self._runtime, extraction_id, finding_index)

    async def record_correction(
        self,
        extraction_id: str,
        correction_type: CorrectionType,
        *,
        target_finding_index: int | None = None,
        target_json_path: str | None = None,
        proposed_finding: Finding | None = None,
        attribute_overrides: dict[str, str] | None = None,
        comment: str | None = None,
        created_by: str | None = None,
        username: str | None = None,
        status: CorrectionStatus = "pending",
    ) -> StoredCorrection:
        return await corrections.record_correction(
            self._runtime,
            extraction_id,
            correction_type,
            target_finding_index=target_finding_index,
            target_json_path=target_json_path,
            proposed_finding=proposed_finding,
            attribute_overrides=attribute_overrides,
            comment=comment,
            created_by=created_by,
            username=username,
            status=status,
        )

    async def list_corrections(self, extraction_id: str) -> list[StoredCorrection]:
        return await corrections.list_corrections(self._runtime, extraction_id)

    async def create_user(self, username: str, name: str, email: str) -> StoredUser:
        return await users.create_user(self._runtime, username, name, email)

    async def get_user(self, username: str) -> StoredUser | None:
        return await users.get_user(self._runtime, username)

    async def list_users(self) -> list[StoredUser]:
        return await users.list_users(self._runtime)


__all__ = [
    "CorrectionRow",
    "ExtractionDetail",
    "ExtractionRow",
    "ExtractionSummary",
    "ExtractionStore",
    "JobRow",
    "ReportRow",
    "ReportDetail",
    "ReportSummary",
    "StoredCorrection",
    "StoredJob",
    "StoredUser",
    "UserRow",
]
