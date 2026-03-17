"""Job persistence helpers and public job return type."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlmodel import select

from finding_extractor.db.engine import StoreRuntime
from finding_extractor.db.tables import JobRow
from finding_extractor.models import JobStatus, JobWarningPayload


@dataclass(frozen=True)
class StoredJob:
    """A persisted background job for extraction execution."""

    id: str
    report_id: str
    status: JobStatus
    created_at: str
    started_at: str | None
    completed_at: str | None
    extraction_id: str | None
    error: str | None
    status_message: str | None
    warning_payload: JobWarningPayload | None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stored_job_from_row(row: JobRow) -> StoredJob:
    warning_payload = (
        JobWarningPayload.model_validate(json.loads(row.warning_payload_json))
        if row.warning_payload_json is not None
        else None
    )
    return StoredJob(
        id=row.id,
        report_id=row.report_id,
        status=cast(JobStatus, row.status),
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        extraction_id=row.extraction_id,
        error=row.error,
        status_message=row.status_message,
        warning_payload=warning_payload,
    )


async def create_job(
    runtime: StoreRuntime,
    *,
    job_id: str,
    report_id: str,
    extraction_id: str | None = None,
    status: JobStatus = "pending",
) -> StoredJob:
    """Create a job row before enqueueing worker execution."""
    job = JobRow(
        id=job_id,
        report_id=report_id,
        extraction_id=extraction_id,
        status=status,
        created_at=_utc_now_iso(),
    )
    async with runtime.session() as session:
        session.add(job)
        await session.commit()
    return _stored_job_from_row(job)


async def get_job(runtime: StoreRuntime, job_id: str) -> StoredJob | None:
    """Fetch a persisted job by id."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
    if row is None:
        return None
    return _stored_job_from_row(row)


async def update_job_status_message(runtime: StoreRuntime, job_id: str, message: str) -> None:
    """Update the status_message field on a job for in-flight progress visibility."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
        if row is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        row.status_message = message
        session.add(row)
        await session.commit()


async def mark_job_running(runtime: StoreRuntime, job_id: str) -> None:
    """Transition an existing job to running."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
        if row is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        row.status = "running"
        row.started_at = _utc_now_iso()
        row.error = None
        row.status_message = "[stage:queued] starting"
        row.warning_payload_json = None
        session.add(row)
        await session.commit()


async def mark_job_completed(
    runtime: StoreRuntime,
    job_id: str,
    extraction_id: str,
    *,
    status_message: str = "[stage:completed] extraction_complete",
) -> None:
    """Transition an existing job to completed with extraction id."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
        if row is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        row.status = "completed"
        row.completed_at = _utc_now_iso()
        row.extraction_id = extraction_id
        row.error = None
        row.status_message = status_message
        row.warning_payload_json = None
        session.add(row)
        await session.commit()


async def mark_job_completed_with_warnings(
    runtime: StoreRuntime,
    job_id: str,
    extraction_id: str,
    warning_payload: JobWarningPayload,
    *,
    status_message: str = "[stage:completed_with_warnings] extraction_complete",
) -> None:
    """Transition an existing job to completed_with_warnings with warning payload."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
        if row is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        row.status = "completed_with_warnings"
        row.completed_at = _utc_now_iso()
        row.extraction_id = extraction_id
        row.error = None
        row.status_message = status_message
        row.warning_payload_json = json.dumps(
            warning_payload.model_dump(mode="json"),
            ensure_ascii=False,
        )
        session.add(row)
        await session.commit()


async def mark_job_failed(
    runtime: StoreRuntime,
    job_id: str,
    error: str,
    warning_payload: JobWarningPayload | None = None,
    *,
    status_message: str | None = None,
) -> None:
    """Transition an existing job to failed with error details."""
    async with runtime.session() as session:
        row = (await session.exec(select(JobRow).where(JobRow.id == job_id))).first()
        if row is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        row.status = "failed"
        row.completed_at = _utc_now_iso()
        row.error = error
        row.status_message = status_message or f"[stage:failed] {error}"
        row.warning_payload_json = (
            json.dumps(warning_payload.model_dump(mode="json"), ensure_ascii=False)
            if warning_payload is not None
            else None
        )
        session.add(row)
        await session.commit()
