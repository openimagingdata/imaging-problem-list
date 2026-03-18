# Pending Refactoring Backlog

Last updated: 2026-03-18
Status: Active

This is the canonical near-term refactoring/cleanup queue. Longer-horizon improvements live in `docs/future-improvements.md`.

## Open Items

| ID | Priority | Item | Origin |
|---|---|---|---|
| PR-005 | medium | Expand targeted tests for `extraction_review` label allowlist/reextract decisions, and model-catalog fallback regression. | `docs/archive/extractor-agent-roadmap.md` |
| PR-010 | low | Evaluate lightweight agent-instance caching per model only if profiling shows measurable benefit. | former `docs/code-review-2026-02-15.md` |
| PR-015 | low | Reconcile archived CLI persistence residuals: keep/retire `--store-include-validation` and confirm explicit `--store` failure/validation exit-code tests. | `docs/archive/persistence-cli-plan.md` |
| PR-019 | medium | Enforce migration discipline on direct API startup: avoid `create_all()`-bootstrapped unstamped schemas when running `finding-extractor-api` outside the Taskfile/Docker migration path. | PR review on `refactor/package-restructuring` |
| PR-020 | medium | Finish active-doc sweep after package restructuring; update remaining references to removed modules, renamed callbacks, and deleted `ValidationResult.is_valid` semantics. Detailed scope below. | PR review on `refactor/package-restructuring` |

## Detailed Scope for PR-020

Only active docs should be updated in this pass. Archived docs under `docs/archive/` are historical snapshots and do not need path/name cleanup.

1. `docs/api-internals.md`
- Replace the stale `api_models.py` reference with the current split: request/response contracts live in `api/schemas.py`; store/domain-to-response conversion lives in `api/mappers.py`.
- Update the `api/schemas.py` module description near the top so it no longer says the file contains mapping helpers.
- Review the app lifecycle section so it accurately describes current startup behavior: `create_app()` still calls `store.init()`, while the intended Alembic path is Taskfile/Docker migration preflight rather than API self-migration.

2. `docs/extraction-usage.md`
- Remove the stale statement that `--validate` always returns `is_valid=True`; `ValidationResult.is_valid` was removed and the output now consists of `verbatim_errors` plus `coverage_warnings`.
- Update the Python API example comment from `status_callback` to `progress_callback`.
- Re-read the validation semantics section to ensure it matches current runtime behavior: post-run validation can still produce verbatim errors, and strict reliability mode can fail the run on validation or unrecovered section failures.

3. `docs/eval-internals.md`
- Replace `batch_cli.py` references with the actual current module owning the behavior being described: `cli/batch.py` for Click entrypoints and `cli/batch_engine.py` for run-engine internals.
- Replace `eval_cli.py` with `cli/eval_cmd.py` anywhere the current eval CLI module is referenced.
- Recheck the “Adding a New Evaluator” section so file/module names line up with the current package layout.

4. `docs/coding-agent-design.md`
- Replace `llm_config.defaults` with `llm.defaults`.
- Replace `llm_config.providers` with `llm.model_settings`.
- Sweep the surrounding text for any other pre-restructure module paths or “validator redesign” wording that should now point at the current reviewer/model-settings vocabulary.

5. Cross-doc verification pass
- Run one final `rg` over active docs (excluding `docs/archive/`) for these stale terms: `api_models.py`, `llm_config`, `ValidationResult.is_valid`, `is_valid=True`, `status_callback`, `batch_cli.py`, and `eval_cli.py`.
- If a stale hit is intentional historical commentary, move that note to `docs/archive/` or reword it so it is clearly framed as historical context rather than current guidance.

## Recently Resolved (2026-03 Package Restructuring)

All items below were resolved during the package restructuring effort on `refactor/package-restructuring`:

- **PR-001/002**: Typed `ProgressCallback` Protocol and consolidated emit helpers (`extractor/progress.py`)
- **PR-003**: Reasoning workaround moved to provider settings layer (`resolve_runtime_reasoning()`)
- **PR-004/011**: Extracted `_build_review_callback()` helper; no passthrough chunk duplication found
- **PR-006**: Removed dead `ValidationResult.is_valid` field
- **PR-007**: Inline orchestrator gate-semantics comments added
- **PR-008**: Unified all runtime modules to structlog
- **PR-009**: Removed dead `apply_coding` UI stage label
- **PR-012**: `examples/` is now a subpackage
- **PR-013/014**: Package restructuring (subpackages, `ExtractorSettings`, `ExtractorDeps` move)
- **PR-016**: Testing practices synced with conftest.py fixtures
- **PR-017**: `coding_summary.py` kept at top level (cross-cutting concern)
- **PR-018**: Dead `_resolve_coding_adjudicator_reasoning()` removed

## Scope Rules

- Add near-term cleanup/refactor items here.
- Keep longer-horizon improvements in `docs/future-improvements.md`.
- When an item is completed, move it to "Recently Resolved" and add a concise entry to `docs/DEV_LOG.md`.
