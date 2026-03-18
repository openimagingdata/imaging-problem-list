# Development Log

Older entries through 2026-02-17 are archived in [archive/dev-log-through-2026-02-17.md](archive/dev-log-through-2026-02-17.md).

---

## 2026-03-18 — Fix TaskIQ worker registration for coding jobs

Fixed the real worker process command so TaskIQ loads both
`worker/extraction_jobs.py` and `worker/coding_jobs.py`. The API and worker task
modules already supported coding dispatch, but the Docker/local worker command
only registered extraction tasks, which would leave queued coding jobs
unconsumed in the live TaskIQ path.

Updated both `docker-compose.yml` and the non-Docker worker runbook in
`docs/dev-ops.md` to include the coding task module.

---

## 2026-03-18 — Coding agent production validation and tuning

Ran the production `run_coding()` pipeline against real extraction data with
full Logfire instrumentation. Verified end-to-end span tree, per-agent token
accounting, and cost tracking are all working and queryable in Logfire.

Key changes from production testing:

1. **Split-model architecture**: Term generators now use
   `gemini-3-flash-preview` (no reasoning) while code selectors use
   `gpt-5.2` (reasoning: low). Logfire traces showed gpt-5.2 was spending
   reasoning tokens on term generation with no quality benefit. New config
   setting `IPL_CODING_TERM_MODEL` controls this independently.

2. **Concurrency tuned to 8**: Bumped `MAX_CONCURRENCY` from 5 to 8.
   Phase 4 (code selection) dropped from 20.1s to 13.9s (31% improvement)
   with no rate limit issues. Total pipeline wall clock: 27.5s for 26
   findings ($0.13 total cost).

3. **Production coding CLI**: Added the `finding-extractor-code` command as
   a first-class wrapper over `coding.run_coding()`, following the existing
   CLI convention of sending progress to stderr while writing result JSON to
   stdout or `--output`.

4. **Docs sync**: Updated `coding-agent-design.md` (split-model
   architecture, concurrency tuning, production run profile),
   `coding-agent-prompts.md` (no report text, instructions not
   system_prompt), `configuration.md` (all `IPL_CODING_*` env vars),
   `logging-usage.md` (coding-specific structured context).

Production run profile (26-finding chest X-ray, split models, concurrency 8):
- 11 fast-path finding codes, 11 fast-path location codes
- 29 LLM calls total (2 term gen + 13 finding selectors + 14 location selectors)
- 20 findings coded, 6 unresolved (ontology gaps)
- $0.131 total cost, 27.5s wall clock

---

## 2026-03-16 — Coding agent architecture implementation

Implemented the post-extraction coding pipeline as a first-class runtime flow.
Added the new `finding_extractor.coding` package (prompt builders, typed LLM
outputs, agent factories, runtime orchestrator), a TaskIQ coding worker, and
the `POST /api/extractions/{id}/code` endpoint to run coding independently from
extraction.

Extended extraction persistence to store inline coding results plus coding
provenance metadata (`coding_model`, `coding_reasoning`, timing, trace ID).
Folded those extraction columns into the existing baseline Alembic migration
and updated migration tests to assert the new schema and current head revision.

Added coding-specific logging/docs updates and targeted test coverage for coding
types, prompt builders, fast-path runtime behavior, config settings, model
compatibility shims, and the coding API path.

Follow-up review fixes tightened the runtime in two places: location grouping
now keeps laterality-distinct findings separate, and batched term generation now
backfills deterministic fallback terms for any omitted items before search so
partial LLM outputs do not silently force findings unresolved.

Additional cleanup from follow-up review consolidated duplicated TaskIQ job
helpers into a shared worker utility module, added typed Protocols for coding
prompt candidates, clarified the synchronous location fast-path lookup, and
expanded regression coverage for invalid selector IDs, no-candidate location
paths, bilateral fallback terms, and the coding API's missing-extraction case.

---

## 2026-03-16 — Per-chunk pipeline, Logfire observability, review prompt fix

Replaced the sequential extract-all → merge → review-all orchestration with a
per-chunk pipeline: each chunk runs extract → review → correct as an independent
unit, parallelized via `asyncio.TaskGroup`. Reviews now start as soon as each
chunk extraction completes, overlapping with other extractions.

Other changes:
- Added Logfire span instrumentation (`observation_span()` helper) for
  hierarchical trace visibility across pipeline stages
- Scoped review prompt to finding-level evaluation (name, presence, location)
  to prevent reviewer from flagging missing attributes
- Removed `IPL_EXTRACTOR_CHUNK_REPAIR_ENABLED` — redundant given PydanticAI's
  built-in output retries + FallbackModel
- Upgraded pydantic-ai 1.67.0 → 1.68.0
- Suppressed HuggingFace Hub auth warning during semantic chunking

---
## 2026-03-12 — Test workflow: explicit API/Web E2E task names

Renamed the higher-level test tasks to make their scope obvious:
`task test:api:e2e` for the backend API workflow and `task test:web:e2e` for
the browser-driven extractor UI flow through Caddy. Kept `task test:smoke` and
`task test:integration` as compatibility aliases.

Both tasks fail fast if the expected stack is not already running, instead of
trying to manage service lifecycle implicitly. API E2E checks `/api/readyz` on
the backend stack, while web E2E checks both `http://localhost:8080/` and the
proxied `http://localhost:8080/api/readyz`.

Aligned `tests/test_integration.py` with that contract: the Playwright fixture
no longer auto-starts or tears down Docker Compose, and now fails with a clear
instruction to run `task stack:up:full` first. Updated developer-facing docs to
match the new workflow surface.

Verification:
- `task --summary test:api:e2e`
- `task --summary test:web:e2e`

---

## 2026-03-12 — FI-008 shared read-model consolidation

Implemented the clean-break FI-008 refactor for the pure-mirror persistence/API
read paths. Added `read_models.py` as the shared report/extraction DTO module,
removed `StoredReport*` / `StoredExtraction*`, and updated the store to return
`ReportSummary`, `ReportDetail`, `ExtractionSummary`, and `ExtractionDetail`
directly. Report/extraction API routes now use those shared models as their
response contracts instead of re-wrapping store results through mappers.

Promoted `PipelineDiagnostics` to the canonical cross-layer Pydantic model and
deleted the mirrored `PipelineDiagnosticsResponse` API wrapper. Jobs,
corrections, users, and model catalog responses intentionally remain
mapper-driven because those endpoints still rename, enrich, or redact fields.

Added test coverage to assert the new shared read-model return types in store
tests and to verify extraction detail API payloads include `pipeline_diagnostics`
and `trace_id`, closing the drift gap that motivated FI-008.

Verification:
- `uv run pytest tests/test_store.py tests/test_api.py -q`

---

## 2026-03-12 — Base user seeding, Taskfile fixes, doc archival

Replaced hardcoded user identity in API startup with `base_users.json` file
loading. The API lifespan searches cwd, `/app/`, and project root for the file
and upserts any users found (with structured logging). Dockerfile copies the
file into the container image using a glob pattern that silently skips if absent.

Fixed Taskfile `stack:up` / `stack:up:full` to build Docker images before
running Alembic migrations (previously migrations ran against the old image).
Updated 3 stale Alembic revision references (`17f8ebc6c608` → `3d867b54ee78`).
Deleted superseded `extractor/orchestrator.py` (replaced by `orchestrator/`
subpackage in earlier commit).

Added 3 missing test files to `test:unit` target: `test_chunk_prompt.py`,
`test_impression_list_chunker.py`, `test_model_resilience.py` (602 tests, up
from 588).

Folded planning doc content into reference docs and archived completed plans:
- `persistence-internals.md`: added Design Rationale section, fixed migration
  history to single baseline
- `extraction-internals.md`: inlined orchestrator workflow steps and chunking
  config table
- `pending-refactoring.md`: cleaned resolved items, added PR-019/PR-020
- Archived: `package-restructuring-plan.md`,
  `persistence-and-orchestrator-decomposition-plan.md`,
  `semantic-chunking-plan.md`, `extractor-agent-roadmap.md`,
  `extractor-agent-plans/`
- Fixed stale references in `eval-internals.md` and `api-usage.md`

Verification:
- `task lint && task test` (602 passed)
- `task test:smoke` (passed on fresh DB)
- `task test:integration` (13/13 passed)

---

## 2026-03-12 — API startup migration preflight

Aligned API startup with the existing CLI migration discipline. `create_app()`
now calls `check_migration_current()` before `store.init()` and fails fast on
an unstamped or outdated DB with an actionable error pointing to
`task db:migrate` / `task stack:up`, preventing `finding-extractor-api` from
silently bootstrapping an unstamped schema via `create_all`.

Updated the shared test `store_factory` fixture to upgrade temp SQLite DBs to
Alembic head before yielding an `ExtractionStore`, so API/task/store tests now
exercise the supported migrated-schema path. Added an API regression test
covering unmigrated-startup failure and verified no app tables are created as a
side effect.

Docs updated to match the new contract: `api-internals.md`,
`schema-migrations.md`, `persistence-internals.md`, and `dev-ops.md`.

Verification:
- `task lint`
- `task test`

---

## 2026-03-11 — Post-review cleanup: stale doc names, callback type safety

Fixed stale `ReportExtraction` / `ChunkExtraction` type names in 7 active docs
files (extraction-internals, extraction-usage, eval-internals, eval-usage,
persistence-usage, human-review-workflow, extractor-agent-roadmap). Fixed stale
`providers` → `model_settings` in `llm/__init__.py` docstring. Tightened
`_build_review_callback()` parameter from `str | None` to `str`, removing
runtime assert in favor of compile-time type safety.

---

## 2026-03-11 — Fixture-catalog docs sync (PR-016)

Synced `docs/testing-practices.md` with `tests/conftest.py`: documented
`_block_model_requests` autouse fixture, `ContextCaptureLogger.records`
structure, `RuntimeLoggingSpy.patch()` signature with `.configure_calls` and
`.setup_calls` details, and `store_factory` async usage example. Reorganized
fixture catalog into autouse and opt-in sections.

---

## 2026-03-11 — Extractor UI status audit (PR-009)

Removed dead `apply_coding` stage label from `extractor-ui/app.js` (coding
pipeline decoupled; stage never emitted). Audited remaining stages: `queued`
(emitted in `db/store.py`), `persist` (emitted in `runtime.py`), and all others
confirmed in active use. Dual `status_message`/`status_event` handling and
`retry_after` fallback verified as correct.

---

## 2026-03-11 — Extract review callback helper (PR-004), close PR-011

Extracted `_build_review_callback()` from nested closure in
`run_extraction_runtime()` to a module-level helper in `runtime.py`. Removes
closure-captured state in favor of explicit parameters. Closed PR-011 (no
actual duplication found — passthrough chunk helper exists only once).

---

## 2026-03-11 — Orchestrator gate semantics comments (PR-007)

Added inline comments to orchestrator subpackage documenting non-obvious control
flow: section selection (no conditional gating), cross-section dedup key logic,
non-fatal exam-info failure fallback, and silent reextract disable.

---

## 2026-03-11 — Unify stdlib logging to structlog (PR-008)

Migrated `extractor/agent.py`, `extractor/chunking.py`, `extractor/runtime.py`,
and `api/routes.py` from stdlib `logging` to `structlog.get_logger()`. Unified
dual-logger pattern in `routes.py` to single structlog logger. Converted
`extra={}` dict pattern to structlog keyword args.

---

## 2026-03-11 — Decompose persistence internals and orchestrator package

Refactored `db/store.py` into a thin public `ExtractionStore` facade over new
domain modules: `db/engine.py`, `db/reports.py`, `db/extractions.py`,
`db/jobs.py`, `db/corrections.py`, and `db/users.py`. Kept `ExtractionStore`
as the public persistence boundary; did not introduce repository-pattern
abstractions. Re-exported `StoredUser` from package roots.

Replaced the monolithic extractor orchestrator file with a real
`extractor/orchestrator/` subpackage: `__init__.py` as the public facade,
`run.py` as the workflow coordinator, and `types.py`, `chunks.py`, `merge.py`,
`review.py` for internal orchestration mechanics. Narrowed the public
orchestrator surface back down to the actual entrypoint/result/review types;
internal runtime/review code now imports type aliases from
`orchestrator/types.py` instead of through the facade.

Updated targeted tests for the new internal package path and refreshed
architecture/internal docs: `AGENTS.md`, `CLAUDE.md`, `api-internals.md`,
`extraction-internals.md`, `persistence-internals.md`, and
`schema-migrations.md`. Added
`persistence-and-orchestrator-decomposition-plan.md` to capture the intended
shape.

Verification:
- `task lint`
- `task test`

---

## 2026-03-11 — Backlog: typed callback Protocol, consolidated emit helpers, remove dead is_valid

Created `extractor/progress.py` with `ProgressCallback` Protocol (PR-001),
`ProgressCallbackType` alias, and shared `emit_stage_progress()` /
`format_stage_status()` helpers (PR-002). Removed duplicate definitions from
`orchestrator.py` and `runtime.py`. Removed dead `ValidationResult.is_valid`
field (PR-006) — all callers now check `len(verbatim_errors) == 0` directly.
Updated tests and CLI display logic. Marked PR-001, PR-002, PR-006 resolved.

---

## 2026-03-11 — Post-review cleanup: naming completeness, docs, dead code

Completed `status_callback` → `progress_callback` rename across all public
parameters (runtime, agent, CLI, worker, eval, tests). Deleted `StatusCallback`
compatibility alias. Removed dead `extract_findings()` legacy function from
`agent.py` and its test. Renamed `report_chunk` parameter → `chunk_text` in
`review.py`, `runtime.py`, `orchestrator.py`, and tests. Moved health endpoints
(`/api/healthz`, `/api/readyz`) and `_assert_broker_ready` from
`api/__init__.py` to `api/routes.py`, slimming `__init__.py` to factory +
middleware + main. Added `review` stage label to `extractor-ui/app.js`. Updated
`validator_review` → `review` in `extraction-internals.md`. Comprehensive docs
sweep: fixed stale module paths in `extraction-internals.md`,
`logging-internals.md`, `dev-ops.md`, `report-sections.md`,
`persistence-usage.md`, `persistence-internals.md`, `api-internals.md`,
`model-selection-notes.md`. Updated CLAUDE.md repository structure. Marked
PR-012/013/014/017 resolved in `pending-refactoring.md`.

---

## 2026-03-11 — Track 3c: API + persistence renames, Alembic reset, ty fixes

API/persistence naming cleanup: `exam_description` → `study_description`,
`exam_description_hint` → `study_description_hint`, `coding_coded_count` →
`coded_finding_count`, `coding_unresolved_count` → `unresolved_finding_count`.
Renamed `exam_name` → `study_description` in review prompts, `exam_description`
→ `study_description` in eval models/datasets. Made `ExtractionRow.finding_count`
non-nullable (default 0). Collapsed all Alembic migrations into single baseline
`3d867b54ee78`. Renamed `"validator_review"` stage strings → `"review"`.

Fixed all 6 pre-existing `ty` type errors: used typed `BetaThinkingConfig*Param`
constructors instead of plain dicts in `llm/model_settings.py`; typed
`ANTHROPIC_EFFORT_MAP` with `Literal`; made `StoredExtraction.study_description`
nullable and `finding_count` non-nullable to match DB schema.

Updated `extractor-ui/app.js`, eval datasets, and docs (`api-usage.md`,
`eval-internals.md`, `persistence-internals.md`, `extraction-usage.md`,
`frontend-internals.md`, `schema-migrations.md`).

---

## 2026-03-11 — Track 3b: Rename validator_* to reviewer_*

Standardized reviewer vocabulary: renamed `validator_review_enabled` →
`reviewer_enabled`, `validator_model` → `reviewer_model`,
`validator_reasoning` → `reviewer_reasoning`,
`validator_reextract_enabled` → `reviewer_reextract_enabled`. Renamed env vars
`IPL_VALIDATOR_*` → `IPL_REVIEWER_*`. Updated `PipelineDiagnostics` fields
(`validator_requested_chunks` → `reviewer_requested_chunks`,
`validator_reextracted_chunks` → `reviewer_reextracted_chunks`). Renamed
`_resolve_validator_model_name()` → `_resolve_reviewer_model_name()`. Updated
`config.toml.example`, `docs/configuration.md`, and `docs/extraction-internals.md`.

---

## 2026-03-11 — Track 3a: Internal type/function naming cleanup

Internal naming cleanup: `ReportExtraction` → `ExtractedReportFindings`,
`ExtractedFinding` → `Finding`, `ChunkExtraction` → `ExtractedChunkFindings`.
Renamed result fields (`.extraction` → `.report_findings`/`.chunk_findings`),
callback types (`EmitStatusFn` → `ProgressCallbackFn`, `emit_status()` →
`emit_progress()`), and pipeline result types (`OrchestratedExtractionResult` →
`OrchestrationResult`, `RuntimeResult` → `PipelineRunResult`,
`ReportChunk.report_chunk` → `.text`). Moved `ExtractorDeps` to
`extractor/agent.py`. Renamed `Settings` → `ExtractorSettings`.

---

## 2026-03-11 — Track 2c: Split cli/batch.py into engine + state

Split `cli/batch.py` (923→3 files): CLI entrypoints stay in `batch.py`,
run engine/processing to `batch_engine.py`, state/directory helpers to
`batch_state.py`. Dropped underscore prefixes from public functions
(`_resolve_run_options` → `resolve_run_options`, etc.).

---

## 2026-03-11 — Track 2b: Split api/schemas.py, extract mappers

Split `api/schemas.py`: extracted `map_*` conversion functions and private
helpers (`_parse_status_event`, `_pipeline_diagnostics_response`, etc.) to
`api/mappers.py`. Request/response models stay in `schemas.py`.

---

## 2026-03-11 — Track 2a: Split db/store.py, extract tables

Split `db/store.py`: extracted SQLModel table classes (`ReportRow`,
`ExtractionRow`, `CorrectionRow`, `JobRow`, `UserRow`) to `db/tables.py`.
Store facade and `Stored*` dataclasses remain in `db/store.py`. Updated
`alembic/env.py` to import `tables` instead of `store`.

---

## 2026-03-11 — Track 1e: Rename llm_config/ → llm/

Renamed `llm_config/` → `llm/`. Renamed `providers.py` → `model_settings.py`.
Updated all imports (24 files).

---

## 2026-03-11 — Track 1d: Create db/ subpackage, consolidate extractor/

Created `db/` subpackage (moved `store.py`; `db/__init__.py` re-exports public
types). Updated `alembic/env.py`. Moved text-processing modules into `extractor/`:
`report_sections.py`, `semantic_chunking.py` (→ `chunking.py`),
`impression_list_chunker.py` (→ `impression_chunker.py`), `prompt.py`, `verbatim.py`.

---

## 2026-03-11 — Track 1c: Create worker/ and cli/ subpackages

Created `worker/` subpackage (`broker.py`, `tasks.py` → `extraction_jobs.py`)
and `cli/` subpackage (`cli.py` → `extract.py`, `batch_cli.py` → `batch.py`,
`eval_cli.py` → `eval_cmd.py`, `runtime_budget.py`). Updated `docker-compose.yml`
worker command and `pyproject.toml` entry points. Fixed all string-based
monkeypatch references in tests.

---

## 2026-03-11 — Track 1b: Create api/ subpackage

Created `api/` subpackage. Moved `api.py` (→ `api/__init__.py`), `api_routes.py`
(→ `routes.py`), `api_models.py` (→ `schemas.py`), `api_services.py`
(→ `services.py`), `api_dependencies.py` (→ `dependencies.py`). Entry point
`finding_extractor.api:main` and uvicorn ref `finding_extractor.api:app`
unchanged (both resolve to `api/__init__.py`).

---

## 2026-03-11 — Track 1a: Create core/ subpackage

Created `core/` subpackage. Moved `config.py`, `base.py` (→ `base_model.py`),
`logging_setup.py`, `observability.py` into `core/`. Updated all imports
(26 files across src/ and tests/). `core/__init__.py` is kept slim (no
re-exports) to avoid circular imports with `models.py`.

---

## 2026-03-11 — Package restructuring: Phase 0 setup

Package restructuring: added canonical plan (`docs/package-restructuring-plan.md`).
Removed superseded planning docs (`codebase-cleanup-plan.md`,
`package-restructuring-plan-review-2026-03-11.md`). Archived
`agent-restructuring.md`. Marked PR-013/014/017 active in
`pending-refactoring.md`.

---

## 2026-03-10 — Fix Anthropic Opus 4.6+ adaptive thinking

Upgraded pydantic-ai (1.50→1.67) and anthropic SDK (0.77→0.84). Fixed
`build_anthropic_settings()` to use adaptive thinking with `anthropic_effort`
for Opus 4.6+ models instead of the deprecated `budget_tokens` extended
thinking. Pre-4.6 models (Sonnet 4.5, etc.) retain budget-based thinking.

Added `anthropic_model_minor()` to `policy.py` for version detection.
Removed deprecated `BetaThinkingConfig*` SDK type imports.

---

## 2026-03-01 — Sync persistence store with extraction pipeline

Synchronized the persistence layer with the current extraction pipeline output.
The store now surfaces exam metadata in summary views, persists pipeline
diagnostics, and captures Logfire trace IDs for prompt reproducibility.

1. **Exam info in summary views**: `StoredExtraction` and
   `ExtractionSummaryResponse` now include `study_description`, `modality`,
   `body_region`, `body_part`, `contrast`, `laterality`, and `finding_count`.
   `study_description` and `finding_count` are required fields (backfilled
   from `extraction_json` in the migration for existing rows). Previously
   these were only accessible via the detail payload.

2. **Coding count denormalization**: `coding_coded_count` and
   `coding_unresolved_count` are computed at persist time, eliminating JSON
   deserialization from the summary path.

3. **Pipeline diagnostics persisted**: `PipelineDiagnostics` (chunk counts,
   repair stats, validator stats) serialized to `diagnostics_json` and
   returned in `ExtractionDetailResponse`.

4. **Logfire trace_id linkage**: The runtime captures the current
   OpenTelemetry trace ID at persist time via `get_current_trace_id()` in
   `observability.py`. Combined with Logfire's prompt+response capture,
   this provides extraction reproducibility without duplicating prompts.

5. **Domain type cleanup**: Moved `PipelineDiagnostics` from
   `extractor/orchestrator.py` to `models.py`. Consolidated OTel trace
   capture into the shared `observability.py` helper (used by both
   `runtime.py` and `api.py`).

6. **DB migration**: `e1a3b5c7d9f2` adds 6 nullable columns to
   `extractions` and backfills `study_description`/`finding_count`.

---

## 2026-02-26 — Exam info sub-agent improvement

Tightened the exam info sub-agent to return specific, structured metadata
instead of vague results like "Radiological Study". Live-tested on all 10
sample reports — 10/10 correct metadata, 8/10 study dates extracted (2
correctly null where reports have no date header).

1. **Constrained types**: Added `Modality`, `BodyRegion`, `Contrast` Literal
   type aliases in `models.py`. `ExamInfo.modality` now uses `Modality` instead
   of `str`. Added `body_region: BodyRegion | None` and `contrast: Contrast | None`
   fields. `FindingLocation.body_region` reuses the shared `BodyRegion` alias.

2. **study_date extraction**: Added `study_date: date | None` to
   `ExamInfoExtraction` and mapped it through to `ExamInfo` (pre-existing gap —
   the field existed on `ExamInfo` but was never populated by the sub-agent).

3. **Directive prompt with examples**: Replaced minimal 4-sentence prompt with
   detailed instructions covering priority-of-evidence, modality code mapping,
   body_region mapping, contrast semantics, study_description format, anti-patterns,
   and 5 few-shot examples (CT, XR, MR, US with various body regions, contrast,
   and study_date including a null-date case).

4. **Simplified report context**: Removed complex `_build_exam_info_report_headers`
   function (section parsing + fallback logic). Now uses simple first-20-lines
   of report text.

5. **Downstream updates**: CLI, validator review, store (new DB columns + migration),
   eval datasets (fixed `body_region` bug using `.body_part` instead of `.body_region`),
   prompt.py OUTPUT_FORMAT_BLOCK (stale ExamInfo field list).

6. **DB migration**: `d4f2a8b1c6e3` adds nullable `body_region` and `contrast`
   columns to `extractions` table.

---

## 2026-02-25 — Agent refactor: naming, reasoning cleanup, subpackages

Rationalized naming, consolidated reasoning resolution, and restructured the
package into `llm_config/` and `extractor/` subpackages.

1. **Naming rationalization:** Aligned extraction-side naming with validator
   chunk-scoped conventions. `SectionExtractionUnit` → `ReportChunk`,
   `SectionExtractionOutcome` → `ChunkExtractionOutcome`. All field, parameter,
   local variable, and status-event references updated from "unit" to "chunk"
   vocabulary throughout orchestrator, runtime, tasks, and tests.

2. **Reasoning resolution cleanup:** Removed redundant `resolve_effective_reasoning()`.
   Purified `get_model_settings()` to be a pure builder (returns `None` when
   reasoning is `None`). Consolidated all runtime reasoning resolution onto
   `resolve_runtime_reasoning()`.

3. **`llm_config/` subpackage:** Moved `model_defaults.py`, `model_policy.py`,
   `model_catalog.py`, `model_resilience.py`, `providers.py` into
   `src/finding_extractor/llm_config/`. Clean-break migration — no re-export shims.

4. **`extractor/` subpackage:** Moved `extraction_orchestrator.py`,
   `extraction_agent.py`, `extraction_runtime.py`, `extraction_review.py`,
   `exam_info_agent.py` into `src/finding_extractor/extractor/`. Clean-break
   migration — no re-export shims.

5. **Documentation:** Updated CLAUDE.md structure, extraction-internals.md module
   paths and vocabulary, coding-agent-design.md references, pending-refactoring.md
   (PR-003 resolved, PR-013 providers.py resolved), semantic-chunking-plan.md,
   agent-restructuring.md, and report-sections.md/extraction-usage.md import paths.

Verification: lint clean, 561 tests passing.

## 2026-02-23 — Decouple coding from extraction pipeline

Stripped all inline OIFM coding from the extraction path. Coding is now an
independent tool, triggered separately from extraction.

1. **Design doc:** Created `docs/coding-agent-design.md` capturing architecture
   (3-call LLM pipeline), index search strategy, prompt design principles,
   response models, independent job design, and lessons learned from prototyping.
2. **Extraction stripping:** Removed `ApplyCodingFn` wiring, `coding_enabled` and
   all `coding_*` config fields, worker shutdown hook, dead `on_outcome` parameter
   from orchestrator.
3. **Deleted files:** `batch_coding.py`, `batch_coding_agents.py`, `code_assigner.py`,
   `coding_agents.py` (and their tests).
4. **Archived:** `finding-and-location-code-assignment-plan.md` moved to `docs/archive/`.
5. **Backlog updates:** Added PR-017 (move `coding_summary.py` to presentation layer),
   FI-012 (independent coding agent testability). Removed completed/superseded items.
6. **Branch:** Created `coding-agent` worktree for standalone coding agent implementation.

Verification: `task lint` clean, 536 tests passing.

## 2026-02-19 — Batch coding pipeline refactoring (code review fixes)

Post-review structural improvements to batch coding pipeline:

1. **God function decomposition** (`batch_coding.py`): Broke 360-line `batch_apply_coding`
   into focused phase functions: `_run_fast_path`, `_assemble_fast_path_only`,
   `_build_unresolved_descriptors`, `_generate_terms`, `_search_all_candidates`,
   `_select_findings`, `_select_locations`, `_assemble_results`. Main function is now
   a thin orchestrator calling phases in sequence.

2. **Selection pattern deduplication** (`batch_coding.py`): Extracted shared helpers
   `_is_valid_selection`, `_finding_alternates`, `_location_alternates`,
   `_unresolved_finding_code`, `_unresolved_location_code` — removes near-identical
   code between Phase 3 (finding selection) and Phase 4 (location selection).

3. **Prompt builder consolidation** (`batch_coding_agents.py`): Three nearly-identical
   prompt builders (`_build_search_term_prompt`, `_build_finding_selector_prompt`,
   `_build_location_selector_prompt`) replaced with shared `_build_prompt(instruction, *,
   exam_info, chunk_text, findings)` plus per-agent instruction constants.

4. **Typed inter-module interfaces** (`batch_coding_agents.py`): Replaced `dict[str, Any]`
   parameters with `TypedDict` interfaces: `FindingDescriptor`, `FindingWithCandidates`,
   `LocationWithCandidates`. Used at construction sites in `batch_coding.py` and agent
   function signatures.

5. **Documentation**: Added deferred items (PR-017, PR-018) and future ideas (FI-012
   through FI-014) to backlog docs.

## 2026-02-19 — Batch coding pipeline (replaces per-finding adjudication)

Replaced per-finding deterministic+adjudication coding pipeline with batch per-chunk
3-call LLM pipeline:

1. **New files:**
   - `batch_coding_agents.py`: 3 PydanticAI agents (search term generator, finding
     code selector, location code selector) with structured output models.
   - `batch_coding.py`: pipeline orchestrator — deterministic fast-path, then 3 LLM
     calls per chunk for unresolved findings. Includes index infrastructure moved
     from `code_assigner.py`.

2. **Wiring changes:**
   - `models.py`: added `"batch"` to `CodingMethod` and `LocationCodingMethod`.
   - `extraction_orchestrator.py`: `ApplyCodingFn` now variadic; passes `chunk_text`
     to coding function.
   - `extraction_runtime.py`: default coding function calls `batch_apply_coding`.
   - `config.py`: replaced `coding_adjudication_enabled` with `coding_search_limit`.
   - `broker.py`: updated import for `close_reusable_coding_indexes`.

3. **Retired files:** `code_assigner.py`, `coding_agents.py` (and their tests).

4. **New tests:** `test_batch_coding_agents.py` (10 tests), `test_batch_coding.py`
   (11 tests). Updated orchestrator and runtime tests for new signatures.

## 2026-02-19 — Runtime contract alignment (exam-info context + always-on validator)

1. Expanded exam-info sub-agent payload wiring:
   - orchestrator now passes `source_ref`, external metadata, and deterministic
     header-focused report context to `extract_exam_info`.
   - exam-info prompt builder now includes those fields and only falls back to
     report preview when header context is unavailable.
2. Validator review is now always-on in runtime:
   - removed `validator_review_enabled` setting and `IPL_VALIDATOR_REVIEW_ENABLED`.
   - `validator_reextract_enabled` remains the retry control for validator requests.
3. Added regression/contract tests:
   - cache-key regression ensuring adjudication caching keys on `evidence_text`.
   - exam-info context forwarding tests at runtime and orchestrator layers.
4. Documentation alignment updates:
   - `docs/configuration.md` + `config.toml.example` updated for always-on validator.
   - `docs/extraction-internals.md`, `docs/extraction-usage.md`,
     `docs/eval-internals.md`, and orchestrator plan stage vocabulary aligned with
     current runtime behavior.

## 2026-02-18 - Documentation cleanup and restructuring

1. Added `docs/README.md` as categorized index of all documentation.
2. Archived 23 completed/historical docs to `docs/archive/`:
   - 12 completed stage/stream docs from `extractor-agent-plans/`
   - 2 one-time artifacts (`ui-improvement-fixes.md`, `ui-impact-runtime-unification.md`)
   - 9 completed plan docs (`testing_plan.md`, `batch-runner-plan.md`, `data-model-plan.md`, `config-plan.md`, `migration-architecture.md`, `api-server.md`, `extractor-frontend.md`, `database-layer.md`, `logging-plan.md`)
3. Updated all cross-references in active docs to point to `archive/` paths.
4. Updated root `README.md` to remove stale doc references.
5. Rotated DEV_LOG.md (121K → fresh start; full history in archive).

## 2026-02-18 — Orchestrator next-phase: exam-info, coding context, validator feedback, timeouts

Implemented all four "Immediate Next Work Items" from the orchestrator core plan:

1. **Exam-info sub-agent** (`exam_info_agent.py`): dedicated agent extracts modality,
   body part, and laterality from the report header. Runs in parallel with chunk
   extraction via `asyncio.create_task`; non-fatal on failure (keeps placeholder).
   Added `laterality` field to `ExamInfo` model.
2. **Coding adjudicator context upgrade** (`coding_agents.py`, `code_assigner.py`):
   adjudication prompts now receive exam info, presence, location fields, and evidence
   text. Cache key includes exam context to prevent cross-report stale hits.
   Renamed `code_assinger.py` → `code_assigner.py` (typo fix).
3. **Validator review with feedback** (`extraction_review.py`, `extraction_orchestrator.py`):
   `ReviewRequest` model carries per-unit feedback and suspected_issue. Feedback is
   threaded to retry units and appended to chunk extraction prompts. Validator review
   now runs unconditionally in the V2 runtime.
4. **Per-piece timeouts** (`config.py`, `extraction_orchestrator.py`):
   `subagent_timeout_seconds` (default 20s) wraps chunk extraction, coding, validator
   review, and exam-info await. All timeout paths are non-fatal except chunk extraction
   (which feeds into existing repair logic).

Bug fixes from code review:
- Coding cache key now includes exam context fields and evidence text to prevent stale adjudication reuse.
- Exam-info task is cancelled on early orchestrator failure (all chunks fail).

Test coverage: 15 new/updated orchestrator tests covering parallel exec, timeouts,
feedback threading, non-fatal failures. 60 tests passing across affected modules.

## 2026-02-18 - Chunk sub-agent wiring + model guidance docs

1. Wired orchestrator chunk-unit extraction calls to the dedicated chunk prompt/schema path:
   - runtime/worker now use `extract_chunk_findings` for unit extraction
   - chunk context fields (`section_name`, prev/next context) are passed explicitly
2. Kept final assembled contract unchanged (`ReportExtraction`) while adapting chunk payloads.
3. Updated extraction docs to reflect chunk sub-agent behavior:
   - `docs/extraction-internals.md`
   - `docs/extraction-usage.md`
4. Added model guidance reference:
   - `docs/model-selection-notes.md`
5. Updated active plan docs for remaining orchestrator work and future ideas:
   - `docs/extractor-agent-plans/orchestrator-core-plan.md`
   - `docs/extractor-agent-plans/chunk-extraction-prompt-schema-plan.md`
   - `docs/future-improvements.md` (dynamic example selection backlog item)

## 2026-02-24 - Validator hard cutover to single-chunk review contract

1. Replaced report-level validator request flow with single-chunk review decisions:
   - one validator call per `report_chunk_id`
   - one `ExtractionReviewDecision` per chunk
   - problem list typed as `ExtractionReviewProblem` with `extract_problem_type`
2. Updated orchestrator validator stage behavior:
   - chunk-scoped review status events (`chunk_review_start`, `chunk_review_decision`)
   - targeted re-extraction with structured feedback threaded into chunk prompt
   - final review summary detail event
3. Updated validator prompt contract and payload shape to chunk-level naming:
   - canonical fields: `REPORT_CHUNK_ID`, `EXAM_INFO`, `PRECEDING_CHUNK_CONTEXT`,
     `REPORT_CHUNK`, `FOLLOWING_CHUNK_CONTEXT`, `CHUNK_EXTRACTION`
   - required `EXTRACTION_TASK_SUMMARY` block
4. Moved validator prompt artifact to `prompts/validator_prompt_example.md`
   and removed the stale root-level `validator_prompt_example.md`.
5. Updated active plan/docs to align with the new schema and terminology.


## 2026-02-24 - Runtime reasoning policy + canonical model defaults cleanup

1. Added canonical model constants and curated common model list in `src/finding_extractor/model_defaults.py`.
2. Updated defaults/presets/docs to align on current baseline models:
   - default extraction: `google-gla:gemini-3-flash-preview`
   - fallback extraction: `openai:gpt-5.2`
   - quality preset / validator default example: `anthropic:claude-opus-4-6`
   - local options: `ollama:qwen3:30b-instruct`, `ollama:qwen3:30b-thinking`, `ollama:gpt-oss:120b`
3. Unified API/batch/eval/runtime reasoning preflight on `resolve_runtime_reasoning(...)` with model-family-aware normalization and strict unknown-family fail-fast (override via `IPL_ALLOW_UNKNOWN_MODEL_REASONING=true`).
4. Made Ollama reasoning behavior model-specific in provider settings/capabilities:
   - Qwen3 thinking variants accept thinking levels
   - Qwen3 instruct remains `none` only
   - GPT-OSS 120B supports tiered `think` levels (`minimal` normalized to `low`)
5. Switched secrets handling to unprefixed env names where applicable:
   - Logfire token is `LOGFIRE_TOKEN` (env-only; rejected in `config.toml`)
6. Updated CLI/docs semantics so coverage validation is enabled by default (`--validate/--no-validate`, default `--validate`) and clarified usage guidance.
