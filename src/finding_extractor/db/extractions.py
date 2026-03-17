"""Extraction persistence helpers and shared read-model conversion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import col, select

from finding_extractor.coding_summary import inline_coding_counts
from finding_extractor.db.engine import StoreRuntime
from finding_extractor.db.tables import ExtractionRow
from finding_extractor.models import (
    ExtractedReportFindings,
    ExtractionUsage,
    PipelineDiagnostics,
    ValidationResult,
)
from finding_extractor.read_models import ExtractionDetail, ExtractionSummary


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _usage_from_row(row: ExtractionRow) -> ExtractionUsage | None:
    if row.input_tokens is None and row.output_tokens is None:
        return None
    details: dict[str, int] = {}
    if row.usage_details_json:
        details = json.loads(row.usage_details_json)
    return ExtractionUsage(
        requests=row.model_requests or 0,
        input_tokens=row.input_tokens or 0,
        output_tokens=row.output_tokens or 0,
        cache_read_tokens=row.cache_read_tokens or 0,
        cache_write_tokens=row.cache_write_tokens or 0,
        duration_ms=row.duration_ms,
        details=details,
    )


def _coding_counts_from_extraction(
    extraction: ExtractedReportFindings,
) -> tuple[int | None, int | None]:
    return inline_coding_counts(extraction)


def _diagnostics_from_row(row: ExtractionRow) -> PipelineDiagnostics | None:
    if row.diagnostics_json is None:
        return None
    return PipelineDiagnostics.model_validate(json.loads(row.diagnostics_json))


def _extraction_summary_from_row(row: ExtractionRow) -> ExtractionSummary:
    return ExtractionSummary(
        id=row.id,
        report_id=row.report_id,
        model_name=row.model_name,
        reasoning_effort=row.reasoning_effort,
        created_at=row.created_at,
        study_description=row.study_description,
        modality=row.modality,
        body_region=row.body_region,
        body_part=row.body_part,
        contrast=row.contrast,
        laterality=row.laterality,
        finding_count=row.finding_count,
        usage=_usage_from_row(row),
        coded_finding_count=row.coded_finding_count,
        unresolved_finding_count=row.unresolved_finding_count,
    )


def _extraction_detail_from_row(
    row: ExtractionRow,
    *,
    extraction: ExtractedReportFindings,
    validation_result: ValidationResult | None,
) -> ExtractionDetail:
    return ExtractionDetail(
        id=row.id,
        report_id=row.report_id,
        model_name=row.model_name,
        reasoning_effort=row.reasoning_effort,
        study_description_hint=row.study_description_hint,
        created_at=row.created_at,
        extraction=extraction,
        validation_result=validation_result,
        usage=_usage_from_row(row),
        pipeline_diagnostics=_diagnostics_from_row(row),
        trace_id=row.trace_id,
    )


async def create_extraction(
    runtime: StoreRuntime,
    *,
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
    """Persist one extraction run payload."""
    created_at = _utc_now_iso()
    extraction_id = str(uuid4())
    extraction_json = json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False)
    validation_json = (
        json.dumps(validation_result.model_dump(mode="json"), ensure_ascii=False)
        if validation_result is not None
        else None
    )

    usage_details_json: str | None = None
    if usage is not None and usage.details:
        usage_details_json = json.dumps(usage.details, ensure_ascii=False)

    diagnostics_json: str | None = None
    if pipeline_diagnostics is not None:
        diagnostics_json = json.dumps(
            pipeline_diagnostics.model_dump(mode="json"), ensure_ascii=False
        )

    coded, unresolved = _coding_counts_from_extraction(extraction)

    async with runtime.session() as session:
        extraction_row = ExtractionRow(
            id=extraction_id,
            report_id=report_id,
            created_at=created_at,
            model_name=model_name,
            reasoning_effort=reasoning_effort,
            study_description_hint=study_description_hint,
            study_description=extraction.exam_info.study_description,
            study_date=(
                extraction.exam_info.study_date.isoformat()
                if extraction.exam_info.study_date is not None
                else None
            ),
            modality=extraction.exam_info.modality,
            body_region=extraction.exam_info.body_region,
            body_part=extraction.exam_info.body_part,
            contrast=extraction.exam_info.contrast,
            laterality=extraction.exam_info.laterality,
            finding_count=len(extraction.findings),
            coded_finding_count=coded,
            unresolved_finding_count=unresolved,
            diagnostics_json=diagnostics_json,
            trace_id=trace_id,
            extraction_json=extraction_json,
            validation_json=validation_json,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
            cache_write_tokens=usage.cache_write_tokens if usage else None,
            model_requests=usage.requests if usage else None,
            duration_ms=usage.duration_ms if usage else None,
            usage_details_json=usage_details_json,
        )
        session.add(extraction_row)
        await session.commit()

    return _extraction_summary_from_row(extraction_row)


async def get_extraction(
    runtime: StoreRuntime, extraction_id: str
) -> ExtractionDetail | None:
    """Fetch one extraction with deserialized JSON payloads."""
    async with runtime.session() as session:
        row = (await session.exec(select(ExtractionRow).where(ExtractionRow.id == extraction_id))).first()
    if row is None:
        return None

    extraction_payload = ExtractedReportFindings.model_validate(json.loads(row.extraction_json))
    validation_payload = (
        ValidationResult.model_validate(json.loads(row.validation_json))
        if row.validation_json is not None
        else None
    )
    return _extraction_detail_from_row(
        row,
        extraction=extraction_payload,
        validation_result=validation_payload,
    )


async def list_extractions(runtime: StoreRuntime, report_id: str) -> list[ExtractionSummary]:
    """List extraction summaries for a report."""
    async with runtime.session() as session:
        rows = (
            await session.exec(
                select(ExtractionRow)
                .where(ExtractionRow.report_id == report_id)
                .order_by(col(ExtractionRow.created_at).desc(), col(ExtractionRow.id).desc())
            )
        ).all()
    return [_extraction_summary_from_row(row) for row in rows]


async def update_extraction_coding(
    runtime: StoreRuntime,
    *,
    extraction_id: str,
    extraction: ExtractedReportFindings,
    coding_model: str,
    coding_reasoning: str | None,
    coding_duration_ms: int | None,
    coding_trace_id: str | None,
) -> ExtractionDetail:
    """Persist inline coding updates back onto an existing extraction row."""

    async with runtime.session() as session:
        row = (await session.exec(select(ExtractionRow).where(ExtractionRow.id == extraction_id))).first()
        if row is None:
            raise ValueError(f"Unknown extraction_id: {extraction_id}")

        row.extraction_json = json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False)
        coded, unresolved = _coding_counts_from_extraction(extraction)
        row.coded_finding_count = coded
        row.unresolved_finding_count = unresolved
        row.coding_model = coding_model
        row.coding_reasoning = coding_reasoning
        row.coding_completed_at = _utc_now_iso()
        row.coding_duration_ms = coding_duration_ms
        row.coding_trace_id = coding_trace_id
        session.add(row)
        await session.commit()

    validation_payload = (
        ValidationResult.model_validate(json.loads(row.validation_json))
        if row.validation_json is not None
        else None
    )
    return _extraction_detail_from_row(
        row,
        extraction=extraction,
        validation_result=validation_payload,
    )


async def get_finding_path(
    runtime: StoreRuntime, extraction_id: str, finding_index: int
) -> str | None:
    """Return JSON path for a finding index if it exists in extraction payload."""
    async with runtime.session() as session:
        row = (await session.exec(select(ExtractionRow).where(ExtractionRow.id == extraction_id))).first()
        if row is None:
            return None
        payload = json.loads(row.extraction_json)

    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        return None
    if finding_index < 0 or finding_index >= len(findings):
        return None
    return f"$.findings[{finding_index}]"
