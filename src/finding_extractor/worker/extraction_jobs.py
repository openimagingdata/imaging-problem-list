"""TaskIQ tasks for background extraction processing."""

from typing import Annotated

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from taskiq import TaskiqDepends

from finding_extractor.core.config import get_settings
from finding_extractor.db.store import ExtractionStore
from finding_extractor.extractor.agent import (
    extract_chunk_findings,
    validate_extraction,
)
from finding_extractor.extractor.progress import format_stage_status
from finding_extractor.extractor.runtime import (
    ReliabilityContractError,
    run_extraction_runtime,
)
from finding_extractor.models import (
    JobWarningPayload,
    ReliabilityMode,
)
from finding_extractor.worker.broker import broker
from finding_extractor.worker.job_utils import (
    get_task_store,
)
from finding_extractor.worker.job_utils import (
    to_public_job_error as _to_public_job_error,
)

logger = structlog.get_logger(__name__)


def to_public_job_error(exc: Exception) -> str:
    """Return a stable, non-sensitive job error string for extraction responses."""
    return _to_public_job_error(exc, job_name="extraction")


def _log_reliability_contract_outcome(
    *,
    terminal_status: str,
    reliability_mode: ReliabilityMode,
    warning_payload: JobWarningPayload,
    public_error: str | None = None,
) -> None:
    logger.info(
        "Reliability contract outcome",
        terminal_status=terminal_status,
        reliability_mode=reliability_mode,
        public_error=public_error,
        reason_categories=list(warning_payload.reason_categories),
        dropped_findings_count=warning_payload.dropped_findings_count,
        dropped_non_finding_count=warning_payload.dropped_non_finding_count,
        validation_error_count=warning_payload.validation_error_count,
        coverage_warning_count=warning_payload.coverage_warning_count,
        section_failure_count=warning_payload.section_failure_count,
    )


async def _run_extraction_impl(
    job_id: str,
    report_id: str,
    store: ExtractionStore,
    model: str | None = None,
    reasoning: str | None = None,
    study_description: str | None = None,
    reliability_mode: ReliabilityMode = "strict",
    validate: bool = True,
) -> dict[str, str]:
    """Core extraction logic shared by default and test brokers."""
    clear_contextvars()
    bind_contextvars(job_id=job_id, report_id=report_id)
    try:
        logger.info("Extraction task started", model=model, validate=validate)
        await store.mark_job_running(job_id)

        await store.update_job_status_message(
            job_id,
            format_stage_status("preflight", "retrieving_report"),
        )
        report = await store.get_report(report_id)
        if report is None:
            raise ValueError(f"Unknown report_id: {report_id}")

        async def _status_cb(message: str) -> None:
            logger.debug("Extraction task status update", status_message=message)
            await store.update_job_status_message(job_id, message)

        settings = get_settings()

        result = await run_extraction_runtime(
            report_text=report.report_text,
            study_description=study_description,
            model=model,
            reasoning=reasoning,
            validate=validate,
            reliability_mode=reliability_mode,
            store=store,
            db_path=store.db_path,
            source_ref=report.source_ref,
            report_id=report_id,
            progress_callback=_status_cb,
            settings=settings,
            extract_findings_fn=extract_chunk_findings,
            validate_extraction_fn=validate_extraction,
        )
        logger.info(
            "Extraction runtime complete",
            model_name=result.model_name,
            findings_count=len(result.extraction.findings),
            non_finding_count=len(result.extraction.non_finding_text),
        )
        pipeline_diagnostics = result.pipeline_diagnostics
        section_failure_count = pipeline_diagnostics.remaining_failed_chunks
        if pipeline_diagnostics.mode in {"modular", "v2"}:
            logger.info(
                "Orchestrator pipeline diagnostics",
                total_chunks=pipeline_diagnostics.total_chunks,
                initial_failed_chunks=pipeline_diagnostics.initial_failed_chunks,
                remaining_failed_chunks=pipeline_diagnostics.remaining_failed_chunks,
                total_chunk_attempts=pipeline_diagnostics.total_chunk_attempts,
                failed_chunk_ids=list(pipeline_diagnostics.failed_chunk_ids),
                failed_chunk_error_types=list(pipeline_diagnostics.failed_chunk_error_types),
                reviewer_requested_chunks=pipeline_diagnostics.reviewer_requested_chunks,
                reviewer_reextracted_chunks=pipeline_diagnostics.reviewer_reextracted_chunks,
            )
            if section_failure_count > 0:
                logger.warning(
                    "Modular extraction has unrecovered failed chunks",
                    reliability_mode=reliability_mode,
                    remaining_failed_chunks=section_failure_count,
                    failed_chunk_ids=list(pipeline_diagnostics.failed_chunk_ids),
                    failed_chunk_error_types=list(pipeline_diagnostics.failed_chunk_error_types),
                )
        warning_payload = result.warning_payload
        storage_metadata = result.storage_metadata
        if storage_metadata is None:
            raise RuntimeError("Runtime returned without persistence metadata for worker run")
        if warning_payload is None:
            await store.mark_job_completed(job_id, extraction_id=storage_metadata.extraction_id)
        else:
            _log_reliability_contract_outcome(
                terminal_status="completed_with_warnings",
                reliability_mode=reliability_mode,
                warning_payload=warning_payload,
            )
            await store.mark_job_completed_with_warnings(
                job_id,
                extraction_id=storage_metadata.extraction_id,
                warning_payload=warning_payload,
            )
        logger.info(
            "Extraction task completed",
            extraction_id=storage_metadata.extraction_id,
            model_name=result.model_name,
            warning_payload=(
                warning_payload.model_dump(mode="json") if warning_payload is not None else None
            ),
        )
        return {
            "extraction_id": storage_metadata.extraction_id,
            "model_name": result.model_name,
        }
    except Exception as exc:
        warning_payload = None
        if isinstance(exc, ReliabilityContractError):
            public_error = exc.public_error
            warning_payload = exc.warning_payload
            _log_reliability_contract_outcome(
                terminal_status="failed",
                reliability_mode=reliability_mode,
                warning_payload=warning_payload,
                public_error=public_error,
            )
        else:
            public_error = to_public_job_error(exc)
        if public_error in {
            "extraction_failed:model_provider_error",
            "extraction_failed:model_timeout",
        }:
            logger.warning(
                "Extraction task failed with retryable provider error",
                public_error=public_error,
            )
        else:
            logger.exception("Extraction task failed", public_error=public_error)
        try:
            await store.update_job_status_message(
                job_id,
                format_stage_status("failed", public_error),
            )
            await store.mark_job_failed(
                job_id,
                error=public_error,
                warning_payload=warning_payload,
            )
        except ValueError:
            logger.warning(
                "Failed to persist failed job state",
                job_id=job_id,
                public_error=public_error,
                exc_info=True,
            )
        raise
    finally:
        clear_contextvars()


def register_run_extraction_task(task_broker):
    """Bind the extraction task to a broker instance."""

    @task_broker.task(task_name="run_extraction")
    async def _run_extraction_task(
        job_id: str,
        report_id: str,
        model: str | None = None,
        reasoning: str | None = None,
        study_description: str | None = None,
        reliability_mode: ReliabilityMode = "strict",
        validate: bool = True,
        *,
        store: Annotated[ExtractionStore, TaskiqDepends(get_task_store)],
    ) -> dict[str, str]:
        return await _run_extraction_impl(
            job_id=job_id,
            report_id=report_id,
            store=store,
            model=model,
            reasoning=reasoning,
            study_description=study_description,
            reliability_mode=reliability_mode,
            validate=validate,
        )

    return _run_extraction_task


run_extraction = register_run_extraction_task(broker)
