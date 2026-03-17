"""Tests for the finding extractor CLI."""

import json
from pathlib import Path

from finding_extractor.cli.extract import format_json_output, format_table_output, main
from finding_extractor.extractor.runtime import PipelineRunResult, StorageMetadata
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


async def _async_none():
    """Coroutine returning None — used to stub check_migration_current."""
    return None


def _runtime_result(
    extraction: ExtractedReportFindings,
    *,
    validation: ValidationResult | None = None,
    storage: StorageMetadata | None = None,
) -> PipelineRunResult:
    return PipelineRunResult(
        extraction=extraction,
        validation_result=validation,
        usage=storage.usage if storage is not None else None,
        pipeline_diagnostics=PipelineDiagnostics(
            mode="modular",
            total_chunks=1,
            initial_failed_chunks=0,
            remaining_failed_chunks=0,
            total_chunk_attempts=1,
            failed_chunk_ids=(),
            failed_chunk_error_types=(),
            reviewer_requested_chunks=0,
            reviewer_reextracted_chunks=0,
        ),
        model_name=storage.model_name if storage is not None else "openai:gpt-5-mini",
        reasoning_effort=storage.reasoning_effort if storage is not None else None,
        warning_payload=None,
        storage_metadata=storage,
    )


class TestFormatJsonOutput:
    """Test cases for JSON output formatting."""

    def test_basic_json_output(self):
        """Test formatting extraction as JSON."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT Abdomen"),
            findings=[
                Finding(
                    finding_name="test finding",
                    presence="present",
                    report_text="Test text.",
                ),
            ],
        )
        output = format_json_output(extraction)
        assert "CT Abdomen" in output
        assert "test finding" in output
        assert '"presence": "present"' in output

    def test_json_with_validation(self):
        """Test formatting extraction with validation results."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Test"),
        )
        validation = ValidationResult(
            verbatim_errors=[],
            coverage_warnings=[],
        )
        output = format_json_output(extraction, validation)
        assert "_validation" in output
        assert "verbatim_errors" in output

    def test_json_with_coding(self):
        """Test formatting extraction keeps inline coding in findings payload."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Test"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia.",
                    coding=FindingCodingBundle(
                        finding_code=FindingCode(
                            status="coded",
                            oifm_id="OIFM:123",
                            oifm_name="pneumonia",
                            method="fast-path",
                        ),
                        location_codes=[
                            LocationCode(
                                status="coded",
                                location_id="LOC:1",
                                location_name="lung",
                                method="fast-path",
                            )
                        ],
                    ),
                )
            ],
        )
        output = format_json_output(extraction)
        payload = json.loads(output)
        assert "_coding" not in payload
        assert payload["findings"][0]["coding"]["finding_code"]["oifm_id"] == "OIFM:123"


class TestFormatTableOutput:
    """Test cases for table output formatting."""

    def test_basic_table_output(self):
        """Test formatting extraction as table."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT Abdomen"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia seen.",
                ),
            ],
        )
        output = format_table_output(extraction)
        assert "CT Abdomen" in output
        assert "pneumonia" in output
        assert "PRESENT" in output or "Present" in output

    def test_table_with_attributes(self):
        """Test table output with finding attributes."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT"),
            findings=[
                Finding(
                    finding_name="renal calculus",
                    presence="present",
                    location=FindingLocation(
                        body_region="abdomen",
                        specific_anatomy="right kidney",
                        laterality="right",
                    ),
                    attributes=[
                        FindingAttribute(key="size", value="3 mm"),
                    ],
                    report_text="Stone seen.",
                ),
            ],
        )
        output = format_table_output(extraction)
        assert "renal calculus" in output
        assert "abdomen" in output
        assert "right" in output.lower()
        assert "size=3 mm" in output

    def test_table_with_coding_summary(self):
        """Table output should include coding summary when coding is present."""
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="CT"),
            findings=[
                Finding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia.",
                    coding=FindingCodingBundle(
                        finding_code=FindingCode(
                            status="coded",
                            oifm_id="OIFM:123",
                            oifm_name="pneumonia",
                            method="fast-path",
                        ),
                        location_codes=[],
                    ),
                ),
                Finding(
                    finding_name="atelectasis",
                    presence="present",
                    report_text="Atelectasis.",
                    coding=FindingCodingBundle(
                        finding_code=FindingCode(
                            status="unmapped",
                            method="unresolved",
                            reason="no_candidates",
                        ),
                        location_codes=[],
                    ),
                ),
            ],
        )
        output = format_table_output(extraction)
        assert "CODING:" in output
        assert "Findings coded: 1 | Unresolved: 1" in output
        assert "atelectasis" in output


class TestCLI:
    """Test cases for CLI commands."""

    def test_cli_help(self, cli_runner):
        """Test CLI help output."""
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "extract structured findings" in result.output.lower()
        assert "--exam-type" in result.output
        assert "--output" in result.output
        assert "--model" in result.output
        assert "--preset" in result.output
        assert "--verbose" in result.output
        assert "--store / --no-store" in result.output

    def test_cli_missing_file(self, cli_runner):
        """Test CLI with missing file."""
        result = cli_runner.invoke(main, ["nonexistent.txt"])
        assert result.exit_code != 0

    def test_cli_wires_structured_logging_setup(self, monkeypatch, cli_runner, runtime_logging_spy):
        """CLI startup should configure logfire first, then structured logging."""
        runtime_logging_spy.patch(
            monkeypatch,
            "finding_extractor.cli.extract",
            logfire_enabled=True,
        )

        def fake_run_pipeline_sync(**kwargs):
            _ = kwargs
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(main, [str(report_path)])

            assert result.exit_code == 0
            assert len(runtime_logging_spy.configure_calls) == 1
            assert len(runtime_logging_spy.setup_calls) == 1
            assert runtime_logging_spy.configure_calls[0]["runtime"] == "cli"
            assert runtime_logging_spy.configure_calls[0]["enabled_override"] is None
            assert runtime_logging_spy.configure_calls[0]["fastapi_app"] is None
            assert runtime_logging_spy.setup_calls[0]["include_logfire_processor"] is True
            assert runtime_logging_spy.setup_calls[0]["settings"] is not None

    def test_cli_verbose_sets_info_log_level(self, monkeypatch, cli_runner, runtime_logging_spy):
        """--verbose should elevate runtime logging level to INFO."""
        runtime_logging_spy.patch(
            monkeypatch,
            "finding_extractor.cli.extract",
            logfire_enabled=False,
        )

        def fake_run_pipeline_sync(**kwargs):
            _ = kwargs
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(main, [str(report_path), "--verbose"])

            assert result.exit_code == 0
            assert len(runtime_logging_spy.setup_calls) == 1
            assert runtime_logging_spy.setup_calls[0]["settings"].log_level == "INFO"

    def test_cli_rejects_disallowed_model_prefix(self, cli_runner):
        """CLI should fail fast when a model id violates policy."""
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(
                main, [str(report_path), "--model", "google-vertex:gemini-3-pro"]
            )
            assert result.exit_code == 1
            assert "google-vertex models are not allowed; use google-gla:*" in result.output

    def test_cli_preset_fast_sets_correct_model_and_reasoning(self, monkeypatch, cli_runner):
        """--preset fast should set model=gemini-3-flash-preview, reasoning=low."""
        captured = {}

        def fake_run_pipeline_sync(**kwargs):
            captured.update(kwargs)
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(main, [str(report_path), "--preset", "fast"])
            assert result.exit_code == 0
            assert captured["model"] == "google-gla:gemini-3-flash-preview"
            assert captured["reasoning"] == "low"

    def test_cli_preset_model_override(self, monkeypatch, cli_runner):
        """Explicit --model should override preset model."""
        captured = {}

        def fake_run_pipeline_sync(**kwargs):
            captured.update(kwargs)
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--preset", "fast", "--model", "ollama:llama3.3"],
            )
            assert result.exit_code == 0
            assert captured["model"] == "ollama:llama3.3"
            assert captured["reasoning"] == "low"

    def test_cli_preset_reasoning_override(self, monkeypatch, cli_runner):
        """Explicit --reasoning should override preset reasoning."""
        captured = {}

        def fake_run_pipeline_sync(**kwargs):
            captured.update(kwargs)
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--preset", "fast", "--reasoning", "high"],
            )
            assert result.exit_code == 0
            assert captured["model"] == "google-gla:gemini-3-flash-preview"
            assert captured["reasoning"] == "high"

    def test_cli_config_preset_fallback(self, monkeypatch, cli_runner):
        """IPL_PRESET env var should apply when --preset is not passed."""
        captured = {}

        def fake_run_pipeline_sync(**kwargs):
            captured.update(kwargs)
            return (
                ExtractedReportFindings(exam_info=ExamInfo(study_description="Chest XR")),
                None,
                None,
            )

        monkeypatch.setattr("finding_extractor.cli.extract._run_pipeline_sync", fake_run_pipeline_sync)
        monkeypatch.setenv("IPL_PRESET", "quality")
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(main, [str(report_path)])
            assert result.exit_code == 0
            assert captured["model"] == "anthropic:claude-opus-4-6"
            assert captured["reasoning"] == "low"

    def test_cli_store_writes_rows_and_outputs_storage_metadata(self, monkeypatch, cli_runner):
        """When --store is used, CLI exposes storage metadata contract in JSON output."""

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="pleural effusion",
                            presence="absent",
                            report_text="No pleural effusion.",
                        )
                    ],
                ),
                storage=StorageMetadata(
                    db_path=str(db_path),
                    report_id="r1",
                    report_seen_before=False,
                    extraction_id="e1",
                    model_name="openai:gpt-5-mini",
                    reasoning_effort=None,
                    extracted_at="2026-02-11T00:00:00+00:00",
                ),
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            lambda self: _async_none(),
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")
            db_path = Path("cli.sqlite3")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path), "--format", "json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert "_storage" in payload
            assert payload["_storage"]["db_path"] == str(db_path)
            assert payload["_storage"]["report_seen_before"] is False
            assert payload["_storage"]["model_name"] == "openai:gpt-5-mini"
            assert payload["_storage"]["report_id"]
            assert payload["_storage"]["extraction_id"]
            assert payload["_storage"]["extracted_at"]

    def test_cli_store_json_includes_usage_when_present(self, monkeypatch, cli_runner):
        """When --store is used and usage is available, JSON _storage includes serialized usage."""

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="pleural effusion",
                            presence="absent",
                            report_text="No pleural effusion.",
                        )
                    ],
                ),
                storage=StorageMetadata(
                    db_path=str(db_path),
                    report_id="r1",
                    report_seen_before=False,
                    extraction_id="e1",
                    model_name="openai:gpt-5-mini",
                    reasoning_effort=None,
                    extracted_at="2026-02-11T00:00:00+00:00",
                    usage=ExtractionUsage(
                        requests=1,
                        input_tokens=500,
                        output_tokens=200,
                        cache_read_tokens=50,
                        cache_write_tokens=100,
                        duration_ms=1234,
                    ),
                ),
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            lambda self: _async_none(),
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")
            db_path = Path("cli.sqlite3")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path), "--format", "json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert "_storage" in payload
            usage = payload["_storage"]["usage"]
            assert usage is not None
            assert usage["input_tokens"] == 500
            assert usage["output_tokens"] == 200
            assert usage["duration_ms"] == 1234
            assert usage["requests"] == 1

    def test_cli_default_json_has_no_storage_metadata(self, monkeypatch, cli_runner):
        """Without --store, JSON output should not include _storage."""

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="cardiomegaly",
                            presence="absent",
                            report_text="Cardiomediastinal silhouette is normal.",
                        )
                    ],
                ),
                storage=None,
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("Cardiomediastinal silhouette is normal.")

            result = cli_runner.invoke(main, [str(report_path), "--format", "json"])
            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert "_storage" not in payload

    def test_cli_store_marks_second_run_as_seen_before(self, monkeypatch, cli_runner):
        """Running twice against same DB/report should set report_seen_before on second run."""

        counter = {"n": 0}

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            counter["n"] += 1
            n = counter["n"]
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="pleural effusion",
                            presence="absent",
                            report_text="No pleural effusion.",
                        )
                    ],
                ),
                storage=StorageMetadata(
                    db_path=str(db_path),
                    report_id="same-report-id",
                    report_seen_before=(n > 1),
                    extraction_id=f"e{n}",
                    model_name="openai:gpt-5-mini",
                    reasoning_effort=None,
                    extracted_at=f"2026-02-11T00:00:0{n}+00:00",
                ),
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            lambda self: _async_none(),
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")
            db_path = Path("cli.sqlite3")

            first = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path), "--format", "json"],
            )
            second = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path), "--format", "json"],
            )

            assert first.exit_code == 0
            assert second.exit_code == 0

            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            assert first_payload["_storage"]["report_seen_before"] is False
            assert second_payload["_storage"]["report_seen_before"] is True
            assert first_payload["_storage"]["report_id"] == second_payload["_storage"]["report_id"]
            assert (
                first_payload["_storage"]["extraction_id"]
                != second_payload["_storage"]["extraction_id"]
            )

    def test_cli_table_output_includes_persistence_block_when_store_enabled(
        self, monkeypatch, cli_runner
    ):
        """Table output includes persistence section when --store is enabled."""

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="pneumonia",
                            presence="present",
                            report_text="Pneumonia seen.",
                        )
                    ],
                ),
                storage=StorageMetadata(
                    db_path=str(db_path),
                    report_id="r-table",
                    report_seen_before=False,
                    extraction_id="e-table",
                    model_name="openai:gpt-5-mini",
                    reasoning_effort=None,
                    extracted_at="2026-02-11T00:00:00+00:00",
                ),
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            lambda self: _async_none(),
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("Pneumonia seen.")
            result = cli_runner.invoke(main, [str(report_path), "--store", "--format", "table"])

            assert result.exit_code == 0
            assert "PERSISTENCE:" in result.output
            assert "Report ID:" in result.output
            assert "Extraction ID:" in result.output

    def test_cli_emits_progress_on_stderr(self, monkeypatch, cli_runner):
        """CLI should emit progress messages to stderr during extraction."""

        async def fake_run_extraction_runtime(
            report_text,
            *,
            study_description,
            model,
            reasoning,
            validate,
            store,
            db_path,
            source_ref,
            progress_callback=None,
            **kwargs,
        ):
            _ = (report_text, study_description, model, reasoning, validate, store, db_path, source_ref)
            if progress_callback is not None:
                await progress_callback("Validating model configuration...")
                await progress_callback("Calling model...")
                await progress_callback("Model call complete, processing results")
                await progress_callback("Done.")
            return _runtime_result(
                ExtractedReportFindings(
                    exam_info=ExamInfo(study_description="Chest XR"),
                    findings=[
                        Finding(
                            finding_name="pleural effusion",
                            presence="absent",
                            report_text="No pleural effusion.",
                        )
                    ],
                ),
                storage=None,
            )

        monkeypatch.setattr(
            "finding_extractor.cli.extract.run_extraction_runtime", fake_run_extraction_runtime
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(main, [str(report_path), "--format", "json"])
            assert result.exit_code == 0
            assert "Validating model configuration..." in result.stderr
            assert "Calling model..." in result.stderr
            assert "Model call complete, processing results" in result.stderr
            assert "Done." in result.stderr

    def test_cli_rejects_incompatible_reasoning(self, cli_runner):
        """CLI should fail when reasoning level is incompatible with model provider."""
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")

            result = cli_runner.invoke(
                main, [str(report_path), "--model", "ollama:llama4", "--reasoning", "high"]
            )
            assert result.exit_code == 1
            assert "not supported by ollama" in result.output

    def test_cli_store_migration_preflight_rejects_outdated_db(self, monkeypatch, cli_runner):
        """When --store targets a DB at wrong revision, CLI should fail with migration hint."""

        async def fake_check_migration(self) -> str | None:
            return "Database is at revision 17f8ebc6c608, expected a3f1c8b2d4e6. Run 'task db:migrate' to upgrade."

        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            fake_check_migration,
        )
        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")
            db_path = Path("outdated.sqlite3")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path)],
            )
            assert result.exit_code != 0
            assert "expected a3f1c8b2d4e6" in result.output
            assert "task db:migrate" in result.output

    def test_cli_store_fresh_db_fails_preflight_without_creating_tables(self, cli_runner):
        """Fresh DB + --store should fail preflight and leave DB without app tables."""
        import sqlite3

        with cli_runner.isolated_filesystem():
            report_path = Path("report.md")
            report_path.write_text("No pleural effusion.")
            db_path = Path("fresh.sqlite3")

            result = cli_runner.invoke(
                main,
                [str(report_path), "--store", "--db-path", str(db_path)],
            )
            assert result.exit_code != 0
            assert "task db:migrate" in (result.output + result.stderr)

            # DB file may or may not exist (engine may create it),
            # but app tables must not have been created.
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                conn.close()
                for app_table in ("reports", "extractions", "corrections", "jobs"):
                    assert app_table not in tables, (
                        f"Table '{app_table}' should not exist after preflight failure"
                    )
