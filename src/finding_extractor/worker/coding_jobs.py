"""TaskIQ tasks for background coding processing."""

from __future__ import annotations

from typing import Annotated

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from taskiq import TaskiqDepends

from finding_extractor.coding.runtime import run_coding
from finding_extractor.core.config import get_settings
from finding_extractor.db.store import ExtractionStore
from finding_extractor.extractor.progress import format_stage_status
from finding_extractor.worker.broker import broker
from finding_extractor.worker.job_utils import (
    get_task_store,
)
from finding_extractor.worker.job_utils import (
    to_public_job_error as _to_public_job_error,
)

logger = structlog.get_logger(__name__)


def to_public_job_error(exc: Exception) -> str:
    """Return a stable, non-sensitive job error string for coding responses."""
    return _to_public_job_error(exc, job_name="coding")


async def _run_coding_impl(
    job_id: str,
    extraction_id: str,
    store: ExtractionStore,
    model: str | None = None,
    reasoning: str | None = None,
) -> dict[str, str]:
    clear_contextvars()
    bind_contextvars(job_id=job_id, extraction_id=extraction_id)
    try:
        extraction_detail = await store.get_extraction(extraction_id)
        if extraction_detail is None:
            raise ValueError(f"Unknown extraction_id: {extraction_id}")
        bind_contextvars(report_id=extraction_detail.report_id)
        logger.info("Coding task started", model=model)
        await store.mark_job_running(job_id)

        async def _status_cb(message: str) -> None:
            logger.debug("Coding task status update", status_message=message)
            await store.update_job_status_message(job_id, message)

        settings = get_settings()
        result = await run_coding(
            extraction_detail.extraction,
            model=model,
            reasoning=reasoning,
            settings=settings,
            progress_callback=_status_cb,
            store=store,
            extraction_id=extraction_id,
            report_id=extraction_detail.report_id,
            job_id=job_id,
        )
        await store.mark_job_completed(
            job_id,
            extraction_id,
            status_message=format_stage_status("coding_complete", "coding_complete"),
        )
        logger.info(
            "Coding task completed",
            extraction_id=extraction_id,
            coded_findings=result.coded_finding_count,
            unresolved_findings=result.unresolved_finding_count,
        )
        return {
            "extraction_id": extraction_id,
            "model_name": result.model_name,
        }
    except Exception as exc:
        public_error = to_public_job_error(exc)
        if public_error in {
            "coding_failed:model_provider_error",
            "coding_failed:model_timeout",
        }:
            logger.warning("Coding task failed with retryable provider error", public_error=public_error)
        else:
            logger.exception("Coding task failed", public_error=public_error)
        try:
            await store.mark_job_failed(
                job_id,
                error=public_error,
                status_message=format_stage_status("coding_failed", public_error),
            )
        except ValueError:
            logger.warning(
                "Failed to persist failed coding job state",
                job_id=job_id,
                public_error=public_error,
                exc_info=True,
            )
        raise
    finally:
        clear_contextvars()


def register_run_coding_task(task_broker):
    """Bind the coding task to a broker instance."""

    @task_broker.task(task_name="run_coding")
    async def _run_coding_task(
        job_id: str,
        extraction_id: str,
        model: str | None = None,
        reasoning: str | None = None,
        *,
        store: Annotated[ExtractionStore, TaskiqDepends(get_task_store)],
    ) -> dict[str, str]:
        return await _run_coding_impl(
            job_id=job_id,
            extraction_id=extraction_id,
            store=store,
            model=model,
            reasoning=reasoning,
        )

    return _run_coding_task


run_coding_task = register_run_coding_task(broker)
