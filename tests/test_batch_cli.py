"""Tests for batch extraction CLI."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from finding_extractor.cli.batch import cli
from finding_extractor.cli.batch_engine import (
    BatchRunConfig,
    _process_one_file,
    resolve_run_options,
)
from finding_extractor.extractor.runtime import PipelineRunResult, StorageMetadata
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    ExtractionUsage,
    Finding,
    PipelineDiagnostics,
)


def _runtime_result(
    extraction: ExtractedReportFindings,
    *,
    storage: StorageMetadata | None = None,
) -> PipelineRunResult:
    return PipelineRunResult(
        extraction=extraction,
        validation_result=None,
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


def test_batch_run_fail_fast_runtime_guard_blocks_run(cli_runner):
    """Runtime guard should fail fast before starting a risky batch run."""
    with cli_runner.isolated_filesystem():
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "a.txt").write_text("No pleural effusion.", encoding="utf-8")

        run_id = "batch-runtime-guard-blocked"
        result = cli_runner.invoke(
            cli,
            [
                "run",
                str(reports_dir),
                "--glob",
                "*.txt",
                "--run-id",
                run_id,
                "--run-dir",
                ".runs",
                "--workers",
                "1",
                "--timeout-seconds",
                "120",
                "--retries",
                "1",
                "--max-predicted-runtime-seconds",
                "60",
            ],
        )

        assert result.exit_code != 0
        assert "BATCH preflight:" in result.output
        assert "Predicted runtime upper bound exceeds fail-fast budget" in result.output
        assert not (Path(".runs") / run_id).exists()


def test_batch_run_allow_slow_overrides_runtime_guard(monkeypatch, cli_runner):
    """--allow-slow should permit intentionally long predicted runs."""

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
        **kwargs,
    ):
        _ = (study_description, model, reasoning, validate, store, db_path, source_ref)
        return _runtime_result(
            ExtractedReportFindings(
                exam_info=ExamInfo(study_description="Chest XR"),
                findings=[
                    Finding(
                        finding_name="pleural effusion",
                        presence="absent",
                        report_text=report_text.strip(),
                    )
                ],
                non_finding_text=[],
            ),
        )

    monkeypatch.setattr(
        "finding_extractor.cli.batch_engine.run_extraction_runtime",
        fake_run_extraction_runtime,
    )

    with cli_runner.isolated_filesystem():
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "a.txt").write_text("No pleural effusion.", encoding="utf-8")

        run_id = "batch-runtime-guard-allowed"
        result = cli_runner.invoke(
            cli,
            [
                "run",
                str(reports_dir),
                "--glob",
                "*.txt",
                "--mode",
                "interactive",
                "--run-id",
                run_id,
                "--run-dir",
                ".runs",
                "--workers",
                "1",
                "--timeout-seconds",
                "120",
                "--retries",
                "1",
                "--max-predicted-runtime-seconds",
                "60",
                "--allow-slow",
                "--model",
                "openai:gpt-5-mini",
                "--reasoning",
                "medium",
            ],
        )

        assert result.exit_code == 0
        assert "BATCH preflight warning: running despite high predicted bound" in result.output
        assert (reports_dir / "a.extracted.json").exists()


def test_batch_run_interactive_writes_outputs_and_state(monkeypatch, cli_runner):
    """Interactive run should produce extracted files and terminal state metadata."""

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
        **kwargs,
    ):
        _ = (study_description, model, reasoning, validate, store, db_path, source_ref)
        return _runtime_result(
            ExtractedReportFindings(
                exam_info=ExamInfo(study_description="Chest XR"),
                findings=[
                    Finding(
                        finding_name="pleural effusion",
                        presence="absent",
                        report_text=report_text.strip(),
                    )
                ],
                non_finding_text=[],
            ),
        )

    monkeypatch.setattr(
        "finding_extractor.cli.batch_engine.run_extraction_runtime",
        fake_run_extraction_runtime,
    )

    with cli_runner.isolated_filesystem():
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "a.txt").write_text("No pleural effusion.", encoding="utf-8")
        (reports_dir / "b.txt").write_text("No pneumothorax.", encoding="utf-8")

        run_id = "batch-test-1"
        result = cli_runner.invoke(
            cli,
            [
                "run",
                str(reports_dir),
                "--glob",
                "*.txt",
                "--mode",
                "interactive",
                "--workers",
                "2",
                "--run-id",
                run_id,
                "--run-dir",
                ".runs",
                "--model",
                "openai:gpt-5-mini",
                "--reasoning",
                "medium",
            ],
        )

        assert result.exit_code == 0
        assert (reports_dir / "a.extracted.json").exists()
        assert (reports_dir / "b.extracted.json").exists()

        state_path = Path(".runs") / run_id / "state.json"
        results_path = Path(".runs") / run_id / "results.jsonl"
        assert state_path.exists()
        assert results_path.exists()

        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["status"] == "completed"
        assert state["progress"]["total"] == 2
        assert state["progress"]["done"] == 2
        assert state["progress"]["ok"] == 2

        results = [line for line in results_path.read_text(encoding="utf-8").splitlines() if line]
        assert len(results) == 2


def test_batch_cli_wires_structured_logging_setup(monkeypatch, cli_runner, runtime_logging_spy):
    """Batch CLI startup should configure logfire first, then structured logging."""
    runtime_logging_spy.patch(
        monkeypatch,
        "finding_extractor.cli.batch",
        logfire_enabled=True,
    )

    with cli_runner.isolated_filesystem():
        run_id = "batch-test-logging"
        run_dir = Path(".runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "mode": "interactive",
                    "status": "completed",
                    "started_at": "2026-02-11T00:00:00+00:00",
                    "ended_at": "2026-02-11T00:00:01+00:00",
                    "updated_at": "2026-02-11T00:00:01+00:00",
                    "error": None,
                    "config": {},
                    "progress": {
                        "total": 0,
                        "done": 0,
                        "ok": 0,
                        "skipped": 0,
                        "failed": 0,
                        "timeout": 0,
                    },
                    "workers": {},
                }
            ),
            encoding="utf-8",
        )

        result = cli_runner.invoke(cli, ["status", "--run-id", run_id, "--run-dir", ".runs"])

    assert result.exit_code == 0
    assert len(runtime_logging_spy.configure_calls) == 1
    assert len(runtime_logging_spy.setup_calls) == 1
    assert runtime_logging_spy.configure_calls[0]["runtime"] == "cli"
    assert runtime_logging_spy.configure_calls[0]["enabled_override"] is None
    assert runtime_logging_spy.configure_calls[0]["fastapi_app"] is None
    assert runtime_logging_spy.setup_calls[0]["include_logfire_processor"] is True
    assert runtime_logging_spy.setup_calls[0]["settings"] is not None


def test_batch_status_shows_worker_elapsed_time(cli_runner):
    """Status output should include live elapsed runtime for running workers."""
    with cli_runner.isolated_filesystem():
        run_id = "batch-test-status"
        run_dir = Path(".runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        started = time.time() - 12.0

        state = {
            "run_id": run_id,
            "mode": "interactive",
            "status": "running",
            "started_at": "2026-02-11T00:00:00+00:00",
            "ended_at": None,
            "updated_at": "2026-02-11T00:00:10+00:00",
            "error": None,
            "config": {},
            "progress": {"total": 2, "done": 1, "ok": 1, "skipped": 0, "failed": 0, "timeout": 0},
            "workers": {
                "1": {
                    "status": "running",
                    "file": "a.txt",
                    "started_at": "2026-02-11T00:00:05+00:00",
                    "started_at_epoch": started,
                    "last_result": None,
                },
                "2": {
                    "status": "idle",
                    "file": None,
                    "started_at": None,
                    "started_at_epoch": None,
                    "last_result": None,
                },
            },
        }
        (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

        result = cli_runner.invoke(
            cli,
            [
                "status",
                "--run-id",
                run_id,
                "--run-dir",
                ".runs",
            ],
        )

        assert result.exit_code == 0
        assert "w1: running a.txt" in result.output
        match = re.search(r"w1: running a\.txt \((\d+\.\d+)s\)", result.output)
        assert match is not None
        assert float(match.group(1)) >= 10.0


def test_batch_run_rejects_invalid_run_id(monkeypatch, cli_runner):
    """Run id should be restricted to safe filesystem-friendly characters."""

    async def fake_extract_findings(report_text, study_description=None, model=None, reasoning=None):
        _ = (report_text, study_description, model, reasoning)
        return ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[],
            non_finding_text=[],
        )

    monkeypatch.setattr(
        "finding_extractor.extractor.runtime.extract_chunk_findings", fake_extract_findings
    )

    with cli_runner.isolated_filesystem():
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "a.txt").write_text("No pleural effusion.", encoding="utf-8")

        result = cli_runner.invoke(
            cli,
            [
                "run",
                str(reports_dir),
                "--glob",
                "*.txt",
                "--run-id",
                "../bad-id",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid run id" in result.output


def test_batch_status_watch_waits_while_starting(cli_runner):
    """Watch mode should treat 'starting' as active and wait for terminal state."""
    with cli_runner.isolated_filesystem():
        run_id = "batch-test-watch"
        run_dir = Path(".runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        state_path = run_dir / "state.json"
        state = {
            "run_id": run_id,
            "mode": "detached",
            "status": "starting",
            "started_at": "2026-02-11T00:00:00+00:00",
            "ended_at": None,
            "updated_at": "2026-02-11T00:00:00+00:00",
            "error": None,
            "config": {},
            "progress": {"total": 1, "done": 0, "ok": 0, "skipped": 0, "failed": 0, "timeout": 0},
            "workers": {
                "1": {
                    "status": "idle",
                    "file": None,
                    "started_at": None,
                    "started_at_epoch": None,
                    "last_result": None,
                },
            },
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        def _complete_soon() -> None:
            time.sleep(0.05)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            updated["status"] = "completed"
            updated["ended_at"] = "2026-02-11T00:00:01+00:00"
            updated["updated_at"] = "2026-02-11T00:00:01+00:00"
            updated["progress"]["done"] = 1
            updated["progress"]["ok"] = 1
            state_path.write_text(json.dumps(updated, indent=2), encoding="utf-8")

        t = threading.Thread(target=_complete_soon, daemon=True)
        t.start()
        result = cli_runner.invoke(
            cli,
            [
                "status",
                "--run-id",
                run_id,
                "--run-dir",
                ".runs",
                "--watch",
                "--interval-seconds",
                "0.01",
            ],
        )
        t.join(timeout=1)

        assert result.exit_code == 0
        assert "status=starting" in result.output
        assert "status=completed" in result.output


class TestReasoningPreflight:
    """Reasoning compatibility is checked at batch start, not per-file."""

    def test_resolve_run_options_rejects_incompatible_reasoning(self, tmp_path: Path):
        """Invalid reasoning for a provider should raise at resolve time."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest.")

        with pytest.raises(ValueError, match="not supported by ollama"):
            resolve_run_options(
                mode="interactive",
                workers=1,
                timeout_seconds=60,
                retries=0,
                status_interval_seconds=30.0,
                resume=False,
                suffix=".extracted.json",
                model="ollama:llama4",
                reasoning="high",
                exam_type=None,
                validate=False,
                store=False,
                db_path=tmp_path / "test.db",
                output_dir=None,
                manifest=None,
                run_dir=tmp_path / "runs",
                run_id="test-run",
                input_files=[report],
            )

    def test_resolve_run_options_rejects_incompatible_default_reasoning(
        self, tmp_path: Path, monkeypatch
    ):
        """Env default reasoning incompatible with provider should raise at resolve time."""
        monkeypatch.setenv("IPL_REASONING", "medium")
        report = tmp_path / "report.txt"
        report.write_text("Normal chest.")

        with pytest.raises(ValueError, match="not supported by ollama"):
            resolve_run_options(
                mode="interactive",
                workers=1,
                timeout_seconds=60,
                retries=0,
                status_interval_seconds=30.0,
                resume=False,
                suffix=".extracted.json",
                model="ollama:llama4",
                reasoning=None,
                exam_type=None,
                validate=False,
                store=False,
                db_path=tmp_path / "test.db",
                output_dir=None,
                manifest=None,
                run_dir=tmp_path / "runs",
                run_id="test-run",
                input_files=[report],
            )

    def test_resolve_run_options_accepts_valid_reasoning(self, tmp_path: Path):
        """Valid reasoning for a provider should succeed."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest.")

        config = resolve_run_options(
            mode="interactive",
            workers=1,
            timeout_seconds=60,
            retries=0,
            status_interval_seconds=30.0,
            resume=False,
            suffix=".extracted.json",
            model="openai:gpt-5-mini",
            reasoning="medium",
            exam_type=None,
            validate=False,
            store=False,
            db_path=tmp_path / "test.db",
            output_dir=None,
            manifest=None,
            run_dir=tmp_path / "runs",
            run_id="test-run",
            input_files=[report],
        )
        assert config.reasoning == "medium"

    def test_resolve_run_options_rejects_unknown_model_family_reasoning(self, tmp_path: Path):
        """Unknown model-family compatibility should fail fast by default."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest.")

        with pytest.raises(ValueError, match="Cannot verify reasoning compatibility"):
            resolve_run_options(
                mode="interactive",
                workers=1,
                timeout_seconds=60,
                retries=0,
                status_interval_seconds=30.0,
                resume=False,
                suffix=".extracted.json",
                model="openai:gpt-6",
                reasoning="minimal",
                exam_type=None,
                validate=False,
                store=False,
                db_path=tmp_path / "test.db",
                output_dir=None,
                manifest=None,
                run_dir=tmp_path / "runs",
                run_id="test-run",
                input_files=[report],
            )

    def test_resolve_run_options_resolves_provider_default_when_reasoning_is_none(
        self, tmp_path: Path
    ):
        """When reasoning is omitted, config should persist the provider default reasoning."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest.")

        config = resolve_run_options(
            mode="interactive",
            workers=1,
            timeout_seconds=60,
            retries=0,
            status_interval_seconds=30.0,
            resume=False,
            suffix=".extracted.json",
            model="ollama:llama4",
            reasoning=None,
            exam_type=None,
            validate=False,
            store=False,
            db_path=tmp_path / "test.db",
            output_dir=None,
            manifest=None,
            run_dir=tmp_path / "runs",
            run_id="test-run",
            input_files=[report],
        )
        assert config.reasoning == "none"


class TestUsageInOutput:
    """Usage data is included in batch _storage output."""

    @pytest.mark.asyncio
    async def test_process_one_file_includes_usage_in_storage(self, tmp_path: Path):
        """When storage_metadata has usage, it should appear in the output JSON."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest radiograph.")

        usage = ExtractionUsage(
            requests=1,
            input_tokens=500,
            output_tokens=200,
            cache_read_tokens=50,
            cache_write_tokens=100,
            duration_ms=1234,
        )
        storage = StorageMetadata(
            db_path=str(tmp_path / "test.db"),
            report_id="r1",
            report_seen_before=False,
            extraction_id="e1",
            model_name="openai:gpt-5-mini",
            reasoning_effort=None,
            extracted_at="2026-02-11T00:00:00+00:00",
            usage=usage,
        )
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pleural effusion",
                    presence="absent",
                    report_text="Normal chest radiograph.",
                )
            ],
        )

        async def fake_pipeline(*args, **kwargs):
            _ = (args, kwargs)
            return _runtime_result(extraction, storage=storage)

        config = BatchRunConfig(
            run_id="test",
            mode="interactive",
            inputs=[str(report)],
            output_dir=str(tmp_path / "out"),
            suffix=".extracted.json",
            model="openai:gpt-5-mini",
            reasoning=None,
            exam_type=None,
            workers=1,
            timeout_seconds=60,
            retries=0,
            validate=False,
            resume=False,
            store=True,
            db_path=str(tmp_path / "test.db"),
            status_interval_seconds=30.0,
            manifest_path=None,
            run_dir=str(tmp_path / "runs"),
        )

        with patch("finding_extractor.cli.batch_engine.run_extraction_runtime", side_effect=fake_pipeline):
            result = await _process_one_file(
                report,
                config=config,
                output_dir=tmp_path / "out",
                store=None,
            )

        assert result["status"] == "ok"
        output_path = Path(result["output_path"])
        payload = json.loads(output_path.read_text())
        assert "_storage" in payload
        assert "usage" in payload["_storage"]
        assert payload["_storage"]["usage"]["input_tokens"] == 500
        assert payload["_storage"]["usage"]["output_tokens"] == 200
        assert payload["_storage"]["usage"]["duration_ms"] == 1234

    @pytest.mark.asyncio
    async def test_process_one_file_omits_usage_when_none(self, tmp_path: Path):
        """When storage_metadata has no usage, _storage should not have a usage key."""
        report = tmp_path / "report.txt"
        report.write_text("Normal chest radiograph.")

        storage = StorageMetadata(
            db_path=str(tmp_path / "test.db"),
            report_id="r1",
            report_seen_before=False,
            extraction_id="e1",
            model_name="openai:gpt-5-mini",
            reasoning_effort=None,
            extracted_at="2026-02-11T00:00:00+00:00",
        )
        extraction = ExtractedReportFindings(
            exam_info=ExamInfo(study_description="Chest XR"),
            findings=[
                Finding(
                    finding_name="pleural effusion",
                    presence="absent",
                    report_text="Normal chest radiograph.",
                )
            ],
        )

        async def fake_pipeline(*args, **kwargs):
            _ = (args, kwargs)
            return _runtime_result(extraction, storage=storage)

        config = BatchRunConfig(
            run_id="test",
            mode="interactive",
            inputs=[str(report)],
            output_dir=str(tmp_path / "out"),
            suffix=".extracted.json",
            model="openai:gpt-5-mini",
            reasoning=None,
            exam_type=None,
            workers=1,
            timeout_seconds=60,
            retries=0,
            validate=False,
            resume=False,
            store=True,
            db_path=str(tmp_path / "test.db"),
            status_interval_seconds=30.0,
            manifest_path=None,
            run_dir=str(tmp_path / "runs"),
        )

        with patch("finding_extractor.cli.batch_engine.run_extraction_runtime", side_effect=fake_pipeline):
            result = await _process_one_file(
                report,
                config=config,
                output_dir=tmp_path / "out",
                store=None,
            )

        assert result["status"] == "ok"
        output_path = Path(result["output_path"])
        payload = json.loads(output_path.read_text())
        assert "_storage" in payload
        assert "usage" not in payload["_storage"]


class TestMigrationPreflight:
    """Migration-revision preflight writes terminal state on failure."""

    def test_batch_run_migration_preflight_writes_failed_state(
        self, monkeypatch, tmp_path: Path, cli_runner
    ):
        """When --store targets a DB at wrong revision, state.json should be terminal 'failed'."""

        async def fake_check_migration(self) -> str | None:
            return (
                "Database is at revision 17f8ebc6c608, "
                "expected a3f1c8b2d4e6. Run 'task db:migrate' to upgrade."
            )

        monkeypatch.setattr(
            "finding_extractor.db.store.ExtractionStore.check_migration_current",
            fake_check_migration,
        )

        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "a.txt").write_text("Normal chest.", encoding="utf-8")

        run_id = "preflight-fail"
        run_dir = tmp_path / "runs"

        result = cli_runner.invoke(
            cli,
            [
                "run",
                str(reports_dir),
                "--glob",
                "*.txt",
                "--mode",
                "interactive",
                "--run-id",
                run_id,
                "--run-dir",
                str(run_dir),
                "--store",
                "--db-path",
                str(tmp_path / "test.db"),
                "--model",
                "openai:gpt-5-mini",
            ],
        )

        assert result.exit_code != 0
        assert "task db:migrate" in result.output

        state_path = run_dir / run_id / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["status"] == "failed"
        assert state["ended_at"] is not None
        assert "expected a3f1c8b2d4e6" in state["error"]
