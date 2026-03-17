# Logging Usage

Operator-facing guide for runtime logging in the finding extractor stack.

## Quick Start

Use env vars to control log output:

```bash
export IPL_LOG_LEVEL=WARNING
export IPL_LOG_JSON=false
```

- `IPL_LOG_LEVEL`: `CRITICAL|ERROR|WARNING|INFO|DEBUG|NOTSET` (`WARN` accepted)
- `IPL_LOG_JSON`: set `true` for machine-readable JSON logs
- CLI: pass `--verbose` to elevate a single run to `INFO` without changing env defaults.

## Where Logging Is Configured

Logging is initialized once per process in all runtimes:

- API (`finding-extractor-api`)
- worker (`taskiq worker`)
- CLI (`finding-extractor`)
- batch CLI (`finding-extractor-batch`)
- eval CLI (`finding-extractor-eval`)

The worker should continue to run with TaskIQ `--no-configure-logging` so the project logging pipeline stays authoritative.

## Structured Context You Can Expect

Common context fields:

- `timestamp`
- `level`
- `logger`
- `event`

API request logs also include:

- `request_id`
- `http_method`
- `http_path`
- `trace_id` and `span_id` when OpenTelemetry span context is active

Worker extraction logs include:

- `job_id`
- `report_id`
- `extraction_id` for coding jobs

Reliability/modular diagnostics logs include:

- `terminal_status` (`failed` or `completed_with_warnings`)
- `public_error` (for terminal failures)
- warning counters:
  - `validation_error_count`
  - `coverage_warning_count`
  - `section_failure_count`
  - `dropped_findings_count`
  - `dropped_non_finding_count`

Primary events:

- `Modular pipeline diagnostics`
- `Reliability contract outcome`
- `Coding pipeline outcome`

Coding pipeline progress/status events include:

- `coding_fast_path`
- `coding_term_gen`
- `coding_search`
- `coding_selection`
- `coding_assembly`
- `coding_persist`
- `coding_complete`
- `coding_failed`

## Logfire

Logfire is optional and disabled by default.

```bash
export IPL_LOGFIRE_ENABLED=true
```

Related settings (`IPL_LOGFIRE_*`) are documented in `docs/configuration.md`.

## PHI-Safe Logging Rules

- Never log raw report text.
- Never log verbatim quote text from findings.
- Prefer IDs, counts, statuses, durations, and model names.
- Do not log coding-selector `reasoning` strings; persist them in extraction JSON only.

## Operational Alert Hooks

For reliability alerting, key on structured worker events:

1. strict modular terminal failures:
   - event: `Reliability contract outcome`
   - filter: `terminal_status=failed` and `public_error=extraction_failed:section_failures_remaining`
2. warning-rate monitoring:
   - event: `Reliability contract outcome`
   - filter: `terminal_status=completed_with_warnings`
   - aggregate `section_failure_count`, `coverage_warning_count`, `validation_error_count`
3. modular repair pressure:
   - event: `Modular pipeline diagnostics`
   - aggregate `remaining_failed_units`, `repair_attempts_used`, `total_unit_attempts`

## Related Docs

- `docs/configuration.md`
- `docs/logging-internals.md`
