# Testing Practices

Project-specific pytest conventions for this repository.

For generic pytest best practices, use `.agents/skills/pytest-testing-patterns/`.

## Scope

- This document is the source of truth for testing patterns that are specific to this codebase.
- `docs/archive/testing_plan.md` has the historical sequencing and rollout status.
- Test behavior truth still lives in `tests/` and runtime code.

## Primary Commands

Use `Taskfile.yml` as the workflow surface:

```bash
task lint              # Ruff lint + format check
task test              # Unit tests (excludes UI/integration by default)
task test:ui           # Playwright UI tests (run separately)
task test:api:e2e      # Backend API E2E against an already-running backend stack
task test:web:e2e      # Browser E2E against an already-running full stack
```

Compatibility aliases:

```bash
task test:smoke
task test:integration
```

For targeted local iteration:

```bash
uv run pytest tests/test_api.py -q
```

## Test Topology

- Core backend behavior:
  - `tests/test_store.py`
  - `tests/test_api.py`
  - `tests/test_tasks.py`
- CLI and batch/eval command behavior:
  - `tests/test_cli.py`
  - `tests.test_batch_cli`
  - `tests.test_eval_cli`
- Config/policy/catalog contracts:
  - `tests/test_config.py`
  - `tests/test_model_policy.py`
  - `tests/test_model_catalog.py`
- UI and integration:
  - `tests/test_ui.py`
  - `tests/test_integration.py`

## Shared Fixture Catalog (`tests/conftest.py`)

### Autouse Fixtures

These run automatically for every test — no fixture argument needed.

#### `_clear_cached_settings` (autouse, function scope)

- Purpose: prevent settings cache leakage across tests that mutate env vars.
- Calls `clear_settings_cache()` before and after each test.

#### `_block_model_requests` (autouse, function scope)

- Purpose: prevent real LLM API calls in non-integration tests.
- Uses `pydantic_ai.models.override_allow_model_requests(False)` to block outbound model requests.
- Skipped for tests decorated with `@pytest.mark.integration`.

### Opt-in Fixtures

#### `context_capture_logger` (function scope)

- Returns: `ContextCaptureLogger`
- Purpose: capture structlog event kwargs plus active contextvars in logging tests.
- Each record in `.records` is a dict: `{"level": str, "event": str, "kwargs": dict, "context": dict}`.
- Methods: `.info()`, `.debug()`, `.warning()`, `.exception()` — each appends a record.

#### `cli_runner` (function scope)

- Returns: `click.testing.CliRunner`
- Purpose: shared CLI runner for CLI/batch/eval test modules.

#### `store_factory` (function scope)

- Returns: async context-manager factory that yields initialized `ExtractionStore`.
- Purpose: consistent async store setup/teardown across store/API/task tests.
- Usage:
  ```python
  async with store_factory(tmp_path / "test.db") as store:
      await store.upsert_report(...)
  ```

#### `runtime_logging_spy` (function scope)

- Returns: `RuntimeLoggingSpy`
- Purpose: patch and capture startup `configure_logfire(...)` and `setup_logging(...)` calls.
- `.patch(monkeypatch, module_path, *, logfire_enabled: bool)` — patches `configure_logfire` and `setup_logging` on the given module path.
- `.configure_calls` — list of dicts: `{"runtime": str, "enabled_override": bool | None, "fastapi_app": Any}`.
- `.setup_calls` — list of dicts: `{"settings": ExtractorSettings, "include_logfire_processor": bool}`.

## Pattern Rules For This Repo

1. Promote fixtures to `tests/conftest.py` only when reused by 2+ modules or clearly global.
2. Keep API-specific app/client fixtures local to API tests unless reuse becomes real.
3. Keep assertions explicit at callsites for startup/logging wiring tests.
4. Use per-test DB paths or explicit wrappers when store tests need filename clarity.
5. Keep log assertions PHI-safe and metadata-focused.

## Anti-Patterns (Repository-Specific)

1. Importing helper fixtures from `tests.<module>` paths instead of pytest fixture discovery.
2. Creating new global fixtures for one-off local test setup.
3. Adding hidden side effects to autouse fixtures.
4. Reintroducing direct duplicate setup already covered by `cli_runner`, `store_factory`, or `runtime_logging_spy`.

## Update Policy

1. Any new shared fixture in `tests/conftest.py` must be documented here.
2. Any removed/renamed shared fixture must be updated here in the same change.
3. If guidance is generic pytest advice, move it to `.agents/skills/pytest-testing-patterns/` and keep this file focused on repo specifics.

## Related Docs

- Plan and slice status (historical): `docs/archive/testing_plan.md`
- Dev history: `docs/DEV_LOG.md`
- Agent onboarding: `AGENTS.md`
- Contributor architecture map: `CLAUDE.md`
