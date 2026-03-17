# Coding Agent Design

Blueprint for the standalone OIFM finding code and anatomic location code assignment tool.

Last updated: 2026-03-16

## Overview

Coding assigns OIFM finding codes and anatomic location codes to extracted findings. It is an **independent job** — fully decoupled from extraction. Extraction output persists without codes; coding is triggered separately and can be re-run with different models or settings.

## Architecture Decisions

### Canonical unit of work: flat merged-finding mode

Coding operates on the **flat merged finding list** from a completed extraction — not chunk-scoped. Each finding already carries `finding_name`, `presence`, `location`, `report_text` (verbatim quote), and `source_section`. This is sufficient context for coding; the extraction agent has already resolved chunk-level ambiguity.

**Rationale (from prototype testing):**
- Dropping full report text from term generation prompts produced identical results with 22% fewer input tokens.
- Per-finding `report_text` + `location` fields give selectors the context they need.
- Chunk context (preceding/following) adds marginal value for coding — it matters during extraction (interpreting free text), but by coding time the structured fields carry the signal.

The chunk-scoped naming conventions (`report_chunk_id`, `preceding_chunk_context`, etc.) are **not used** by the coding agent. They remain canonical for the extraction and validation subsystems.

### 4-Call LLM Pipeline

The pipeline has 5 phases, of which 4 involve computation and 2 involve LLM calls:

1. **Fast-path resolution** — exact/synonym index lookup for finding codes (`FindingIndex.get(name)`) and location codes (`AnatomicLocationIndex.get(specific_anatomy)`). Findings that resolve skip the LLM pipeline for that axis.
2. **LLM term generation** — two parallel agents (finding terms + location terms) generate 2-3 diverse search terms per finding. Only findings that missed fast-path are included.
3. **Index search** — `search_batch()` for finding candidates, `search_batch()` for location candidates. Results deduped per finding, capped at `MAX_CANDIDATES`.
4. **LLM code selection** — per-finding finding selector + location selector, run concurrently within a semaphore.
5. **Assembly** — merge fast-path and LLM results into `FindingCodingBundle` per finding.

Finding code selection and location code selection run as **parallel LLM calls** within the same concurrency semaphore.

### Non-Fatal Per-Phase Design

Each phase catches exceptions independently and degrades gracefully:

- Search term generation failure → use `finding_name` as the fallback search term.
- Index search failure → skip coding for that finding (mark unresolved).
- Code selection failure → mark unresolved.
- One finding's failure does not block other findings.

## Prompt Design

Full prompt text lives in `docs/coding-agent-prompts.md`. Key decisions from prototype testing:

- **No full report text** in term generation prompts. Each finding's `report_text` + `finding_name` + `location` fields are sufficient.
- **Exam info** (modality, body part, study description) is included — it helps disambiguate terms and candidates.
- **Four separate prompts**: finding term generator, location term generator, finding code selector, location code selector. The two term generators run in parallel; the two selectors run in parallel per finding.

## Index Search Strategy

### Finding Index

- `search_batch(all_unique_terms, limit=SEARCH_LIMIT)` — one batch embedding call across all finding search terms.
- Results distributed back to each finding based on which terms belong to which finding.
- Deduped per finding, capped at `MAX_CANDIDATES`.

### Location Index

- `search_batch(all_unique_terms, limit=SEARCH_LIMIT)` — one batch embedding call across all location search terms.
- Results distributed back to each finding, deduped, capped at `MAX_CANDIDATES`.

### Tuned Parameters (from prototype testing)

- `SEARCH_LIMIT = 6` — candidates per search term (reduced from 10; no quality loss)
- `MAX_CANDIDATES = 12` — cap per finding after dedup across terms (reduced from unbounded ~22; no quality loss, ~18% faster)
- `MAX_CONCURRENCY = 5` — semaphore for parallel LLM selector calls

## Model Configuration

### Defaults (from prototype benchmarking)

| Setting | Value | Rationale |
|---------|-------|-----------|
| Primary model | `openai:gpt-5.2` | Same quality as gemini-3-flash, 2x faster |
| Reasoning | `low` | Sufficient for term generation and code selection |
| Fallback model | `google-gla:gemini-3.1-flash-lite-preview` | Fast, cheap, adequate for most coding tasks |

### Infrastructure

- Use `build_resilient_model()` from `llm/resilience.py` for primary + fallback with pinned model settings per provider.
- Use `resolve_runtime_reasoning()` from `llm/model_settings.py` at API/worker preflight boundaries to validate and normalize the requested reasoning level for the selected model.
- Use `get_model_settings()` from `llm/model_settings.py` only as the provider-settings builder after reasoning has already been resolved.
- Model and reasoning are configurable per coding run (CLI arg, API parameter, config setting).

### Configuration Settings

New `IPL_CODING_*` env var namespace:

- `coding_model` — default: `openai:gpt-5.2`
- `coding_reasoning` — default: `low`
- `coding_fallback_model` — default: `google-gla:gemini-3.1-flash-lite-preview`
- `coding_max_concurrency` — default: `5`
- `coding_search_limit` — default: `6`
- `coding_max_candidates` — default: `12`

## Schema: Coding Payload

### `FindingCodingBundle` (updated)

The current `FindingCodingBundle` has `location_code: LocationCode` (singular). The coding agent can return **multiple location codes** for bilateral/spanning findings (e.g., "lungs" → left lung + right lung). Update to:

```python
class FindingCodingBundle(StrictBaseModel):
    finding_code: FindingCode = Field(default_factory=FindingCode)
    location_codes: list[LocationCode] = Field(default_factory=list)
```

**Migration:** rename `location_code` → `location_codes` (list). Existing coded extractions with a single location code get wrapped in a one-element list during migration.

### `FindingCode` — updated method enum

Current `CodingMethod` includes methods from prior iterations (`"exact"`, `"synonym"`, `"search"`, `"agent"`, `"batch"`). Simplify to match actual pipeline:

```python
CodingMethod = Literal["fast-path", "llm", "unresolved"]
```

- `"fast-path"` — resolved via `FindingIndex.get()` exact/synonym match
- `"llm"` — resolved via term generation → search → LLM selector
- `"unresolved"` — no acceptable match found

### `LocationCode` — updated method enum

```python
LocationCodingMethod = Literal["fast-path", "llm", "unresolved"]
```

### `UnresolvedReason` — expanded to match selector contracts

Current enum: `Literal["no_match", "search_low_confidence", "coding_error"]`

Updated to align with the LLM selector rejection reasons:

```python
# Finding unresolved reasons
FindingUnresolvedReason = Literal[
    "too_specific",         # candidates narrow beyond what report states
    "too_broad",            # candidates too general to be useful
    "wrong_concept",        # candidates are different clinical entities
    "definition_mismatch",  # candidate name matches but definition differs (flags ontology gap)
    "no_candidates",        # index search returned no candidates
    "coding_error",         # LLM or infrastructure failure
]

# Location unresolved reasons
LocationUnresolvedReason = Literal[
    "no_candidate_match",   # know where it is, no candidate fits (flags index gap)
    "location_unknown",     # cannot determine location from available context
    "no_candidates",        # index search returned no candidates
    "coding_error",         # LLM or infrastructure failure
]
```

### `FindingCode` — add reasoning field

```python
class FindingCode(StrictBaseModel):
    status: Literal["coded", "unmapped"] = "unmapped"
    oifm_id: str | None = None
    oifm_name: str | None = None
    method: CodingMethod = "unresolved"
    reason: FindingUnresolvedReason | None = None
    reasoning: str | None = None  # LLM's explanation of selection/rejection
    closest_candidate_id: str | None = None  # when unresolved, the nearest miss
    candidates: list[AlternateCode] = Field(default_factory=list)
```

### `LocationCode` — add reasoning field

```python
class LocationCode(StrictBaseModel):
    status: Literal["coded", "unmapped"] = "unmapped"
    location_id: str | None = None
    location_name: str | None = None
    method: LocationCodingMethod = "unresolved"
    reason: LocationUnresolvedReason | None = None
    reasoning: str | None = None
    candidates: list[LocationAlternateCode] = Field(default_factory=list)
```

## Persistence Model

### Coding mutates the existing extraction in place

Coding writes back to the same `ExtractionRow` by updating `extraction_json` with `Finding.coding` populated. This is the simplest model and matches the current schema where `Finding.coding` defaults to `None`.

**Why not separate coding-run records?** The extraction is the unit of work. Coding decorates it with codes. Re-running coding with different settings overwrites the previous codes on that extraction. If we need audit history of coding runs, we add that later — YAGNI for now.

**What changes on the extraction row:**

- `extraction_json` — updated with `Finding.coding` populated
- `coded_finding_count` — count of findings with `finding_code.status == "coded"`
- `unresolved_finding_count` — count with `finding_code.status == "unmapped"` after coding

### Coding metadata on ExtractionRow

Add columns for coding provenance:

```python
coding_model: str | None = None
coding_reasoning: str | None = None
coding_completed_at: str | None = None
coding_duration_ms: int | None = None
coding_trace_id: str | None = None
```

**Migration:** because this project does not need to preserve any existing stamped database, the coding columns are folded directly into the current baseline Alembic revision instead of introducing a follow-on revision.

### Job lifecycle

Coding reuses the existing `JobRow` table **without adding `job_type`**. A coding job stores:

- `report_id` — copied from the parent extraction's report
- `extraction_id` — set at enqueue time to the extraction being coded

This is sufficient to identify the job as a coding job in practice:

- It is created only via `POST /api/extractions/{extraction_id}/code`
- It is polled through the existing `GET /api/jobs/{job_id}` endpoint
- The worker and API route already know which task type they enqueued

If we later need first-class mixed job listing/filtering across multiple job kinds, we can add `job_type` then. For now, avoid schema churn we do not need. Job lifecycle remains: `pending → running → completed/failed`.

## API

### Trigger coding

```
POST /api/extractions/{extraction_id}/code
```

Request body (all optional, defaults from config):
```json
{
  "model": "openai:gpt-5.2",
  "reasoning": "low"
}
```

Response (202 Accepted):
```json
{
  "job_id": "...",
  "extraction_id": "...",
  "status": "pending"
}
```

### Coding status

Coding job status is visible via the existing `GET /api/jobs/{job_id}` endpoint.

Coding results are visible on the extraction detail:
- `GET /api/extractions/{extraction_id}` — includes `Finding.coding` when populated
- `GET /api/reports/{report_id}/extractions` — summary shows `coded_finding_count` / `unresolved_finding_count`

## Observability

### Logfire integration

Use the shared `configure_logfire()` path from `core/observability.py` — not ad hoc `logfire.configure()`. This gets the repo-standard PydanticAI, httpx, SQLAlchemy, Redis, and provider SDK instrumentation automatically.

### Structlog logging

Following the extraction worker pattern (`worker/extraction_jobs.py`):

- `logger = structlog.get_logger(__name__)` at module level in `coding/runtime.py` and `worker/coding_jobs.py`
- `bind_contextvars(job_id=..., report_id=..., extraction_id=...)` at the start of each coding job, `clear_contextvars()` in `finally`. This ensures all log lines within the job carry structured context automatically.
- Key operational log events:
  - `logger.info("Coding task started", model=..., reasoning=..., total_findings=...)`
  - `logger.info("Coding pipeline outcome", coded_findings=..., unresolved_findings=..., fast_path_count=..., llm_count=..., wall_clock_seconds=...)`
  - `logger.warning("Coding completed with unresolved findings", unresolved_count=..., unresolved_names=...)` — when findings remain unmapped
  - `logger.exception("Coding task failed", public_error=...)` — for infrastructure/LLM failures
  - `logger.debug(...)` for per-phase detail (fast-path hits, term counts, candidate counts)
- Error classification follows extraction's `to_public_job_error()` pattern, with coding-specific error strings (`coding_failed:model_provider_error`, `coding_failed:internal_error`, etc.)

### Progress callbacks

Following the extraction pipeline's `ProgressCallbackType` pattern:

- `coding/runtime.py` accepts an optional `progress_callback: ProgressCallbackType | None`
- Status messages use `format_stage_status()` from `extractor/progress.py` for parseable `[stage:X] detail` format
- Coding-specific stages:
  - `[stage:coding_fast_path] resolving_indexes`
  - `[stage:coding_term_gen] generating_search_terms`
  - `[stage:coding_search] searching_indexes`
  - `[stage:coding_selection] selecting_codes` / `selecting_codes_N_of_M`
  - `[stage:coding_assembly] assembling_results`
  - `[stage:coding_persist] saving_coded_extraction`
  - `[stage:coding_complete] coding_complete` / `[stage:coding_failed] <public_error>`
- The worker task (`worker/coding_jobs.py`) wires this to `store.update_job_status_message(job_id, message)` — same pattern as extraction, enabling the frontend to poll job status and show progress.

### Coding-specific Logfire structured context

All coding Logfire spans carry:
- `job_id`, `report_id`, `extraction_id`
- `coding_model`, `coding_reasoning`
- `total_findings`, `max_concurrency`

### Phase spans (carried from prototype)

```
coding_pipeline                              # top-level span
├── phase1_fast_path                         # findings_resolved, locations_resolved
├── phase2_term_generation                   # finding_count, location_count
│   ├── finding_term_generator run           # PydanticAI auto-instrumented
│   └── location_term_generator run          # PydanticAI auto-instrumented
├── phase3_index_search                      # finding_queries, location_queries
├── phase4_code_selection                    # findings_coded, findings_unresolved, locations_coded, locations_unresolved
│   ├── select_finding_code (per finding)    # finding_name, num_candidates
│   └── select_location_code (per finding)   # finding_name, num_candidates
└── phase5_assembly                          # (terminal counts)
```

### Terminal outcome events

Analogous to extraction's `Reliability contract outcome`, emitted via both structlog and Logfire:

```python
# structlog (always emitted)
logger.info(
    "Coding pipeline outcome",
    coded_findings=coded,
    unresolved_findings=unresolved,
    fast_path_findings=fast_path_count,
    llm_coded_findings=llm_count,
    wall_clock_seconds=elapsed,
)

# Logfire span attribute (when Logfire enabled)
logfire.info(
    "Coding pipeline outcome",
    job_id=job_id,
    extraction_id=extraction_id,
    total_findings=total,
    coded_findings=coded,
    unresolved_findings=unresolved,
    fast_path_findings=fast_path_count,
    llm_coded_findings=llm_count,
    wall_clock_seconds=elapsed,
)
```

For failures:
```python
logger.exception("Coding task failed", public_error=public_error)
logfire.error("Coding pipeline failed", job_id=job_id, extraction_id=extraction_id, error=public_error)
```

### PHI-safe policy

Per `docs/logging-usage.md`:
- Never log raw report text or verbatim finding quotes in span attributes or structlog fields.
- Log finding names, codes, counts, durations, model names, and IDs only.
- The LLM selector `reasoning` field is persisted in the extraction JSON but NOT logged to spans or structlog — it may reference report content.
- Finding names are borderline (they describe clinical concepts, not patient data) — acceptable in debug-level logs and Logfire spans but not in warning/error messages that might appear in external alerting channels.

## Module Map

```
src/finding_extractor/
  coding/                          # New subpackage
    __init__.py                    # Public API: run_coding()
    prompt.py                      # System prompt constants, user prompt builders
    agents.py                      # Agent factory functions (4 agents)
    runtime.py                     # Phase-aware orchestrator, CodingResult type
    types.py                       # LLM response models (FindingTerms, FindingCodeSelection, etc.)
  models.py                        # Updated: FindingCodingBundle, FindingCode, LocationCode, enums
  worker/
    coding_jobs.py                 # New: TaskIQ background task
  api/
    routes.py                      # Updated: POST /extractions/{id}/code
    schemas.py                     # Updated: TriggerCodingRequest/Response
    services.py                    # Updated: enqueue_coding_job()
  core/
    config.py                      # Updated: coding_* settings
  db/
    extractions.py                 # Updated: persist coding results back to extraction
    tables.py                      # Updated: coding metadata columns

alembic/versions/
  XXXX_add_coding_columns.py       # Migration for new columns

tests/
  coding/
    test_types.py                  # Response model validation
    test_prompt.py                 # Prompt builder correctness
    test_runtime.py                # Phase orchestration (mocked agents)
    test_fast_path.py              # Fast-path resolution logic
  test_api_coding.py               # API endpoint integration
```

## Implementation Plan

Status legend: `[ ]` not started, `[-]` in progress, `[x]` complete

Work proceeds on the `feature/coding-agent` branch (rebased on `dev`).

### Phase 1: Foundation

1. [x] **Write this plan** into `docs/coding-agent-design.md`
2. [x] Update `models.py`: `FindingCodingBundle.location_codes` (list), `CodingMethod`, `FindingUnresolvedReason`, `LocationUnresolvedReason`, reasoning/closest_candidate fields
3. [x] Add `coding_*` settings to `core/config.py`
4. [x] Create `coding/types.py`: LLM response models (`FindingTermsBatchOutput`, `LocationTermsBatchOutput`, `FindingCodeSelection`, `LocationCodeSelection`)

### Phase 2: Agents and Prompts

5. [x] Create `coding/prompt.py`: extract system prompts and user prompt builders from prototype
6. [x] Create `coding/agents.py`: four agent factories using `build_resilient_model()`
7. [x] Update `docs/coding-agent-prompts.md` to reflect final prompt text (no full report text in term generators; exam info + per-finding fields only)

### Phase 3: Runtime

8. [x] Create `coding/runtime.py`: 5-phase orchestrator with Logfire spans, semaphore, progress callbacks
9. [x] Wire up `coding/__init__.py` public API
10. [x] Add Alembic migration for coding metadata columns on `ExtractionRow`

### Phase 4: Integration

11. [x] Create `worker/coding_jobs.py`: TaskIQ task
12. [x] Add API route `POST /extractions/{id}/code` + schemas + service function, using `resolve_runtime_reasoning()` during enqueue preflight and storing both `report_id` and `extraction_id` on the reused `JobRow`
13. [x] Update `db/extractions.py`: persist coding results back to extraction

### Phase 5: Tests and Docs

14. [x] Unit tests for types, prompts, fast-path
15. [x] Integration tests for runtime (mocked LLM), API endpoint
16. [x] Update `docs/logging-usage.md` with coding-specific structured context
17. [x] Update `CLAUDE.md` project overview
18. [x] Mark this plan as complete

Implementation status: complete. The coding package, worker task, API endpoint, extraction persistence updates, migration, observability wiring, and targeted test coverage are now in the codebase.

## Lessons Learned From Prototyping

### Fast-path is highly effective

In prototype testing with chest X-ray extractions, fast-path resolved 13/16 unique finding names and 12/15 unique locations without any LLM calls. The LLM pipeline only needs to handle the remainder.

### Full report text adds no value to coding

Tested with/without full report text in term generation prompts. Identical results, 22% fewer input tokens. The per-finding `report_text` field (verbatim quote) plus `finding_name` and `location` fields are sufficient.

### Model comparison (26-finding chest X-ray, 3 LLM findings)

| Model | Finding Codes | Location Codes | Wall Clock |
|-------|--------------|---------------|------------|
| gemini-3-flash-preview | 15 | 15 | ~25s |
| **openai:gpt-5.2** | **15** | **15** | **~9s** |
| gemini-3.1-flash-lite-preview | 15 | 14 (lost 1) | ~7s |

GPT-5.2 matches gemini-3-flash quality at ~2x speed. Flash-lite is fastest but drops edge-case locations.

### Candidate count tuning

Reducing `SEARCH_LIMIT` from 10→6 and capping deduped candidates at 12 (from unbounded ~22) produced identical results with ~18% faster selector calls.

### Location coding needs LLM

The deterministic fast-path (blind top-1 from index) was tested for location assignment and proved inadequate. Location assignment requires contextual reasoning even when the finding code resolves via fast-path.

### Concurrency semaphore is essential

Without `MAX_CONCURRENCY`, large reports with many findings can overwhelm provider rate limits.
