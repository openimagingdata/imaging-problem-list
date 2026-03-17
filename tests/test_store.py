"""Tests for SQLite persistence backing."""

import json
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from finding_extractor.db.store import (
    CorrectionRow,
    ExtractionRow,
    ExtractionStore,
    ReportRow,
)
from finding_extractor.extractor.report_sections import sections_from_json
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    Finding,
    FindingAttribute,
    FindingCode,
    FindingCodingBundle,
    FindingLocation,
    JobWarningPayload,
    LocationCode,
    NonFindingText,
    PipelineDiagnostics,
    ValidationResult,
)
from finding_extractor.read_models import (
    ExtractionDetail,
    ExtractionSummary,
    ReportSummary,
)


@pytest_asyncio.fixture
async def store(tmp_path: Path, store_factory):
    """Create a temporary SQLite-backed store."""
    async with store_factory(tmp_path / "test.sqlite3") as s:
        yield s


@pytest.mark.asyncio
async def test_upsert_report_deduplicates_by_hash(store: ExtractionStore):
    """Same report text should map to a single persisted report row."""
    report_text = "Findings: No focal airspace opacity."

    first = await store.upsert_report(report_text, source_ref="report-a.md")
    second = await store.upsert_report(report_text, source_ref="report-b.md")

    assert isinstance(first, ReportSummary)
    assert isinstance(second, ReportSummary)
    assert first.id == second.id
    assert first.seen_before is False
    assert second.seen_before is True


@pytest.mark.asyncio
async def test_report_with_patient_id(store: ExtractionStore):
    """Patient ID can be associated with a report."""
    report_text = "CT scan shows normal findings."

    # Create report with patient_id
    first = await store.upsert_report(report_text, source_ref="ct-001", patient_id="MRN12345")
    assert first.patient_id == "MRN12345"
    assert first.seen_before is False

    # Dedup still works - same text returns existing report
    second = await store.upsert_report(report_text, source_ref="ct-002")
    assert second.id == first.id
    assert second.patient_id == "MRN12345"
    assert second.seen_before is True

    # Can update patient_id on subsequent upsert if not set
    third_text = "MRI brain unremarkable."
    third = await store.upsert_report(third_text, source_ref="mri-001")
    assert third.patient_id is None

    fourth = await store.upsert_report(third_text, patient_id="MRN99999")
    assert fourth.id == third.id
    assert fourth.patient_id == "MRN99999"


@pytest.mark.asyncio
async def test_create_and_get_users(store: ExtractionStore):
    """Users can be created and retrieved."""
    # Create user
    user = await store.create_user("jsmith", "John Smith", "john@example.com")
    assert user.username == "jsmith"
    assert user.name == "John Smith"
    assert user.email == "john@example.com"
    assert user.created_at is not None

    # Get user
    retrieved = await store.get_user("jsmith")
    assert retrieved is not None
    assert retrieved.username == "jsmith"
    assert retrieved.name == "John Smith"

    # Get non-existent user
    missing = await store.get_user("nobody")
    assert missing is None

    # List users
    await store.create_user("adoe", "Alice Doe", "alice@example.com")
    users = await store.list_users()
    assert len(users) == 2
    assert users[0].username == "adoe"  # alphabetical order
    assert users[1].username == "jsmith"

    # Upsert semantics - update existing user
    updated = await store.create_user("jsmith", "John Q. Smith", "johnq@example.com")
    assert updated.username == "jsmith"
    assert updated.name == "John Q. Smith"
    assert updated.email == "johnq@example.com"

    users_after = await store.list_users()
    assert len(users_after) == 2  # Still only 2 users


@pytest.mark.asyncio
async def test_create_extraction_persists_payload_json(store: ExtractionStore):
    """Extraction payload is stored as JSON with nested findings and non-finding segments."""
    report = await store.upsert_report("Technique: CT.\nStone in right kidney.")
    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(
            study_description="CT Abdomen",
            study_date=date(2021, 8, 26),
            modality="CT",
            body_part="abdomen",
        ),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="right kidney",
                    laterality="right",
                ),
                attributes=[FindingAttribute(key="size", value="3 mm")],
                report_text="Stone in right kidney.",
            ),
        ],
        non_finding_text=[
            NonFindingText(text="Technique: CT.", category="technique"),
        ],
    )

    extraction_record = await store.create_extraction(
        report_id=report.id,
        extraction=extraction,
        model_name="openai:gpt-5-mini",
        reasoning_effort="medium",
    )

    async with AsyncSession(store.engine) as session:
        row = (
            await session.exec(
                select(ExtractionRow).where(ExtractionRow.id == extraction_record.id)
            )
        ).first()

    assert row is not None
    payload = json.loads(row.extraction_json)
    assert payload["exam_info"]["study_description"] == "CT Abdomen"
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["finding_name"] == "renal calculus"
    assert payload["findings"][0]["attributes"][0]["key"] == "size"
    assert len(payload["non_finding_text"]) == 1


@pytest.mark.asyncio
async def test_create_extraction_with_coding_persists_and_round_trips(store: ExtractionStore):
    """Inline finding coding persists through detail and summary views."""
    report = await store.upsert_report("Stone in right kidney.")
    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen"),
        findings=[
            Finding(
                finding_name="renal calculus",
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
        ],
    )

    stored = await store.create_extraction(
        report_id=report.id,
        extraction=extraction,
        model_name="openai:gpt-5-mini",
    )

    # Detail view: inline coding round-trip
    detail = await store.get_extraction(stored.id)
    assert detail is not None
    assert detail.extraction.findings[0].coding is not None
    assert detail.extraction.findings[0].coding.finding_code.oifm_id == "OIFM_GMTS_016552"
    assert detail.extraction.findings[0].coding.finding_code.method == "fast-path"
    assert detail.extraction.findings[0].coding.location_codes[0].location_id == "RID29662"

    # Summary view: coding counts
    summaries = await store.list_extractions(report.id)
    assert len(summaries) == 1
    assert summaries[0].coded_finding_count == 1
    assert summaries[0].unresolved_finding_count == 0


@pytest.mark.asyncio
async def test_extraction_without_coding_returns_null(store: ExtractionStore):
    """Extraction without coding data returns None for coding fields."""
    report = await store.upsert_report("No findings.")
    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="Chest XR"),
    )

    stored = await store.create_extraction(
        report_id=report.id,
        extraction=extraction,
        model_name="openai:gpt-5-mini",
    )

    detail = await store.get_extraction(stored.id)
    assert detail is not None
    assert detail.extraction.findings == []

    summaries = await store.list_extractions(report.id)
    assert summaries[0].coded_finding_count is None
    assert summaries[0].unresolved_finding_count is None


@pytest.mark.asyncio
async def test_record_correction_supports_comment_and_addition(store: ExtractionStore):
    """Corrections can be comments or proposed new findings."""
    # Create a user first
    await store.create_user("reviewer", "Test Reviewer", "reviewer@example.org")

    report = await store.upsert_report("No pleural effusion.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[],
            non_finding_text=[],
        ),
        model_name="openai:gpt-5-mini",
    )

    comment_correction = await store.record_correction(
        extraction_id=extraction.id,
        correction_type="comment",
        comment="Double-check whether this was compared to prior imaging.",
        created_by="reviewer@example.org",
        username="reviewer",
    )
    add_correction = await store.record_correction(
        extraction_id=extraction.id,
        correction_type="add_finding",
        proposed_finding=Finding(
            finding_name="pleural effusion",
            presence="absent",
            report_text="No pleural effusion.",
        ),
        created_by="reviewer@example.org",
        username="reviewer",
    )

    rows = await store.list_corrections(extraction.id)
    types = [r.correction_type for r in rows]

    assert comment_correction.id != add_correction.id
    assert len(rows) == 2
    assert "comment" in types
    assert "add_finding" in types
    assert comment_correction.comment == "Double-check whether this was compared to prior imaging."
    assert comment_correction.username == "reviewer"
    assert add_correction.username == "reviewer"
    # Legacy created_by still preserved
    assert comment_correction.created_by == "reviewer@example.org"


@pytest.mark.asyncio
async def test_record_update_correction_by_finding_index(store: ExtractionStore):
    """Update correction can target a finding via finding index/path."""
    report = await store.upsert_report("Pneumonia in right lower lobe.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia in right lower lobe.",
                )
            ],
            non_finding_text=[],
        ),
        model_name="openai:gpt-5-mini",
    )

    correction = await store.record_correction(
        extraction_id=extraction.id,
        correction_type="update_finding",
        target_finding_index=0,
        attribute_overrides={"severity": "mild"},
        created_by="reviewer@example.org",
    )
    assert correction.target_finding_index == 0
    assert correction.target_json_path == "$.findings[0]"

    async with AsyncSession(store.engine) as session:
        row = (
            await session.exec(select(CorrectionRow).where(CorrectionRow.id == correction.id))
        ).first()
    assert row is not None
    assert row.target_json_path == "$.findings[0]"


@pytest.mark.asyncio
async def test_record_update_correction_invalid_finding_index_raises(store: ExtractionStore):
    """Update correction rejects target indexes that are out of extraction findings range."""
    report = await store.upsert_report("Pneumonia in right lower lobe.")
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia in right lower lobe.",
                )
            ],
            non_finding_text=[],
        ),
        model_name="openai:gpt-5-mini",
    )

    with pytest.raises(
        ValueError,
        match="update_finding target_finding_index does not exist in extraction findings",
    ):
        await store.record_correction(
            extraction_id=extraction.id,
            correction_type="update_finding",
            target_finding_index=9,
            attribute_overrides={"severity": "mild"},
            created_by="reviewer@example.org",
        )

    rows = await store.list_corrections(extraction.id)
    assert rows == []


@pytest.mark.asyncio
async def test_get_report_and_list_reports(store: ExtractionStore):
    """Report read APIs return detail and paginated summary objects."""
    first = await store.upsert_report("First report", source_ref="first.md")
    second = await store.upsert_report("Second report", source_ref="second.md")

    got_first = await store.get_report(first.id)
    assert got_first is not None
    assert got_first.id == first.id
    assert got_first.report_text == "First report"

    listed = await store.list_reports(limit=10, offset=0)
    listed_ids = {item.id for item in listed}
    assert first.id in listed_ids
    assert second.id in listed_ids


@pytest.mark.asyncio
async def test_get_extraction_and_list_extractions(store: ExtractionStore):
    """Extraction read APIs deserialize payloads and filter by report."""
    report = await store.upsert_report("Test report text")
    other_report = await store.upsert_report("Other report text")

    extraction = ExtractedReportFindings(
        exam_info=ExamInfo(study_description="CT Abdomen", modality="CT", body_part="abdomen"),
        findings=[
            Finding(
                finding_name="renal calculus",
                presence="present",
                report_text="Stone in the right kidney.",
            )
        ],
        non_finding_text=[NonFindingText(text="Technique: CT.", category="technique")],
    )
    validation = ValidationResult(
        verbatim_errors=[],
        coverage_warnings=[],
    )

    first = await store.create_extraction(
        report_id=report.id,
        extraction=extraction,
        model_name="openai:gpt-5-mini",
        validation_result=validation,
    )
    _ = await store.create_extraction(
        report_id=other_report.id,
        extraction=ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
        model_name="openai:gpt-5-mini",
    )

    detail = await store.get_extraction(first.id)
    assert detail is not None
    assert detail.id == first.id
    assert detail.extraction.exam_info.study_description == "CT Abdomen"
    assert detail.validation_result is not None
    assert detail.validation_result.verbatim_errors == []

    listed = await store.list_extractions(report.id)
    assert [item.id for item in listed] == [first.id]


@pytest.mark.asyncio
async def test_job_lifecycle_round_trip(store: ExtractionStore):
    """Jobs can be created, transitioned, and fetched by polling APIs."""
    report = await store.upsert_report("Pending report")
    job = await store.create_job(job_id="job-1", report_id=report.id, status="pending")
    assert job.status == "pending"

    await store.mark_job_running("job-1")
    running = await store.get_job("job-1")
    assert running is not None
    assert running.status == "running"
    assert running.started_at is not None

    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(exam_info=ExamInfo(study_description="CT")),
        model_name="openai:gpt-5-mini",
    )
    await store.mark_job_completed("job-1", extraction_id=extraction.id)
    completed = await store.get_job("job-1")
    assert completed is not None
    assert completed.status == "completed"
    assert completed.extraction_id == extraction.id
    assert completed.completed_at is not None
    assert completed.warning_payload is None


@pytest.mark.asyncio
async def test_mark_job_completed_with_warnings_round_trip(store: ExtractionStore):
    """Warning-capable terminal status stores deterministic warning payload."""
    report = await store.upsert_report("Findings report")
    await store.create_job(job_id="job-warn", report_id=report.id)
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(exam_info=ExamInfo(study_description="CT")),
        model_name="openai:gpt-5-mini",
    )
    payload = JobWarningPayload(
        reliability_mode="lenient",
        reason_categories=["validation_failed", "verbatim_mismatch"],
        dropped_findings_count=2,
        dropped_non_finding_count=1,
        validation_error_count=2,
        coverage_warning_count=0,
        section_failure_count=0,
    )

    await store.mark_job_completed_with_warnings(
        "job-warn",
        extraction_id=extraction.id,
        warning_payload=payload,
    )
    job = await store.get_job("job-warn")
    assert job is not None
    assert job.status == "completed_with_warnings"
    assert job.warning_payload == payload


@pytest.mark.asyncio
async def test_mark_job_failed_records_error(store: ExtractionStore):
    """Failed jobs expose an error string and completion timestamp."""
    report = await store.upsert_report("Failed report")
    await store.create_job(job_id="job-2", report_id=report.id)

    await store.mark_job_failed("job-2", error="boom")
    failed = await store.get_job("job-2")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "boom"
    assert failed.completed_at is not None
    assert failed.warning_payload is None


@pytest.mark.asyncio
async def test_mark_job_failed_records_warning_payload(store: ExtractionStore):
    """Failed jobs can carry deterministic warning payloads."""
    report = await store.upsert_report("Failed report with warning payload")
    await store.create_job(job_id="job-fail-warning", report_id=report.id)
    payload = JobWarningPayload(
        reliability_mode="strict",
        reason_categories=["validation_failed"],
        dropped_findings_count=0,
        dropped_non_finding_count=0,
        validation_error_count=1,
        coverage_warning_count=0,
        section_failure_count=0,
    )

    await store.mark_job_failed(
        "job-fail-warning",
        error="extraction_failed:validation_failed",
        warning_payload=payload,
    )
    failed = await store.get_job("job-fail-warning")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "extraction_failed:validation_failed"
    assert failed.warning_payload == payload


@pytest.mark.asyncio
async def test_update_job_status_message(store: ExtractionStore):
    """update_job_status_message sets the message and it is visible via get_job."""
    report = await store.upsert_report("Status message report")
    await store.create_job(job_id="job-msg", report_id=report.id)

    await store.update_job_status_message("job-msg", "Extracting findings from report")
    job = await store.get_job("job-msg")
    assert job is not None
    assert job.status_message == "Extracting findings from report"


@pytest.mark.asyncio
async def test_update_job_status_message_unknown_job_raises(store: ExtractionStore):
    """update_job_status_message raises ValueError for unknown job_id."""
    with pytest.raises(ValueError, match="Unknown job_id"):
        await store.update_job_status_message("nonexistent", "hello")


@pytest.mark.asyncio
async def test_mark_job_running_sets_status_message(store: ExtractionStore):
    """mark_job_running should set a canonical stage status message."""
    report = await store.upsert_report("Running status report")
    await store.create_job(job_id="job-run-msg", report_id=report.id)

    await store.mark_job_running("job-run-msg")
    job = await store.get_job("job-run-msg")
    assert job is not None
    assert job.status_message == "[stage:queued] starting"


@pytest.mark.asyncio
async def test_mark_job_completed_sets_status_message(store: ExtractionStore):
    """mark_job_completed should set a canonical terminal stage message."""
    report = await store.upsert_report("Completed status report")
    await store.create_job(job_id="job-done-msg", report_id=report.id)
    extraction = await store.create_extraction(
        report_id=report.id,
        extraction=ExtractedReportFindings(exam_info=ExamInfo(study_description="CT")),
        model_name="openai:gpt-5-mini",
    )

    await store.mark_job_completed("job-done-msg", extraction_id=extraction.id)
    job = await store.get_job("job-done-msg")
    assert job is not None
    assert job.status_message == "[stage:completed] extraction_complete"


@pytest.mark.asyncio
async def test_mark_job_failed_sets_status_message(store: ExtractionStore):
    """mark_job_failed should set a canonical failure stage message."""
    report = await store.upsert_report("Failed status report")
    await store.create_job(job_id="job-fail-msg", report_id=report.id)

    await store.mark_job_failed("job-fail-msg", error="boom")
    job = await store.get_job("job-fail-msg")
    assert job is not None
    assert job.status_message == "[stage:failed] boom"


@pytest.mark.asyncio
async def test_sqlite_pragmas_are_applied(store: ExtractionStore):
    """Connections enforce SQLite WAL and related concurrency settings."""
    async with store.engine.connect() as conn:
        journal_mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar()
        busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar()
        synchronous = (await conn.exec_driver_sql("PRAGMA synchronous")).scalar()
        foreign_keys = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 5000
    # NORMAL can be returned as either integer (1) or string.
    assert str(synchronous).lower() in {"1", "normal"}
    assert foreign_keys == 1


class TestMigrationPreflight:
    """check_migration_current() works without init() and does not create tables."""

    @pytest.mark.asyncio
    async def test_fresh_db_fails_preflight_without_creating_tables(self, tmp_path: Path):
        """A brand-new DB should fail preflight, and no app tables should be created."""
        db_path = tmp_path / "fresh.sqlite3"
        s = ExtractionStore(db_path)
        try:
            error = await s.check_migration_current()
            assert error is not None
            assert "task db:migrate" in error

            # Verify no app tables were created as a side effect
            async with s.engine.connect() as conn:
                rows = (
                    await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            table_names = {row[0] for row in rows}
            for app_table in ("reports", "extractions", "corrections", "jobs"):
                assert app_table not in table_names, (
                    f"Table '{app_table}' should not exist before init()"
                )
        finally:
            await s.close()

    @pytest.mark.asyncio
    async def test_preflight_passes_after_stamping_expected_revision(self, tmp_path: Path):
        """If alembic_version matches EXPECTED_REVISION, preflight returns None."""
        db_path = tmp_path / "stamped.sqlite3"
        s = ExtractionStore(db_path)
        try:
            # Manually create alembic_version and stamp the expected revision
            async with s.engine.begin() as conn:
                await conn.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                )
                await conn.exec_driver_sql(
                    f"INSERT INTO alembic_version VALUES ('{ExtractionStore.EXPECTED_REVISION}')"
                )
            error = await s.check_migration_current()
            assert error is None
        finally:
            await s.close()

    @pytest.mark.asyncio
    async def test_preflight_fails_on_wrong_revision(self, tmp_path: Path):
        """If alembic_version has a different revision, preflight returns error."""
        db_path = tmp_path / "old.sqlite3"
        s = ExtractionStore(db_path)
        try:
            async with s.engine.begin() as conn:
                await conn.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                )
                await conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('17f8ebc6c608')")
            error = await s.check_migration_current()
            assert error is not None
            assert "17f8ebc6c608" in error
            assert ExtractionStore.EXPECTED_REVISION in error
            assert "task db:migrate" in error
        finally:
            await s.close()

    @pytest.mark.asyncio
    async def test_preflight_fails_on_empty_alembic_version(self, tmp_path: Path):
        """If alembic_version exists but is empty, preflight returns error."""
        db_path = tmp_path / "empty.sqlite3"
        s = ExtractionStore(db_path)
        try:
            async with s.engine.begin() as conn:
                await conn.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                )
            error = await s.check_migration_current()
            assert error is not None
            assert "empty" in error
            assert "task db:migrate" in error
        finally:
            await s.close()


class TestSectionPersistence:
    """Section structure is computed and stored at report ingestion time."""

    STRUCTURED_REPORT = "Findings:\nThe liver is unremarkable.\n\nImpression:\nNo acute finding."

    UNSTRUCTURED_REPORT = "The heart is normal. No pleural effusion."

    @pytest.mark.asyncio
    async def test_upsert_stores_sections_for_new_report(self, store: ExtractionStore):
        """New structured report should have section_structure_json populated."""
        await store.upsert_report(self.STRUCTURED_REPORT)

        async with store.session() as session:
            row = (await session.exec(select(ReportRow))).first()
        assert row is not None
        assert row.section_structure_json is not None
        sections = json.loads(row.section_structure_json)
        names = [s["name"] for s in sections]
        assert "findings" in names
        assert "impression" in names

    @pytest.mark.asyncio
    async def test_upsert_stores_null_for_unstructured_report(self, store: ExtractionStore):
        """Unstructured report should have section_structure_json = NULL."""
        await store.upsert_report(self.UNSTRUCTURED_REPORT)

        async with store.session() as session:
            row = (await session.exec(select(ReportRow))).first()
        assert row is not None
        assert row.section_structure_json is None

    @pytest.mark.asyncio
    async def test_backfill_on_re_upsert(self, store: ExtractionStore):
        """Existing report without sections gets sections on re-upsert."""
        # First insert without sections (simulate pre-upgrade row)
        report = await store.upsert_report(self.STRUCTURED_REPORT)
        async with store.session() as session:
            row = (await session.exec(select(ReportRow).where(ReportRow.id == report.id))).first()
            assert row is not None
            row.section_structure_json = None
            session.add(row)
            await session.commit()

        # Re-upsert should backfill
        await store.upsert_report(self.STRUCTURED_REPORT)
        async with store.session() as session:
            row = (await session.exec(select(ReportRow).where(ReportRow.id == report.id))).first()
        assert row is not None
        assert row.section_structure_json is not None
        sections = json.loads(row.section_structure_json)
        names = [s["name"] for s in sections]
        assert "findings" in names

    @pytest.mark.asyncio
    async def test_sections_round_trip_via_json(self, store: ExtractionStore):
        """Stored sections deserialize correctly via PreprocessedReport helper."""
        await store.upsert_report(self.STRUCTURED_REPORT)

        async with store.session() as session:
            row = (await session.exec(select(ReportRow))).first()
        assert row is not None
        assert row.section_structure_json is not None

        restored = sections_from_json(row.section_structure_json)
        assert len(restored) >= 2
        assert restored[0].name == "findings"
        assert restored[1].name == "impression"


class TestExtractionMetadata:
    """Extraction summary and detail views surface exam info, diagnostics, and trace_id."""

    @pytest.mark.asyncio
    async def test_summary_surfaces_exam_info_fields(self, store: ExtractionStore):
        """ExtractionSummary includes denormalized exam info columns."""
        report = await store.upsert_report("CT scan of abdomen.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(
                study_description="CT Abdomen and Pelvis",
                modality="CT",
                body_region="abdomen",
                body_part="abdomen, pelvis",
                contrast="with",
                laterality=None,
            ),
            findings=[
                Finding(
                    finding_name="renal calculus",
                    presence="present",
                    report_text="CT scan of abdomen.",
                ),
            ],
        )

        await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
        )

        summaries = await store.list_extractions(report.id)
        assert len(summaries) == 1
        summary = summaries[0]
        assert isinstance(summary, ExtractionSummary)
        assert summary.study_description == "CT Abdomen and Pelvis"
        assert summary.modality == "CT"
        assert summary.body_region == "abdomen"
        assert summary.body_part == "abdomen, pelvis"
        assert summary.contrast == "with"
        assert summary.laterality is None
        assert summary.finding_count == 1

    @pytest.mark.asyncio
    async def test_laterality_persisted_and_surfaced(self, store: ExtractionStore):
        """Laterality from ExamInfo is stored as a column and returned in summary."""
        report = await store.upsert_report("Right shoulder XR.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(
                study_description="XR Shoulder",
                modality="XR",
                body_region="upper extremity",
                body_part="shoulder",
                laterality="right",
            ),
        )

        await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
        )

        summaries = await store.list_extractions(report.id)
        assert summaries[0].laterality == "right"

    @pytest.mark.asyncio
    async def test_finding_count_persisted(self, store: ExtractionStore):
        """finding_count is computed at persist time from findings list."""
        report = await store.upsert_report("Multiple findings report.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT Chest"),
            findings=[
                Finding(
                    finding_name="nodule",
                    presence="present",
                    report_text="Nodule.",
                ),
                Finding(
                    finding_name="effusion",
                    presence="absent",
                    report_text="No effusion.",
                ),
            ],
        )

        await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
        )

        summaries = await store.list_extractions(report.id)
        assert summaries[0].finding_count == 2

        # Also check the raw DB row
        async with AsyncSession(store.engine) as session:
            row = (await session.exec(select(ExtractionRow))).first()
        assert row is not None
        assert row.finding_count == 2

    @pytest.mark.asyncio
    async def test_pipeline_diagnostics_round_trip(self, store: ExtractionStore):
        """Pipeline diagnostics serialize/deserialize through the detail view."""
        report = await store.upsert_report("Diagnostics test report.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT Abdomen"),
        )
        diagnostics = PipelineDiagnostics(
            mode="modular",
            total_chunks=3,
            initial_failed_chunks=1,
            repaired_chunks=1,
            remaining_failed_chunks=0,
            repair_attempts_used=1,
            total_chunk_attempts=4,
            failed_chunk_ids=(),
            failed_chunk_error_types=(),
            reviewer_requested_chunks=2,
            reviewer_reextracted_chunks=1,
        )

        stored = await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
            pipeline_diagnostics=diagnostics,
        )

        detail = await store.get_extraction(stored.id)
        assert detail is not None
        assert isinstance(detail, ExtractionDetail)
        assert detail.pipeline_diagnostics is not None
        assert detail.pipeline_diagnostics.mode == "modular"
        assert detail.pipeline_diagnostics.total_chunks == 3
        assert detail.pipeline_diagnostics.initial_failed_chunks == 1
        assert detail.pipeline_diagnostics.repaired_chunks == 1
        assert detail.pipeline_diagnostics.remaining_failed_chunks == 0
        assert detail.pipeline_diagnostics.reviewer_requested_chunks == 2
        assert detail.pipeline_diagnostics.reviewer_reextracted_chunks == 1

    @pytest.mark.asyncio
    async def test_trace_id_round_trip(self, store: ExtractionStore):
        """trace_id is stored and returned in detail view."""
        report = await store.upsert_report("Trace test report.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT Abdomen"),
        )
        fake_trace_id = "0" * 32

        stored = await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
            trace_id=fake_trace_id,
        )

        detail = await store.get_extraction(stored.id)
        assert detail is not None
        assert isinstance(detail, ExtractionDetail)
        assert detail.trace_id == fake_trace_id

    @pytest.mark.asyncio
    async def test_diagnostics_and_trace_id_null_by_default(self, store: ExtractionStore):
        """When not provided, diagnostics and trace_id are None."""
        report = await store.upsert_report("Default test report.")
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT"),
        )

        stored = await store.create_extraction(
            report_id=report.id,
            extraction=extraction,
            model_name="openai:gpt-5-mini",
        )

        detail = await store.get_extraction(stored.id)
        assert detail is not None
        assert isinstance(detail, ExtractionDetail)
        assert detail.pipeline_diagnostics is None
        assert detail.trace_id is None
