"""Batch extraction engine: file processing, run orchestration, and config resolution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import click
from asyncer import runnify

from finding_extractor.cli.batch_state import (
    RunMode,
    _now_epoch,
    _utc_now_iso,
    append_jsonl,
    ensure_run_dir,
    fmt_duration,
    initial_state,
    run_paths,
    write_json_atomic,
)
from finding_extractor.cli.runtime_budget import (
    DEFAULT_MAX_PREDICTED_RUNTIME_SECONDS,  # noqa: F401
    build_runtime_preflight,  # noqa: F401
)
from finding_extractor.core.config import get_settings
from finding_extractor.db.store import ExtractionStore
from finding_extractor.extractor.runtime import run_extraction_runtime
from finding_extractor.llm.model_settings import resolve_runtime_reasoning
from finding_extractor.llm.policy import validate_model_id

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class BatchRunConfig:
    run_id: str
    mode: RunMode
    inputs: list[str]
    output_dir: str | None
    suffix: str
    model: str
    reasoning: str | None
    exam_type: str | None
    workers: int
    timeout_seconds: int
    retries: int
    validate: bool
    resume: bool
    store: bool
    db_path: str
    status_interval_seconds: float
    manifest_path: str | None
    run_dir: str
    log_path: str | None = None


def _make_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid4().hex[:8]}"


def collect_input_files(
    inputs: tuple[Path, ...], glob_pattern: str, recursive: bool
) -> list[Path]:
    files: list[Path] = []
    for input_path in inputs:
        if input_path.is_file():
            files.append(input_path.resolve())
            continue
        iterator = input_path.rglob(glob_pattern) if recursive else input_path.glob(glob_pattern)
        files.extend(path.resolve() for path in iterator if path.is_file())
    return sorted(set(files))


def _resolve_output_path(source_path: Path, output_dir: Path | None, suffix: str) -> Path:
    if output_dir is None:
        return source_path.with_suffix(suffix)
    return output_dir / f"{source_path.stem}{suffix}"


def validate_output_collisions(files: list[Path], output_dir: Path | None, suffix: str) -> None:
    seen: dict[Path, Path] = {}
    for source_path in files:
        out = _resolve_output_path(source_path, output_dir, suffix)
        existing = seen.get(out)
        if existing is not None and existing != source_path:
            raise click.ClickException(
                "Output collision detected. Use a different --output-dir or rename inputs. "
                f"Both '{existing}' and '{source_path}' map to '{out}'."
            )
        seen[out] = source_path


async def _run_batch_extraction_runtime(
    report_text: str,
    *,
    exam_type: str | None,
    model: str | None,
    reasoning: str | None,
    validate: bool,
    store: ExtractionStore | None,
    db_path: Path | None,
    source_ref: str | None,
    progress_callback=None,
):
    """Run shared extraction runtime and unwrap CLI/batch-oriented tuple."""
    result = await run_extraction_runtime(
        report_text,
        study_description=exam_type,
        model=model,
        reasoning=reasoning,
        validate=validate,
        reliability_mode="strict",
        store=store,
        db_path=db_path,
        source_ref=source_ref,
        progress_callback=progress_callback,
    )
    return result.extraction, result.validation_result, result.storage_metadata


class BatchFileProgress:
    """Live single-line progress display for one batch file.

    Rewrites a single line as the extractor walks through stages, showing
    ``[N/M] filename · <status> · <total> / <status-elapsed>``. When the file
    completes the line is finalized with the outcome glyph + finding count +
    total time, then the next file's line starts below.

    In non-TTY mode (CI, redirected stdout), falls back to one-line-per-file
    at the end so logs don't accumulate carriage-returns as separate rows.
    """

    _CHUNK_START_RE = re.compile(r"chunk=([^\s]+) attempt=(\d+) status=started")
    _CHUNK_DONE_RE = re.compile(
        r"chunk=([^\s]+) attempt=(\d+) status=completed findings=(\d+)"
    )
    _CHUNK_FAIL_RE = re.compile(
        r"chunk=([^\s]+) attempt=(\d+) status=failed error=([A-Za-z0-9_]+)"
    )

    def __init__(self, *, header: str, on_tty: bool, echo: Any = click.echo):
        self._header = header  # e.g. "[1/9] head_ct_1.txt"
        self._on_tty = on_tty
        self._echo = echo
        self._started = time.monotonic()
        self._status = "starting"
        self._status_started = self._started
        self._chunk_total = 0
        self._next_chunk_idx = 0
        self._chunk_index: dict[str, int] = {}
        self._drew_pair = False  # first paint is a full two-line print; then in-place

    def _set_status(self, status: str) -> None:
        self._status = status
        self._status_started = time.monotonic()

    def start(self) -> None:
        if self._on_tty:
            self._redraw()

    async def __call__(self, message: str) -> None:
        detail = message.partition("] ")[2]
        stage = message.partition("] ")[0].removeprefix("[stage:")

        if stage == "sectionize":
            m = re.search(r"mode=\S+ sections=\d+ chunks=(\d+)", detail)
            if m:
                self._chunk_total = int(m.group(1))
                self._set_status(f"{self._chunk_total} chunks, reading exam info")
        elif stage == "extract_exam_info":
            if detail.startswith("start"):
                self._set_status("exam_info")
            elif detail.startswith("completed"):
                # Brief transition; next chunk-started will update.
                self._set_status("merging exam info")
        elif stage == "extract_sections":
            m = self._CHUNK_START_RE.search(detail)
            if m:
                chunk_id = m.group(1)
                if chunk_id not in self._chunk_index:
                    self._next_chunk_idx += 1
                    self._chunk_index[chunk_id] = self._next_chunk_idx
                idx = self._chunk_index[chunk_id]
                total = self._chunk_total or idx
                self._set_status(f"chunk {idx}/{total}")
            m = self._CHUNK_DONE_RE.search(detail)
            if m:
                # Transient state between chunks.
                self._set_status("merging")
            m = self._CHUNK_FAIL_RE.search(detail)
            if m:
                _cid, attempt, err = m.groups()
                self._set_status(f"retry (attempt {attempt}, {err})")
        elif stage == "merge_dedupe":
            self._set_status("merging")
        elif stage == "validate_output":
            self._set_status("validating")

        if self._on_tty:
            self._redraw()

    async def tick(self) -> None:
        if self._on_tty:
            self._redraw()

    def finalize(self, *, glyph: str, summary: str) -> str:
        """Replace the live pair with the terminal outcome line; clear step line.

        Returns the finalized line text (caller may persist it to a log file).
        """
        total = fmt_duration(time.monotonic() - self._started)
        final = f"{self._header.replace('  ', f' {glyph} ', 1)} · {summary} · {total}"
        if self._on_tty and self._drew_pair:
            # Move up 2 lines → clear file line → write final + \n →
            # clear step line → leave cursor on step line (empty) so the
            # next file starts there with no blank gap.
            self._echo(f"\033[2A\r\033[2K{final}\n\r\033[2K", nl=False)
        else:
            self._echo(final)
        return final

    def _redraw(self) -> None:
        now = time.monotonic()
        total = fmt_duration(now - self._started)
        status_elapsed = fmt_duration(now - self._status_started)
        file_line = f"{self._header} · {total}"
        step_line = f"       {self._status} · {status_elapsed}"
        if not self._drew_pair:
            # First paint: two lines + newline each, cursor below both.
            self._echo(file_line)
            self._echo(step_line)
            self._drew_pair = True
            return
        # Redraw in place: up 2, clear, line1 + \n, clear, line2 + \n.
        self._echo(
            f"\033[2A\r\033[2K{file_line}\n\r\033[2K{step_line}"
        )


async def _tick_loop(progress: BatchFileProgress) -> None:
    """Redraw ``progress`` every 0.5s so the timer clock keeps moving."""
    try:
        while True:
            await asyncio.sleep(0.5)
            await progress.tick()
    except asyncio.CancelledError:
        return


async def _process_one_file(
    source_path: Path,
    *,
    config: BatchRunConfig,
    output_dir: Path | None,
    store: ExtractionStore | None,
    progress_callback=None,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    output_path = _resolve_output_path(source_path, output_dir, config.suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if config.resume and output_path.exists():
        return {
            "source_path": str(source_path),
            "output_path": str(output_path),
            "status": "skipped",
            "duration_seconds": time.monotonic() - started_monotonic,
            "findings_count": None,
            "non_finding_count": None,
            "error": None,
            "report_id": None,
            "extraction_id": None,
        }

    report_text = source_path.read_text(encoding="utf-8")
    last_error: str | None = None

    for attempt in range(config.retries + 1):
        try:
            extraction, validation_result, storage_metadata = await asyncio.wait_for(
                _run_batch_extraction_runtime(
                    report_text,
                    exam_type=config.exam_type,
                    model=config.model,
                    reasoning=config.reasoning,
                    validate=config.validate,
                    store=store,
                    db_path=Path(config.db_path),
                    source_ref=str(source_path),
                    progress_callback=progress_callback,
                ),
                timeout=config.timeout_seconds,
            )

            payload = extraction.model_dump(mode="json")
            if validation_result is not None:
                payload["_validation"] = validation_result.model_dump(mode="json")
            if storage_metadata is not None:
                storage_dict: dict[str, Any] = {
                    "db_path": storage_metadata.db_path,
                    "report_id": storage_metadata.report_id,
                    "report_seen_before": storage_metadata.report_seen_before,
                    "extraction_id": storage_metadata.extraction_id,
                    "model_name": storage_metadata.model_name,
                    "reasoning_effort": storage_metadata.reasoning_effort,
                    "extracted_at": storage_metadata.extracted_at,
                }
                if storage_metadata.usage is not None:
                    storage_dict["usage"] = storage_metadata.usage.model_dump(mode="json")
                payload["_storage"] = storage_dict
            output_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            return {
                "source_path": str(source_path),
                "output_path": str(output_path),
                "status": "ok",
                "duration_seconds": time.monotonic() - started_monotonic,
                "findings_count": len(extraction.findings),
                "non_finding_count": len(extraction.non_finding_text),
                "error": None,
                "report_id": storage_metadata.report_id if storage_metadata else None,
                "extraction_id": storage_metadata.extraction_id if storage_metadata else None,
            }
        except TimeoutError:
            last_error = f"timed out after {config.timeout_seconds}s"
            if attempt == config.retries:
                return {
                    "source_path": str(source_path),
                    "output_path": str(output_path),
                    "status": "timeout",
                    "duration_seconds": time.monotonic() - started_monotonic,
                    "findings_count": None,
                    "non_finding_count": None,
                    "error": last_error,
                    "report_id": None,
                    "extraction_id": None,
                }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt == config.retries:
                return {
                    "source_path": str(source_path),
                    "output_path": str(output_path),
                    "status": "failed",
                    "duration_seconds": time.monotonic() - started_monotonic,
                    "findings_count": None,
                    "non_finding_count": None,
                    "error": last_error,
                    "report_id": None,
                    "extraction_id": None,
                }

    return {
        "source_path": str(source_path),
        "output_path": str(output_path),
        "status": "failed",
        "duration_seconds": time.monotonic() - started_monotonic,
        "findings_count": None,
        "non_finding_count": None,
        "error": last_error or "unknown error",
        "report_id": None,
        "extraction_id": None,
    }


async def run_engine(config: BatchRunConfig, *, emit: bool = True) -> int:
    paths = run_paths(Path(config.run_dir), config.run_id)
    ensure_run_dir(paths)

    output_dir = Path(config.output_dir) if config.output_dir else None
    manifest_path = Path(config.manifest_path) if config.manifest_path else None
    inputs = [Path(path) for path in config.inputs]

    log_path = Path(config.log_path) if config.log_path else None
    log_handle = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")

    def log_line(text: str) -> None:
        if log_handle is not None:
            log_handle.write(text + "\n")
            log_handle.flush()

    log_line(
        f"BATCH  run_id={config.run_id}  ·  {len(config.inputs)} inputs  ·  "
        f"workers={config.workers}  ·  model={config.model}  ·  "
        f"reasoning={config.reasoning or 'default'}  ·  mode={config.mode}"
    )

    state = initial_state(config)
    write_json_atomic(paths.state_path, state)

    store: ExtractionStore | None = ExtractionStore(Path(config.db_path)) if config.store else None
    if store is not None:
        migration_error = await store.check_migration_current()
        if migration_error is not None:
            await store.close()
            error_msg = f"{migration_error} (IPL_DB_PATH={config.db_path})"
            state["status"] = "failed"
            state["error"] = error_msg
            state["ended_at"] = _utc_now_iso()
            write_json_atomic(paths.state_path, state)
            raise click.ClickException(error_msg)
        await store.init()

    queue: asyncio.Queue[Path | None] = asyncio.Queue()
    for source_path in inputs:
        queue.put_nowait(source_path)
    for _ in range(config.workers):
        queue.put_nowait(None)

    total_files = len(inputs)
    idx_width = len(str(total_files))
    started_count = 0
    status_glyph = {"ok": "✓", "skipped": "○", "failed": "✗", "timeout": "⌛"}

    lock = asyncio.Lock()
    stop_event = asyncio.Event()

    async def persist_state() -> None:
        state["updated_at"] = _utc_now_iso()
        write_json_atomic(paths.state_path, state)

    async def worker(worker_id: int) -> None:
        nonlocal started_count
        worker_key = str(worker_id)
        while True:
            source_path = await queue.get()
            if source_path is None:
                async with lock:
                    state["workers"][worker_key]["status"] = "idle"
                    state["workers"][worker_key]["file"] = None
                    state["workers"][worker_key]["started_at"] = None
                    state["workers"][worker_key]["started_at_epoch"] = None
                    await persist_state()
                queue.task_done()
                return

            async with lock:
                started_count += 1
                idx = started_count
                state["workers"][worker_key]["status"] = "running"
                state["workers"][worker_key]["file"] = source_path.name
                state["workers"][worker_key]["started_at"] = _utc_now_iso()
                state["workers"][worker_key]["started_at_epoch"] = _now_epoch()
                await persist_state()

            # Single live-updating progress line per file: header + status
            # + two timers (total-elapsed / status-elapsed). Ticker keeps the
            # line fresh between events so the user always sees a moving clock.
            header = f"[{idx:>{idx_width}}/{total_files}]  {source_path.name}"
            file_progress: BatchFileProgress | None = None
            ticker_task: asyncio.Task | None = None
            if emit:
                file_progress = BatchFileProgress(
                    header=header,
                    on_tty=sys.stdout.isatty(),
                )
                file_progress.start()
                ticker_task = asyncio.create_task(_tick_loop(file_progress))

            try:
                result = await _process_one_file(
                    source_path,
                    config=config,
                    output_dir=output_dir,
                    store=store,
                    progress_callback=file_progress,
                )
            finally:
                if ticker_task is not None:
                    ticker_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await ticker_task

            async with lock:
                append_jsonl(paths.results_path, result)
                status = result["status"]
                state["progress"][status] += 1
                state["progress"]["done"] += 1
                state["workers"][worker_key]["status"] = "idle"
                state["workers"][worker_key]["file"] = None
                state["workers"][worker_key]["started_at"] = None
                state["workers"][worker_key]["started_at_epoch"] = None
                state["workers"][worker_key]["last_result"] = {
                    "status": status,
                    "source_path": result["source_path"],
                    "duration_seconds": result["duration_seconds"],
                }
                await persist_state()
                glyph = status_glyph.get(status, "•")
                if status == "ok":
                    out_name = Path(result["output_path"]).name
                    summary = f"→ {out_name} · {result['findings_count']} findings"
                elif status == "skipped":
                    summary = "skipped (output exists)"
                else:
                    summary = f"{result['error'] or 'unknown error'}"
                if emit and file_progress is not None:
                    final_line = file_progress.finalize(glyph=glyph, summary=summary)
                    log_line(final_line)
                else:
                    # No TTY progress (e.g. detached child) — construct the
                    # same one-line summary and log it (and echo if emit).
                    duration = fmt_duration(result["duration_seconds"])
                    line = (
                        f"[{idx:>{idx_width}}/{total_files}] {glyph} "
                        f"{source_path.name} · {summary} · {duration}"
                    )
                    if emit:
                        click.echo(line)
                    log_line(line)
            queue.task_done()

    async def reporter() -> None:
        # State.json is persisted after every worker transition in ``worker``;
        # that's what ``finding-extractor-batch status --watch`` consumes for
        # detached runs. This reporter exists only to keep state.json fresh
        # during idle periods (e.g. a single long-running chunk); it no longer
        # emits to stdout because per-file progress events now carry the
        # "what's happening" signal. See BatchFileProgress.
        while not stop_event.is_set():
            await asyncio.sleep(config.status_interval_seconds)
            async with lock:
                if state["status"] != "running":
                    continue
                await persist_state()

    reporter_task = asyncio.create_task(reporter())
    workers = [asyncio.create_task(worker(worker_id)) for worker_id in range(1, config.workers + 1)]
    error: str | None = None
    try:
        await queue.join()
        await asyncio.gather(*workers)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        raise
    finally:
        stop_event.set()
        await reporter_task
        if store is not None:
            await store.close()

        async with lock:
            if error:
                state["status"] = "failed"
                state["error"] = error
            elif state["progress"]["failed"] or state["progress"]["timeout"]:
                state["status"] = "completed_with_errors"
            else:
                state["status"] = "completed"
            state["ended_at"] = _utc_now_iso()
            await persist_state()

    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            paths.results_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    progress = state["progress"]
    run_started = state.get("started_at_epoch")
    total_elapsed = (
        _now_epoch() - run_started if isinstance(run_started, (int, float)) else 0.0
    )
    done_line = (
        "DONE  "
        f"ok={progress['ok']}  "
        f"skipped={progress['skipped']}  "
        f"failed={progress['failed']}  "
        f"timeout={progress['timeout']}  "
        f"total={fmt_duration(total_elapsed)}  "
        f"run_id={config.run_id}"
    )
    state_dir_line = f"      see {paths.base_dir}/ for per-file state"
    if emit:
        click.echo(done_line)
        click.echo(state_dir_line)
    log_line(done_line)
    log_line(state_dir_line)
    if log_handle is not None:
        log_handle.close()
    return 1 if state["progress"]["failed"] or state["progress"]["timeout"] else 0


run_engine_sync = runnify(run_engine)


def build_config_dict(config: BatchRunConfig) -> dict[str, Any]:
    return {
        "run_id": config.run_id,
        "mode": config.mode,
        "inputs": config.inputs,
        "output_dir": config.output_dir,
        "suffix": config.suffix,
        "model": config.model,
        "reasoning": config.reasoning,
        "exam_type": config.exam_type,
        "workers": config.workers,
        "timeout_seconds": config.timeout_seconds,
        "retries": config.retries,
        "validate": config.validate,
        "resume": config.resume,
        "store": config.store,
        "db_path": config.db_path,
        "status_interval_seconds": config.status_interval_seconds,
        "manifest_path": config.manifest_path,
        "run_dir": config.run_dir,
        "log_path": config.log_path,
    }


def config_from_dict(payload: dict[str, Any]) -> BatchRunConfig:
    return BatchRunConfig(
        run_id=payload["run_id"],
        mode=payload["mode"],
        inputs=list(payload["inputs"]),
        output_dir=payload.get("output_dir"),
        suffix=payload["suffix"],
        model=payload["model"],
        reasoning=payload.get("reasoning"),
        exam_type=payload.get("exam_type"),
        workers=int(payload["workers"]),
        timeout_seconds=int(payload["timeout_seconds"]),
        retries=int(payload["retries"]),
        validate=bool(payload["validate"]),
        resume=bool(payload["resume"]),
        store=bool(payload["store"]),
        db_path=payload["db_path"],
        status_interval_seconds=float(payload["status_interval_seconds"]),
        manifest_path=payload.get("manifest_path"),
        run_dir=payload["run_dir"],
        log_path=payload.get("log_path"),
    )


def resolve_run_options(
    *,
    mode: RunMode,
    workers: int | None,
    timeout_seconds: int | None,
    retries: int | None,
    status_interval_seconds: float | None,
    resume: bool | None,
    suffix: str | None,
    model: str | None,
    reasoning: str | None,
    exam_type: str | None,
    validate: bool,
    store: bool,
    db_path: Path | None,
    output_dir: Path | None,
    manifest: Path | None,
    run_dir: Path | None,
    run_id: str | None,
    input_files: list[Path],
    log_path: Path | None = None,
) -> BatchRunConfig:
    settings = get_settings()
    resolved_model = model or settings.default_model
    validate_model_id(resolved_model)
    effective_reasoning = resolve_runtime_reasoning(
        resolved_model,
        reasoning,
        allow_unknown_model_reasoning=settings.allow_unknown_model_reasoning,
    )

    resolved_workers = workers if workers is not None else settings.batch_workers
    resolved_timeout = (
        timeout_seconds if timeout_seconds is not None else settings.batch_timeout_seconds
    )
    resolved_retries = retries if retries is not None else settings.batch_retries
    resolved_status_interval = (
        status_interval_seconds
        if status_interval_seconds is not None
        else settings.batch_status_interval_seconds
    )
    resolved_resume = resume if resume is not None else settings.batch_resume
    resolved_suffix = suffix or settings.batch_output_suffix

    if not resolved_suffix.startswith("."):
        raise click.ClickException("Output suffix must start with '.' (example: .extracted.json)")

    resolved_db_path = (db_path or settings.db_path).resolve()
    resolved_run_dir = (run_dir or settings.batch_run_dir).resolve()
    resolved_output_dir = output_dir.resolve() if output_dir else None
    resolved_manifest = manifest.resolve() if manifest else None
    resolved_run_id = run_id or _make_run_id()
    if not _RUN_ID_PATTERN.match(resolved_run_id):
        raise click.ClickException(
            "Invalid run id. Use 1-128 chars from [A-Za-z0-9._-], starting with alphanumeric."
        )

    resolved_log = log_path.resolve() if log_path else None

    return BatchRunConfig(
        run_id=resolved_run_id,
        mode=mode,
        inputs=[str(path) for path in input_files],
        output_dir=str(resolved_output_dir) if resolved_output_dir else None,
        suffix=resolved_suffix,
        model=resolved_model,
        reasoning=effective_reasoning,
        exam_type=exam_type,
        workers=resolved_workers,
        timeout_seconds=resolved_timeout,
        retries=resolved_retries,
        validate=validate,
        resume=resolved_resume,
        store=store,
        db_path=str(resolved_db_path),
        status_interval_seconds=resolved_status_interval,
        manifest_path=str(resolved_manifest) if resolved_manifest else None,
        run_dir=str(resolved_run_dir),
        log_path=str(resolved_log) if resolved_log else None,
    )
