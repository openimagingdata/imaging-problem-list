"""Batch extraction CLI with local in-process workers.

V1 scope:
- local execution only (no broker/TaskIQ path)
- interactive and detached run modes
- status visibility from local run-state files
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import click

from finding_extractor.cli._local_only import (
    apply_cli_override,
    assert_local_only_model,
    print_manifest,
)
from finding_extractor.cli.batch_engine import (
    build_config_dict,
    collect_input_files,
    config_from_dict,
    resolve_run_options,
    run_engine_sync,
    validate_output_collisions,
)
from finding_extractor.cli.batch_state import (
    _TERMINAL_STATUSES,
    ensure_run_dir,
    initial_state,
    load_json,
    render_status,
    run_paths,
    write_json_atomic,
)
from finding_extractor.cli.runtime_budget import (
    DEFAULT_MAX_PREDICTED_RUNTIME_SECONDS,
    build_runtime_preflight,
)
from finding_extractor.core.config import get_settings
from finding_extractor.core.logging_setup import setup_logging
from finding_extractor.core.observability import configure_logfire


@click.group(name="finding-extractor-batch")
def cli() -> None:
    """Batch extraction workflows (local in-process v1)."""
    settings = get_settings()
    logfire_enabled = configure_logfire(runtime="cli")
    setup_logging(settings, include_logfire_processor=logfire_enabled)


@cli.command("run")
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path, exists=True))
@click.option(
    "--glob",
    "glob_pattern",
    default="*.txt",
    show_default=True,
    help="Pattern for directory inputs.",
)
@click.option(
    "--recursive/--no-recursive",
    default=False,
    show_default=True,
    help="Use recursive globbing for directory inputs.",
)
@click.option(
    "--mode",
    type=click.Choice(["interactive", "detached"], case_sensitive=False),
    default="interactive",
    show_default=True,
    help="Runtime mode.",
)
@click.option("--run-id", default=None, help="Optional run id (defaults to generated id).")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for output JSON files.",
)
@click.option("--suffix", default=None, help="Output suffix (defaults from settings).")
@click.option("--model", default=None, help="Model id override.")
@click.option(
    "--reasoning",
    type=click.Choice(["none", "minimal", "low", "medium", "high"], case_sensitive=False),
    default=None,
    help="Reasoning level override.",
)
@click.option("--exam-type", default=None, help="Optional exam description applied to all files.")
@click.option(
    "--workers", type=click.IntRange(min=1, max=64), default=None, help="Concurrent worker count."
)
@click.option(
    "--timeout-seconds", type=click.IntRange(min=10), default=None, help="Per-file timeout."
)
@click.option(
    "--retries", type=click.IntRange(min=0, max=10), default=None, help="Retries per file."
)
@click.option(
    "--max-predicted-runtime-seconds",
    type=click.IntRange(min=60),
    default=None,
    help=(
        "Fail fast if conservative runtime bound exceeds this value "
        "(default: 900 seconds)."
    ),
)
@click.option(
    "--allow-slow",
    is_flag=True,
    default=False,
    help="Override runtime guard and run even when the predicted bound is high.",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    show_default=True,
    help="Run post-extraction coverage analysis (verbatim checking is handled by the agent's output validator).",
)
@click.option(
    "--resume/--no-resume", default=None, help="Skip existing outputs (defaults from settings)."
)
@click.option(
    "--store/--no-store",
    default=False,
    show_default=True,
    help="Persist report/extraction rows to SQLite.",
)
@click.option(
    "--db-path", type=click.Path(path_type=Path), default=None, help="SQLite path for --store."
)
@click.option(
    "--status-interval-seconds", type=float, default=None, help="How often to print status updates."
)
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional JSONL copy of per-file results.",
)
@click.option(
    "--run-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for run state files.",
)
@click.option(
    "--local-only",
    is_flag=True,
    default=False,
    help="Enforce PHI-safe mode: only Ollama models on a local endpoint, no cloud fallback, no logfire.",
)
def run_command(
    inputs: tuple[Path, ...],
    glob_pattern: str,
    recursive: bool,
    mode: str,
    run_id: str | None,
    output_dir: Path | None,
    suffix: str | None,
    model: str | None,
    reasoning: str | None,
    exam_type: str | None,
    workers: int | None,
    timeout_seconds: int | None,
    retries: int | None,
    max_predicted_runtime_seconds: int | None,
    allow_slow: bool,
    validate: bool,
    resume: bool | None,
    store: bool,
    db_path: Path | None,
    status_interval_seconds: float | None,
    manifest: Path | None,
    run_dir: Path | None,
    local_only: bool,
) -> None:
    """Run batch extraction over files or directories."""
    if not inputs:
        raise click.ClickException("Provide at least one file or directory input.")

    # Apply --local-only + CLI --model override early so the Layer 1
    # validator sees the effective model (not just IPL_MODEL).
    apply_cli_override(local_only=local_only, model_override=model)

    input_files = collect_input_files(inputs, glob_pattern=glob_pattern, recursive=recursive)
    if not input_files:
        raise click.ClickException("No input files matched.")

    config = resolve_run_options(
        mode=mode,  # type: ignore[arg-type]
        workers=workers,
        timeout_seconds=timeout_seconds,
        retries=retries,
        status_interval_seconds=status_interval_seconds,
        resume=resume,
        suffix=suffix,
        model=model,
        reasoning=reasoning,
        exam_type=exam_type,
        validate=validate,
        store=store,
        db_path=db_path,
        output_dir=output_dir,
        manifest=manifest,
        run_dir=run_dir,
        run_id=run_id,
        input_files=input_files,
    )
    # Enforce local-only on the resolved model before any preflight/state-dir
    # creation so rejected runs leave no on-disk residue.
    settings = get_settings()
    if settings.local_only_mode:
        assert_local_only_model(config.model, settings, context="batch CLI --local-only")
        # Local extraction inherently exceeds the cloud-tuned 900s runtime
        # budget; auto-imply --allow-slow so users don't have to remember it.
        allow_slow = True
        print_manifest(
            config.model,
            settings,
            extras={"inputs": str(len(config.inputs))},
        )

    resolved_max_predicted_runtime = (
        max_predicted_runtime_seconds
        if max_predicted_runtime_seconds is not None
        else DEFAULT_MAX_PREDICTED_RUNTIME_SECONDS
    )
    preflight_line, preflight_error, preflight_warning = build_runtime_preflight(
        command_label="BATCH",
        item_label="inputs",
        item_count=len(config.inputs),
        workers=config.workers,
        timeout_seconds=config.timeout_seconds,
        retries=config.retries,
        budget_seconds=resolved_max_predicted_runtime,
        allow_slow=allow_slow,
    )
    click.echo(preflight_line)
    if preflight_error:
        raise click.ClickException(preflight_error)
    if preflight_warning:
        click.echo(preflight_warning, err=True)

    resolved_output_dir = Path(config.output_dir) if config.output_dir else None
    validate_output_collisions(input_files, output_dir=resolved_output_dir, suffix=config.suffix)
    paths = run_paths(Path(config.run_dir), config.run_id)
    ensure_run_dir(paths)
    write_json_atomic(paths.config_path, build_config_dict(config))

    click.echo(
        f"BATCH  run_id={config.run_id}  ·  {len(config.inputs)} inputs  ·  "
        f"workers={config.workers}  ·  model={config.model}  ·  "
        f"reasoning={config.reasoning or 'default'}  ·  mode={config.mode}"
    )

    if config.mode == "detached":
        starting_state = initial_state(config)
        starting_state["status"] = "starting"
        write_json_atomic(paths.state_path, starting_state)
        # Propagate local-only into the detached child so its Layer 1 validator
        # rejects any cloud fallback the same way the parent does.
        child_env = os.environ.copy()
        if settings.local_only_mode:
            child_env["IPL_LOCAL_ONLY"] = "true"
        with paths.log_path.open("a", encoding="utf-8") as log_handle:
            cmd = [
                sys.executable,
                "-m",
                "finding_extractor.cli.batch",
                "_run-child",
                "--run-config",
                str(paths.config_path),
            ]
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=os.getcwd(),
                env=child_env,
            )
        paths.pid_path.write_text(str(proc.pid), encoding="utf-8")
        click.echo(f"STARTED run_id={config.run_id} pid={proc.pid}")
        click.echo(
            f"STATUS  finding-extractor-batch status --run-id {config.run_id} --run-dir {config.run_dir}"
        )
        return

    exit_code = run_engine_sync(config=config, emit=True)
    if exit_code:
        raise SystemExit(exit_code)


@cli.command("status")
@click.option("--run-id", required=True, help="Run id to inspect.")
@click.option(
    "--run-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory containing run states.",
)
@click.option(
    "--watch/--no-watch",
    default=False,
    show_default=True,
    help="Continuously refresh status output.",
)
@click.option(
    "--interval-seconds", type=float, default=None, help="Watch interval (defaults from settings)."
)
def status_command(
    run_id: str, run_dir: Path | None, watch: bool, interval_seconds: float | None
) -> None:
    """Show batch run status from local state file."""
    settings = get_settings()
    resolved_run_dir = (run_dir or settings.batch_run_dir).resolve()
    resolved_interval = (
        interval_seconds if interval_seconds is not None else settings.batch_status_interval_seconds
    )
    paths = run_paths(resolved_run_dir, run_id)
    if not paths.state_path.exists():
        raise click.ClickException(f"Run state not found: {paths.state_path}")

    def print_once() -> dict:
        state = load_json(paths.state_path)
        click.echo(render_status(state, verbose=True))
        if state.get("error"):
            click.echo(f"ERROR {state['error']}")
        if state["status"] in _TERMINAL_STATUSES:
            click.echo(f"ENDED {state.get('ended_at')}")
        return state

    if not watch:
        print_once()
        return

    while True:
        state = print_once()
        if state["status"] in _TERMINAL_STATUSES:
            return
        time.sleep(resolved_interval)


@cli.command("_run-child", hidden=True)
@click.option("--run-config", type=click.Path(path_type=Path, exists=True), required=True)
def run_child_command(run_config: Path) -> None:
    """Internal: execute a detached run from a serialized config."""
    config_payload = load_json(run_config)
    config = config_from_dict(config_payload)
    exit_code = run_engine_sync(config=config, emit=True)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    cli()
