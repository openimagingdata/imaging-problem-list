"""Run-state directory/JSON helpers and status tracking for batch CLI."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

RunMode = Literal["interactive", "detached"]
_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed"}


@dataclass(frozen=True)
class RunPaths:
    base_dir: Path
    state_path: Path
    results_path: Path
    log_path: Path
    pid_path: Path
    config_path: Path


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_epoch() -> float:
    return time.time()


def run_paths(run_dir: Path, run_id: str) -> RunPaths:
    base_dir = run_dir / run_id
    return RunPaths(
        base_dir=base_dir,
        state_path=base_dir / "state.json",
        results_path=base_dir / "results.jsonl",
        log_path=base_dir / "log.txt",
        pid_path=base_dir / "pid",
        config_path=base_dir / "run_config.json",
    )


def ensure_run_dir(paths: RunPaths) -> None:
    paths.base_dir.mkdir(parents=True, exist_ok=True)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_duration(seconds: float) -> str:
    """Render ``seconds`` as a compact human-readable duration.

    Examples: ``58s``, ``2m 14s``, ``1h 3m``.
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        remainder_seconds = int(seconds - total_minutes * 60)
        return f"{total_minutes}m {remainder_seconds:02d}s"
    hours = total_minutes // 60
    remainder_minutes = total_minutes - hours * 60
    return f"{hours}h {remainder_minutes:02d}m"


def initial_state(config: Any) -> dict[str, Any]:
    """Create initial state.json structure from a BatchRunConfig."""
    workers = {
        str(worker_id): {
            "status": "idle",
            "file": None,
            "started_at": None,
            "started_at_epoch": None,
            "last_result": None,
        }
        for worker_id in range(1, config.workers + 1)
    }
    return {
        "run_id": config.run_id,
        "mode": config.mode,
        "status": "running",
        "started_at": _utc_now_iso(),
        "started_at_epoch": _now_epoch(),
        "ended_at": None,
        "updated_at": _utc_now_iso(),
        "error": None,
        "config": {
            "workers": config.workers,
            "timeout_seconds": config.timeout_seconds,
            "retries": config.retries,
            "validate": config.validate,
            "resume": config.resume,
            "store": config.store,
            "model": config.model,
            "reasoning": config.reasoning,
            "exam_type": config.exam_type,
            "suffix": config.suffix,
            "output_dir": config.output_dir,
            "db_path": config.db_path,
            "status_interval_seconds": config.status_interval_seconds,
            "manifest_path": config.manifest_path,
        },
        "progress": {
            "total": len(config.inputs),
            "done": 0,
            "ok": 0,
            "skipped": 0,
            "failed": 0,
            "timeout": 0,
        },
        "workers": workers,
    }


def render_status(state: dict[str, Any], *, verbose: bool = False) -> str:
    """Format run state for display.

    The default (``verbose=False``) is a single-line progress readout suitable
    for streaming updates during interactive runs. ``verbose=True`` returns
    the full multi-line form (used by ``batch status --watch``) that includes
    per-worker detail.
    """
    progress = state["progress"]
    now_epoch = _now_epoch()
    run_started = state.get("started_at_epoch")
    elapsed = (now_epoch - run_started) if isinstance(run_started, (int, float)) else 0.0

    running = [
        worker for worker in state["workers"].values() if worker["status"] == "running"
    ]

    if not verbose:
        bits = [
            f"~ {progress['done']}/{progress['total']}",
            f"ok {progress['ok']}",
            f"fail {progress['failed']}",
            f"skip {progress['skipped']}",
        ]
        if running:
            worker = running[0]
            started = worker.get("started_at_epoch")
            file_elapsed = (
                (now_epoch - started) if isinstance(started, (int, float)) else 0.0
            )
            bits.append(f"running {worker['file']} ({fmt_duration(file_elapsed)})")
        bits.append(f"{fmt_duration(elapsed)} elapsed")
        return "  ·  ".join(bits)

    lines = [
        (
            "RUN "
            f"id={state['run_id']} status={state['status']} "
            f"done={progress['done']}/{progress['total']} "
            f"ok={progress['ok']} skipped={progress['skipped']} "
            f"failed={progress['failed']} timeout={progress['timeout']}"
        ),
        f"UPDATED {state.get('updated_at')}",
    ]
    for worker_id, worker in sorted(state["workers"].items(), key=lambda item: int(item[0])):
        if worker["status"] == "running":
            started = worker.get("started_at_epoch")
            file_elapsed = (
                (now_epoch - started) if isinstance(started, (int, float)) else 0.0
            )
            lines.append(f"w{worker_id}: running {worker['file']} ({file_elapsed:.1f}s)")
        else:
            lines.append(f"w{worker_id}: idle")
    return "\n".join(lines)
