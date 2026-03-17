"""Tests for FastAPI server endpoints and async extraction dispatch."""

from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
import taskiq_fastapi
from httpx import ASGITransport, AsyncClient
from structlog.contextvars import get_contextvars
from taskiq import InMemoryBroker

from finding_extractor.api import create_app
from finding_extractor.coding.runtime import CodingRunResult
from finding_extractor.core.config import ExtractorSettings
from finding_extractor.db.store import ExtractionStore
from finding_extractor.llm.catalog import CatalogModel, ModelCatalog
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    ExtractionUsage,
    Finding,
    FindingAttribute,
    FindingCode,
    FindingCodingBundle,
    FindingLocation,
    LocationCode,
    PipelineDiagnostics,
    ValidationResult,
)
from finding_extractor.read_models import ReportDetail, ReportSummary


@pytest_asyncio.fixture
async def store(tmp_path: Path, store_factory):
    """Create a temporary SQLite-backed store for API tests."""
    async with store_factory(tmp_path / "api.sqlite3") as s:
        yield s


@pytest.fixture
def broker() -> InMemoryBroker:
    """In-memory TaskIQ broker for deterministic tests."""
    return InMemoryBroker(await_inplace=True)


@pytest_asyncio.fixture
async def app(store: ExtractionStore, broker: InMemoryBroker):
    """Create FastAPI app wired to temp store + in-memory broker."""
    app = create_app(store=store, broker=broker)
    taskiq_fastapi.populate_dependency_context(broker, app)
    try:
        yield app
    finally:
        broker.custom_dependency_context = {}


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client over ASGI transport."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c,
    ):
        yield c


def _fake_extraction(
    study_description: str = "Chest XR",
    finding_text: str = "No pleural effusion.",
) -> ExtractedReportFindings:
    """Stable extraction payload used in API tests."""
    return ExtractedReportFindings(
        exam_info=ExamInfo(study_description=study_description, modality="XR", body_part="chest"),
        findings=[
            Finding(
                finding_name="pleural effusion",
                presence="absent",
                report_text=finding_text,
            )
        ],
        non_finding_text=[],
    )


def _settings_for_test(**overrides) -> ExtractorSettings:
    """Build a typed settings object for API tests."""
    return ExtractorSettings.model_construct(
        db_path=Path(".finding_extractor.db"),
        redis_url="redis://localhost:6379",
        default_model="openai:gpt-5-mini",
        **overrides,
    )


def test_create_app_wires_logging_setup(monkeypatch, broker: InMemoryBroker, runtime_logging_spy):
    """App creation should configure logfire first, then structured logging."""
    runtime_logging_spy.patch(
        monkeypatch,
        "finding_extractor.api",
        logfire_enabled=True,
    )

    app = create_app(broker=broker)

    assert len(runtime_logging_spy.configure_calls) == 1
    assert len(runtime_logging_spy.setup_calls) == 1
    assert runtime_logging_spy.configure_calls[0]["runtime"] == "api"
    assert runtime_logging_spy.configure_calls[0]["enabled_override"] is None
    assert runtime_logging_spy.configure_calls[0]["fastapi_app"] is app
    assert runtime_logging_spy.setup_calls[0]["include_logfire_processor"] is True
    assert runtime_logging_spy.setup_calls[0]["settings"] is not None


@pytest.mark.asyncio
async def test_api_startup_fails_fast_on_unmigrated_db(
    tmp_path: Path,
    broker: InMemoryBroker,
) -> None:
    """API startup should reject an unstamped DB before bootstrapping app tables."""
    store = ExtractionStore(tmp_path / "unmigrated.sqlite3")
    app = create_app(store=store, broker=broker)
    taskiq_fastapi.populate_dependency_context(broker, app)

    try:
        with pytest.raises(RuntimeError, match="task db:migrate"):
            async with app.router.lifespan_context(app):
                pass

        async with store.engine.connect() as conn:
            rows = (
                await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        table_names = {row[0] for row in rows}
        assert "reports" not in table_names
        assert "alembic_version" not in table_names
    finally:
        broker.custom_dependency_context = {}
        await store.close()


@pytest.mark.asyncio
async def test_request_context_middleware_binds_request_keys(
    store: ExtractionStore, broker: InMemoryBroker, monkeypatch, context_capture_logger
):
    """Request middleware should bind request-scoped IDs/HTTP keys and clear context."""
    monkeypatch.setattr("finding_extractor.api.logger", context_capture_logger)
    monkeypatch.setattr("finding_extractor.api._get_active_trace_context", lambda: {})

    app = create_app(store=store, broker=broker)
    taskiq_fastapi.populate_dependency_context(broker, app)

    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client,
        ):
            response = await client.get("/api/healthz")
    finally:
        broker.custom_dependency_context = {}

    assert response.status_code == 200
    request_logs = [
        record
        for record in context_capture_logger.records
        if record["event"] in {"API request started", "API request completed"}
    ]
    assert len(request_logs) == 2
    request_ids = {record["context"]["request_id"] for record in request_logs}
    assert len(request_ids) == 1
    for record in request_logs:
        context = record["context"]
        assert context["http_method"] == "GET"
        assert context["http_path"] == "/api/healthz"
        assert "trace_id" not in context
        assert "span_id" not in context
    assert get_contextvars() == {}


@pytest.mark.asyncio
async def test_request_context_middleware_binds_trace_and_span_when_available(
    store: ExtractionStore, broker: InMemoryBroker, monkeypatch, context_capture_logger
):
    """Trace/span context should be bound from active OpenTelemetry span context."""
    from opentelemetry.trace import (
        NonRecordingSpan,
        SpanContext,
        TraceFlags,
        TraceState,
        use_span,
    )

    expected_trace_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    expected_span_id = "bbbbbbbbbbbbbbbb"
    span_context = SpanContext(
        trace_id=int(expected_trace_id, 16),
        span_id=int(expected_span_id, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )

    monkeypatch.setattr("finding_extractor.api.logger", context_capture_logger)

    app = create_app(store=store, broker=broker)
    taskiq_fastapi.populate_dependency_context(broker, app)

    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client,
        ):
            with use_span(NonRecordingSpan(span_context), end_on_exit=False):
                response = await client.get("/api/healthz")
    finally:
        broker.custom_dependency_context = {}

    assert response.status_code == 200
    request_logs = [
        record
        for record in context_capture_logger.records
        if record["event"] in {"API request started", "API request completed"}
    ]
    assert len(request_logs) == 2
    for record in request_logs:
        context = record["context"]
        assert context["trace_id"] == expected_trace_id
        assert context["span_id"] == expected_span_id
    assert get_contextvars() == {}


@pytest.mark.asyncio
async def test_healthz_and_readyz(client: AsyncClient):
    """Health/readiness probes should return healthy status payloads."""
    health = await client.get("/api/healthz")
    ready = await client.get("/api/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_report_endpoints_return_shared_read_models(
    store: ExtractionStore, client: AsyncClient
):
    """Report endpoints keep the same JSON contract while using shared read models."""
    created = await store.upsert_report("Findings:\nNo pleural effusion.", source_ref="seed-1")
    assert isinstance(created, ReportSummary)

    listed = await client.get("/api/reports")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == created.id
    assert listed.json()[0]["seen_before"] is False

    detail = await client.get(f"/api/reports/{created.id}")
    assert detail.status_code == 200
    assert ReportDetail.model_validate(detail.json()).id == created.id


@pytest.mark.asyncio
async def test_models_endpoint_returns_catalog_payload(app, client: AsyncClient, monkeypatch):
    """`GET /api/models` should return the model catalog contract."""

    async def fake_get_catalog() -> ModelCatalog:
        return ModelCatalog(
            updated_at="2026-02-10T00:00:00Z",
            stale=False,
            refresh_interval_seconds=172800,
            models=[
                CatalogModel(
                    id="openai:gpt-5",
                    provider="openai",
                    tier="base",
                    is_default=True,
                    supported_reasoning=["high", "low", "medium", "minimal", "none"],
                    default_reasoning="medium",
                ),
                CatalogModel(
                    id="openai:gpt-5-mini",
                    provider="openai",
                    tier="mini",
                    is_default=False,
                    supported_reasoning=["high", "low", "medium", "minimal", "none"],
                    default_reasoning="medium",
                ),
            ],
        )

    monkeypatch.setattr(app.state.model_catalog, "get_catalog", fake_get_catalog)

    response = await client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == {
        "updated_at": "2026-02-10T00:00:00Z",
        "stale": False,
        "refresh_interval_seconds": 172800,
        "models": [
            {
                "id": "openai:gpt-5",
                "provider": "openai",
                "tier": "base",
                "is_default": True,
                "supported_reasoning": ["high", "low", "medium", "minimal", "none"],
                "default_reasoning": "medium",
            },
            {
                "id": "openai:gpt-5-mini",
                "provider": "openai",
                "tier": "mini",
                "is_default": False,
                "supported_reasoning": ["high", "low", "medium", "minimal", "none"],
                "default_reasoning": "medium",
            },
        ],
    }


@pytest.mark.asyncio
async def test_readyz_returns_503_when_broker_backend_is_unavailable(
    client: AsyncClient, monkeypatch
):
    """Readiness should fail when queue backend connectivity checks fail."""

    async def fake_assert_broker_ready(*args, **kwargs):
        _ = (args, kwargs)
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("finding_extractor.api.routes._assert_broker_ready", fake_assert_broker_ready)

    ready = await client.get("/api/readyz")
    assert ready.status_code == 503
    assert ready.json()["detail"] == "Not ready"


@pytest.mark.asyncio
async def test_report_submit_and_dedupe(client: AsyncClient):
    """POST /api/reports upserts by text hash and toggles seen_before."""
    payload = {"report_text": "No pleural effusion.", "source_ref": "report-a.txt"}
    first = await client.post("/api/reports", json=payload)
    second = await client.post("/api/reports", json={"report_text": "No pleural effusion."})

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["id"] == second_body["id"]
    assert first_body["seen_before"] is False
    assert second_body["seen_before"] is True


@pytest.mark.asyncio
async def test_report_list_and_detail(client: AsyncClient):
    """GET report list/detail returns persisted report content."""
    created = await client.post("/api/reports", json={"report_text": "Technique: CT."})
    report_id = created.json()["id"]

    listed = await client.get("/api/reports")
    detail = await client.get(f"/api/reports/{report_id}")

    assert listed.status_code == 200
    assert any(item["id"] == report_id for item in listed.json())
    assert detail.status_code == 200
    assert detail.json()["report_text"] == "Technique: CT."


@pytest.mark.asyncio
async def test_report_detail_not_found(client: AsyncClient):
    """GET /api/reports/{id} returns 404 for missing report."""
    response = await client.get("/api/reports/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_extract_dispatch_job_and_extraction_reads(client: AsyncClient, monkeypatch):
    """Dispatch endpoint creates job and extraction rows, then read endpoints return them."""
    from finding_extractor.models import ExtractionResult

    async def fake_extract_findings(
        report_text,
        study_description=None,
        model=None,
        reasoning=None,
        *,
        section_name="findings",
        preceding_chunk_context=None,
        following_chunk_context=None,
        feedback=None,
        progress_callback=None,
    ):
        _ = (
            report_text,
            study_description,
            model,
            reasoning,
            section_name,
            preceding_chunk_context,
            following_chunk_context,
            feedback,
        )
        return ExtractionResult(report_findings=_fake_extraction("Chest XR"), usage=None)

    monkeypatch.setattr("finding_extractor.worker.extraction_jobs.extract_chunk_findings", fake_extract_findings)

    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    dispatch = await client.post(f"/api/reports/{report_id}/extract", json={})
    assert dispatch.status_code == 202
    assert dispatch.headers["Location"].startswith("/api/jobs/")
    job_id = dispatch.json()["job_id"]

    job = await client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] in {"pending", "running", "completed"}

    # await_inplace=True should complete this quickly.
    job_final = await client.get(f"/api/jobs/{job_id}")
    assert job_final.status_code == 200
    assert job_final.json()["status"] == "completed"
    extraction_id = job_final.json()["extraction_id"]
    assert extraction_id is not None

    extractions = await client.get(f"/api/reports/{report_id}/extractions")
    assert extractions.status_code == 200
    assert len(extractions.json()) == 1
    assert extractions.json()[0]["id"] == extraction_id

    extraction_detail = await client.get(f"/api/extractions/{extraction_id}")
    assert extraction_detail.status_code == 200
    assert (
        extraction_detail.json()["extraction"]["findings"][0]["finding_name"] == "pleural effusion"
    )


@pytest.mark.asyncio
async def test_extract_dispatch_not_found(client: AsyncClient):
    """POST /api/reports/{id}/extract returns 404 for unknown report."""
    response = await client.post("/api/reports/missing/extract", json={})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_code_dispatch_job_and_extraction_reads(
    store: ExtractionStore,
    client: AsyncClient,
    monkeypatch,
):
    """Coding dispatch endpoint creates a job and updates the target extraction in place."""

    async def fake_run_coding(
        extraction,
        *,
        model=None,
        reasoning=None,
        settings=None,
        progress_callback=None,
        store=None,
        extraction_id=None,
        report_id=None,
        job_id=None,
    ):
        _ = (model, reasoning, settings, report_id, job_id)
        if progress_callback is not None:
            await progress_callback("[stage:coding_selection] selecting_codes_1_of_1")
        updated = extraction.model_copy(
            update={
                "findings": [
                    extraction.findings[0].model_copy(
                        update={
                            "coding": FindingCodingBundle(
                                finding_code=FindingCode(
                                    status="coded",
                                    oifm_id="OIFM:123",
                                    oifm_name="pleural effusion",
                                    method="llm",
                                    reasoning="Matched the only candidate.",
                                ),
                                location_codes=[],
                            )
                        }
                    )
                ]
            }
        )
        assert store is not None
        assert extraction_id is not None
        await store.update_extraction_coding(
            extraction_id=extraction_id,
            extraction=updated,
            coding_model="openai:gpt-5.2",
            coding_reasoning="low",
            coding_duration_ms=12,
            coding_trace_id=None,
        )
        return CodingRunResult(
            extraction=updated,
            model_name="openai:gpt-5.2",
            reasoning_effort="low",
            duration_ms=12,
            coded_finding_count=1,
            unresolved_finding_count=0,
            trace_id=None,
        )

    monkeypatch.setattr("finding_extractor.worker.coding_jobs.run_coding", fake_run_coding)

    report = await store.upsert_report("Findings:\nNo pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    dispatch = await client.post(f"/api/extractions/{extraction.id}/code", json={})
    assert dispatch.status_code == 202
    assert dispatch.headers["Location"].startswith("/api/jobs/")
    job_id = dispatch.json()["job_id"]
    assert dispatch.json()["extraction_id"] == extraction.id

    job_final = await client.get(f"/api/jobs/{job_id}")
    assert job_final.status_code == 200
    assert job_final.json()["status"] == "completed"
    assert job_final.json()["extraction_id"] == extraction.id
    assert job_final.json()["status_event"] == {
        "version": "v2",
        "stage": "coding_complete",
        "detail": "coding_complete",
    }

    extraction_detail = await client.get(f"/api/extractions/{extraction.id}")
    assert extraction_detail.status_code == 200
    coding = extraction_detail.json()["extraction"]["findings"][0]["coding"]
    assert coding["finding_code"]["oifm_id"] == "OIFM:123"
    assert coding["finding_code"]["method"] == "llm"


@pytest.mark.asyncio
async def test_code_dispatch_not_found(client: AsyncClient):
    """POST /api/extractions/{id}/code returns 404 for unknown extraction."""
    response = await client.post("/api/extractions/missing/code", json={})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_extract_dispatch_rejects_disallowed_model_prefix(client: AsyncClient):
    """POST /api/reports/{id}/extract returns 422 for policy-disallowed model ids."""
    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    response = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"model": "google-vertex:gemini-3-pro"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "google-vertex models are not allowed; use google-gla:*"


@pytest.mark.asyncio
async def test_extract_dispatch_enqueue_failure_marks_job_failed(
    app,
    client: AsyncClient,
    monkeypatch,
):
    """Enqueue failures should return 503 and mark job as failed (not stuck pending)."""

    async def fail_kiq(*args, **kwargs):
        _ = (args, kwargs)
        raise RuntimeError("queue down")

    report = await client.post("/api/reports", json={"report_text": "No focal consolidation."})
    report_id = report.json()["id"]

    monkeypatch.setattr(app.state.run_extraction_task, "kiq", fail_kiq)
    monkeypatch.setattr(
        "finding_extractor.api.services.uuid4",
        lambda: UUID("00000000-0000-0000-0000-000000000123"),
    )

    dispatch = await client.post(f"/api/reports/{report_id}/extract", json={})
    assert dispatch.status_code == 503

    job = await client.get("/api/jobs/00000000-0000-0000-0000-000000000123")
    assert job.status_code == 200
    assert job.json()["status"] == "failed"
    assert job.json()["error"] == "enqueue_failed:queue_unavailable"


@pytest.mark.asyncio
async def test_job_not_found(client: AsyncClient):
    """GET /api/jobs/{id} returns 404 for unknown job."""
    response = await client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_extraction_detail_not_found(client: AsyncClient):
    """GET /api/extractions/{id} returns 404 when extraction is absent."""
    response = await client.get("/api/extractions/missing")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_and_list_corrections(store: ExtractionStore, client: AsyncClient):
    """Correction create/list endpoints persist and return correction rows."""
    # Seed user for correction attribution
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    create_payload = {
        "correction_type": "comment",
        "comment": "Looks good",
        "username": "talkasab",
    }
    created = await client.post(
        f"/api/extractions/{extraction.id}/corrections",
        json=create_payload,
    )
    listed = await client.get(f"/api/extractions/{extraction.id}/corrections")

    assert created.status_code == 201
    assert created.json()["comment"] == "Looks good"
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["correction_type"] == "comment"
    assert listed.json()[0]["comment"] == "Looks good"


@pytest.mark.asyncio
async def test_create_update_correction_invalid_index_returns_422(
    store: ExtractionStore, client: AsyncClient
):
    """Update correction returns 422 when target_finding_index is out of range."""
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    create = await client.post(
        f"/api/extractions/{extraction.id}/corrections",
        json={
            "correction_type": "update_finding",
            "target_finding_index": 7,
            "attribute_overrides": {"severity": "mild"},
            "username": "talkasab",
        },
    )
    assert create.status_code == 422
    assert (
        create.json()["detail"]
        == "update_finding target_finding_index does not exist in extraction findings"
    )

    listed = await client.get(f"/api/extractions/{extraction.id}/corrections")
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_corrections_not_found(store: ExtractionStore, client: AsyncClient):
    """Correction endpoints return 404 for unknown extraction ids."""
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    create = await client.post(
        "/api/extractions/missing/corrections",
        json={"correction_type": "comment", "comment": "test", "username": "talkasab"},
    )
    listed = await client.get("/api/extractions/missing/corrections")
    assert create.status_code == 404
    assert listed.status_code == 404


@pytest.mark.asyncio
async def test_extract_dispatch_rejects_invalid_reasoning(client: AsyncClient):
    """POST /api/reports/{id}/extract returns 422 for invalid reasoning value."""
    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    response = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"reasoning": "turbo"},
    )
    assert response.status_code == 422
    assert "Invalid reasoning level" in response.json()["detail"]


@pytest.mark.asyncio
async def test_extract_dispatch_rejects_incompatible_reasoning(client: AsyncClient):
    """POST /api/reports/{id}/extract returns 422 for incompatible model+reasoning combo."""
    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    response = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"model": "ollama:llama4", "reasoning": "high"},
    )
    assert response.status_code == 422
    assert "not supported by ollama" in response.json()["detail"]


@pytest.mark.asyncio
async def test_extract_dispatch_rejects_unknown_model_family_reasoning(client: AsyncClient):
    """POST /api/reports/{id}/extract fails fast on unknown model-family compatibility."""
    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    response = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"model": "openai:gpt-6", "reasoning": "minimal"},
    )
    assert response.status_code == 422
    assert "Cannot verify reasoning compatibility" in response.json()["detail"]


@pytest.mark.asyncio
async def test_extract_dispatch_enqueues_with_effective_reasoning(
    app,
    client: AsyncClient,
    monkeypatch,
):
    """API enqueue should pass resolved effective reasoning to the worker task."""
    captured_args: tuple | None = None

    async def capture_kiq(*args, **kwargs):
        nonlocal captured_args
        _ = kwargs
        captured_args = args
        return None

    monkeypatch.setattr(app.state.run_extraction_task, "kiq", capture_kiq)

    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    dispatch = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"model": "openai:gpt-5-mini"},
    )
    assert dispatch.status_code == 202
    assert captured_args is not None
    assert captured_args[3] == "medium"


@pytest.mark.asyncio
async def test_job_response_includes_status_message(client: AsyncClient, monkeypatch):
    """GET /api/jobs/{job_id} should include status_message field in JSON response."""
    from finding_extractor.models import ExtractionResult

    async def fake_extract_findings(
        report_text,
        study_description=None,
        model=None,
        reasoning=None,
        *,
        section_name="findings",
        preceding_chunk_context=None,
        following_chunk_context=None,
        feedback=None,
        progress_callback=None,
    ):
        _ = (
            report_text,
            study_description,
            model,
            reasoning,
            section_name,
            preceding_chunk_context,
            following_chunk_context,
            feedback,
        )
        return ExtractionResult(report_findings=_fake_extraction("Chest XR"), usage=None)

    monkeypatch.setattr("finding_extractor.worker.extraction_jobs.extract_chunk_findings", fake_extract_findings)

    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    dispatch = await client.post(f"/api/reports/{report_id}/extract", json={})
    assert dispatch.status_code == 202
    job_id = dispatch.json()["job_id"]

    job = await client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    body = job.json()
    assert "status_message" in body
    assert body["status_message"] == "[stage:completed] extraction_complete"
    assert body["status_event"] == {
        "version": "v2",
        "stage": "completed",
        "detail": "extraction_complete",
    }


@pytest.mark.asyncio
async def test_extract_dispatch_lenient_mode_returns_warning_terminal(
    client: AsyncClient, monkeypatch
):
    """Lenient reliability mode returns completed_with_warnings and warning payload."""
    from finding_extractor.models import ExtractionResult

    async def fake_extract_findings(
        report_text,
        study_description=None,
        model=None,
        reasoning=None,
        *,
        section_name="findings",
        preceding_chunk_context=None,
        following_chunk_context=None,
        feedback=None,
        progress_callback=None,
    ):
        _ = (
            report_text,
            study_description,
            model,
            reasoning,
            section_name,
            preceding_chunk_context,
            following_chunk_context,
            feedback,
            progress_callback,
        )
        return ExtractionResult(report_findings=_fake_extraction("Chest XR"), usage=None)

    monkeypatch.setattr("finding_extractor.worker.extraction_jobs.extract_chunk_findings", fake_extract_findings)
    monkeypatch.setattr(
        "finding_extractor.worker.extraction_jobs.validate_extraction",
        lambda *_: ValidationResult(
            verbatim_errors=["invalid quote"],
            coverage_warnings=[],
        ),
    )

    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    dispatch = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"reliability_mode": "lenient"},
    )
    assert dispatch.status_code == 202
    job_id = dispatch.json()["job_id"]

    job = await client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    body = job.json()
    assert body["status"] == "completed_with_warnings"
    assert body["warning_payload"]["reliability_mode"] == "lenient"
    assert body["warning_payload"]["validation_error_count"] == 1
    assert body["warning_payload"]["section_failure_count"] == 0


@pytest.mark.asyncio
async def test_extract_dispatch_strict_mode_section_failures_return_dedicated_error(
    client: AsyncClient, monkeypatch
):
    """Strict mode should fail with section_failures_remaining when modular repairs exhaust."""
    from finding_extractor.models import ExtractionResult

    async def fake_extract_findings(
        report_text,
        study_description=None,
        model=None,
        reasoning=None,
        *,
        section_name="findings",
        preceding_chunk_context=None,
        following_chunk_context=None,
        feedback=None,
        progress_callback=None,
    ):
        _ = (
            study_description,
            model,
            reasoning,
            section_name,
            preceding_chunk_context,
            following_chunk_context,
            feedback,
            progress_callback,
        )
        if "nephrolithiasis" in report_text.lower():
            raise TimeoutError("persistent section failure")
        finding_text = report_text.splitlines()[-1].strip()
        return ExtractionResult(
            report_findings=_fake_extraction("Chest XR", finding_text=finding_text),
            usage=None,
        )

    monkeypatch.setattr("finding_extractor.worker.extraction_jobs.extract_chunk_findings", fake_extract_findings)
    monkeypatch.setattr(
        "finding_extractor.worker.extraction_jobs.get_settings",
        lambda: _settings_for_test(
            extractor_max_subagent_concurrency=2,
        ),
    )

    report = await client.post(
        "/api/reports",
        json={
            "report_text": (
                "Findings:\nStable 3 mm right renal stone.\n"
                "Impression:\nPersistent right nephrolithiasis."
            )
        },
    )
    report_id = report.json()["id"]

    dispatch = await client.post(
        f"/api/reports/{report_id}/extract",
        json={"reliability_mode": "strict"},
    )
    assert dispatch.status_code == 202
    job_id = dispatch.json()["job_id"]

    job = await client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    body = job.json()
    assert body["status"] == "failed"
    assert body["error"] == "extraction_failed:section_failures_remaining"
    assert body["warning_payload"]["reliability_mode"] == "strict"
    assert body["warning_payload"]["reason_categories"] == ["coverage_gap"]
    assert body["warning_payload"]["section_failure_count"] == 1


@pytest.mark.asyncio
async def test_extraction_detail_includes_usage(client: AsyncClient, monkeypatch):
    """Extraction detail response includes usage fields when available."""
    from finding_extractor.models import ExtractionResult

    async def fake_extract_findings(
        report_text,
        study_description=None,
        model=None,
        reasoning=None,
        *,
        section_name="findings",
        preceding_chunk_context=None,
        following_chunk_context=None,
        feedback=None,
        progress_callback=None,
    ):
        _ = (
            report_text,
            study_description,
            model,
            reasoning,
            section_name,
            preceding_chunk_context,
            following_chunk_context,
            feedback,
            progress_callback,
        )
        return ExtractionResult(
            report_findings=_fake_extraction("Chest XR"),
            usage=ExtractionUsage(
                requests=1,
                input_tokens=500,
                output_tokens=200,
                cache_read_tokens=50,
                cache_write_tokens=100,
                duration_ms=1234,
            ),
        )

    monkeypatch.setattr("finding_extractor.worker.extraction_jobs.extract_chunk_findings", fake_extract_findings)

    report = await client.post("/api/reports", json={"report_text": "Findings:\nNo pleural effusion."})
    report_id = report.json()["id"]

    dispatch = await client.post(f"/api/reports/{report_id}/extract", json={})
    assert dispatch.status_code == 202
    job_id = dispatch.json()["job_id"]

    job = await client.get(f"/api/jobs/{job_id}")
    extraction_id = job.json()["extraction_id"]

    detail = await client.get(f"/api/extractions/{extraction_id}")
    assert detail.status_code == 200
    usage = detail.json()["usage"]
    assert usage is not None
    assert usage["input_tokens"] == 500
    assert usage["output_tokens"] == 200
    assert usage["duration_ms"] == 1234


@pytest.mark.asyncio
async def test_extraction_detail_includes_diagnostics_and_trace_id(
    store: ExtractionStore, client: AsyncClient
):
    """Extraction detail response includes diagnostics and trace_id fields."""
    report = await store.upsert_report("Diagnostics seed report.")
    extraction = _fake_extraction()
    diagnostics = PipelineDiagnostics(
        mode="modular",
        total_chunks=3,
        initial_failed_chunks=1,
        repaired_chunks=1,
        remaining_failed_chunks=0,
        repair_attempts_used=1,
        total_chunk_attempts=4,
        failed_chunk_ids=("findings_2",),
        failed_chunk_error_types=("TimeoutError",),
        reviewer_requested_chunks=2,
        reviewer_reextracted_chunks=1,
    )
    stored = await store.create_extraction(
        report_id=report.id,
        extraction=extraction,
        model_name="openai:gpt-5-mini",
        usage=ExtractionUsage(input_tokens=50, output_tokens=20, requests=1),
        pipeline_diagnostics=diagnostics,
        trace_id="1" * 32,
    )

    detail = await client.get(f"/api/extractions/{stored.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["trace_id"] == "1" * 32
    assert body["pipeline_diagnostics"] is not None
    assert body["pipeline_diagnostics"]["mode"] == "modular"
    assert body["pipeline_diagnostics"]["failed_chunk_ids"] == ["findings_2"]
    assert body["pipeline_diagnostics"]["failed_chunk_error_types"] == ["TimeoutError"]
    assert body["pipeline_diagnostics"]["reviewer_requested_chunks"] == 2
    assert body["pipeline_diagnostics"]["reviewer_reextracted_chunks"] == 1


@pytest.mark.asyncio
async def test_list_users(store: ExtractionStore, client: AsyncClient):
    """GET /users returns all registered users."""
    # Seed a user
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    response = await client.get("/api/users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["username"] == "talkasab"
    assert users[0]["name"] == "Tarik Alkasab"


@pytest.mark.asyncio
async def test_submit_report_with_patient_id(store: ExtractionStore, client: AsyncClient):
    """POST /reports accepts patient_id and returns it in response."""
    response = await client.post(
        "/api/reports",
        json={
            "report_text": "CT abdomen shows kidney stone.",
            "source_ref": "ACC123",
            "patient_id": "MRN0000001",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "MRN0000001"
    assert data["source_ref"] == "ACC123"

    # Verify via GET /reports/{id}
    report_id = data["id"]
    detail = await client.get(f"/api/reports/{report_id}")
    assert detail.status_code == 200
    assert detail.json()["patient_id"] == "MRN0000001"


@pytest.mark.asyncio
async def test_create_correction_with_invalid_username(
    store: ExtractionStore, client: AsyncClient
):
    """POST correction with invalid username returns 400."""
    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    response = await client.post(
        f"/api/extractions/{extraction.id}/corrections",
        json={
            "correction_type": "comment",
            "comment": "Test",
            "username": "nonexistent",
        },
    )
    assert response.status_code == 400
    assert "Invalid username" in response.json()["detail"]


@pytest.mark.asyncio
async def test_correction_author_structure(store: ExtractionStore, client: AsyncClient):
    """Correction response includes structured author field when username is valid."""
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    # Create correction with valid username
    response = await client.post(
        f"/api/extractions/{extraction.id}/corrections",
        json={
            "correction_type": "comment",
            "comment": "Looks good",
            "username": "talkasab",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["author"] is not None
    assert data["author"]["username"] == "talkasab"
    assert data["author"]["name"] == "Tarik Alkasab"
    assert data["created_by"] is None  # Not used for new corrections

    # Verify via GET /corrections
    listed = await client.get(f"/api/extractions/{extraction.id}/corrections")
    assert listed.status_code == 200
    corrections = listed.json()
    assert len(corrections) == 1
    assert corrections[0]["author"]["username"] == "talkasab"


@pytest.mark.asyncio
async def test_update_finding_with_proposed_finding(
    store: ExtractionStore, client: AsyncClient
):
    """update_finding correction accepts proposed_finding with complete Finding structure."""
    await store.create_user("talkasab", "Tarik Alkasab", "tarik@alkasab.org")

    # Create extraction with a finding
    report = await store.upsert_report("3mm left kidney stone.")
    extraction_data = _fake_extraction()
    extraction_data.findings = [
        Finding(
            finding_name="kidney stone",
            presence="present",
            location=FindingLocation(
                body_region="abdomen",
                specific_anatomy="left kidney",
                laterality="left",
            ),
            attributes=[FindingAttribute(key="size", value="3mm")],
            report_text="3mm left kidney stone.",
        )
    ]
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=extraction_data,
        model_name="openai:gpt-5-mini",
    )

    # Submit update_finding correction with proposed_finding (not nested attribute_overrides)
    response = await client.post(
        f"/api/extractions/{extraction.id}/corrections",
        json={
            "correction_type": "update_finding",
            "target_finding_index": 0,
            "proposed_finding": {
                "finding_name": "kidney stone",
                "presence": "absent",  # Changed from present
                "location": {
                    "body_region": "abdomen",
                    "specific_anatomy": "right kidney",  # Changed from left
                    "laterality": "right",
                },
                "attributes": [{"key": "size", "value": "5mm"}],  # Changed from 3mm
                "report_text": "3mm left kidney stone.",
            },
            "comment": "Corrected presence and location",
            "username": "talkasab",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["correction_type"] == "update_finding"
    assert data["target_finding_index"] == 0
    assert data["author"]["username"] == "talkasab"
    assert data["comment"] == "Corrected presence and location"


@pytest.mark.asyncio
async def test_extraction_detail_includes_inline_coding(
    store: ExtractionStore, client: AsyncClient
):
    """Extraction detail response includes inline finding coding when persisted."""
    report = await store.upsert_report("Stone in right kidney.")
    extraction_payload = _fake_extraction("CT Abdomen").model_copy(
        update={
            "findings": [
                Finding(
                    finding_name="urinary tract calculus",
                    presence="present",
                    report_text="Stone in right kidney.",
                    coding=FindingCodingBundle(
                        finding_code=FindingCode(
                            status="coded",
                            oifm_id="OIFM_GMTS_016552",
                            oifm_name="urinary tract calculus",
                            method="fast-path",
                        ),
                        location_codes=[
                            LocationCode(
                                status="coded",
                                location_id="RID29662",
                                location_name="right kidney",
                                method="fast-path",
                            )
                        ],
                    ),
                ),
            ]
        },
    )
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=extraction_payload,
        model_name="openai:gpt-5-mini",
    )

    detail = await client.get(f"/api/extractions/{extraction.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "coding_result" not in body
    coding = body["extraction"]["findings"][0]["coding"]
    assert coding["finding_code"]["oifm_id"] == "OIFM_GMTS_016552"
    assert coding["finding_code"]["method"] == "fast-path"
    assert coding["location_codes"][0]["location_id"] == "RID29662"


@pytest.mark.asyncio
async def test_extraction_detail_null_coding_when_absent(
    store: ExtractionStore, client: AsyncClient
):
    """Extraction detail response omits detached coding_result field."""
    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=_fake_extraction(),
        model_name="openai:gpt-5-mini",
    )

    detail = await client.get(f"/api/extractions/{extraction.id}")
    assert detail.status_code == 200
    assert "coding_result" not in detail.json()


@pytest.mark.asyncio
async def test_extraction_summary_includes_coding_counts(
    store: ExtractionStore, client: AsyncClient
):
    """Extraction summary response includes coding counts from inline finding coding."""
    report = await store.upsert_report("Stone in right kidney for summary.")
    extraction_payload = _fake_extraction("CT Abdomen").model_copy(
        update={
            "findings": [
                Finding(
                    finding_name="urinary tract calculus",
                    presence="present",
                    report_text="Stone in right kidney for summary.",
                    coding=FindingCodingBundle(
                        finding_code=FindingCode(
                            status="coded",
                            oifm_id="OIFM_GMTS_016552",
                            oifm_name="urinary tract calculus",
                            method="fast-path",
                        ),
                        location_codes=[],
                    ),
                )
            ]
        },
    )
    await store.create_extraction(
        report_id=report.id,
        extraction=extraction_payload,
        model_name="openai:gpt-5-mini",
    )

    listed = await client.get(f"/api/reports/{report.id}/extractions")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["coded_finding_count"] == 1
    assert items[0]["unresolved_finding_count"] == 0
