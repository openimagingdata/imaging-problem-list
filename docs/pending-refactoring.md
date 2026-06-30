# Pending Refactoring Backlog

Last updated: 2026-06-10
Status: Active

This is the canonical near-term refactoring/cleanup queue. Longer-horizon improvements live in `docs/future-improvements.md`.

## Open Items

| ID | Priority | Item | Origin |
|---|---|---|---|
| PR-005 | medium | Expand targeted tests for `extraction_review` label allowlist/reextract decisions, and model-catalog fallback regression. | `docs/archive/extractor-agent-roadmap.md` |
| PR-010 | low | Evaluate lightweight agent-instance caching per model only if profiling shows measurable benefit. | former `docs/code-review-2026-02-15.md` |
| PR-015 | low | Reconcile archived CLI persistence residuals: keep/retire `--store-include-validation` and confirm explicit `--store` failure/validation exit-code tests. | `docs/archive/persistence-cli-plan.md` |
| PR-019 | medium | Enforce migration discipline on direct API startup: avoid `create_all()`-bootstrapped unstamped schemas when running `finding-extractor-api` outside the Taskfile/Docker migration path. | PR review on `refactor/package-restructuring` |

## Recently Resolved (2026-03 Package Restructuring)

All items below were resolved during the package restructuring effort on `refactor/package-restructuring`:

- **PR-001/002**: Typed `ProgressCallback` Protocol and consolidated emit helpers (`extractor/progress.py`)
- **PR-003**: Reasoning workaround moved to provider settings layer (`resolve_runtime_reasoning()`)
- **PR-004/011**: Extracted `_build_review_callback()` helper; no passthrough chunk duplication found
- **PR-006**: Removed dead aggregate validation-success field
- **PR-007**: Inline orchestrator gate-semantics comments added
- **PR-008**: Unified all runtime modules to structlog
- **PR-009**: Removed dead `apply_coding` UI stage label
- **PR-012**: `examples/` is now a subpackage
- **PR-013/014**: Package restructuring (subpackages, `ExtractorSettings`, `ExtractorDeps` move)
- **PR-016**: Testing practices synced with conftest.py fixtures
- **PR-017**: `coding_summary.py` kept at top level (cross-cutting concern)
- **PR-018**: Dead `_resolve_coding_adjudicator_reasoning()` removed
- **PR-020**: Active-doc sweep completed; stale validation, callback, CLI module, local model/default, vLLM, and plan-status references corrected or archived.

## Scope Rules

- Add near-term cleanup/refactor items here.
- Keep longer-horizon improvements in `docs/future-improvements.md`.
- When an item is completed, move it to "Recently Resolved" and add a concise entry to `docs/DEV_LOG.md`.
