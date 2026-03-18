# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Imaging Problem List (IPL) project extracts structured findings from radiology reports and aggregates them into patient-level imaging problem lists. It includes:

- A **finding extractor** — a PydanticAI-based agent that extracts structured findings from free-text radiology reports, with a FastAPI REST API, TaskIQ async workers, and a CLI.
- An **IPL viewer** — a static SPA that visualizes aggregated imaging problem lists from JSON data files.
- An **extractor UI** — a static SPA frontend for the extraction API (submit reports, trigger extractions, review results).
- **Data specifications** — JSON structures and examples for Exam Finding Lists (EFLs) and Imaging Problem Lists (IPLs), with FHIR mappings.

When working on either frontend (`viewer/` or `extractor-ui/`), prefer **Alpine.js** and **Flowbite** patterns over custom JavaScript and hand-rolled Tailwind markup.

We use `uv` as the build system and manage a `.venv` — use `uv run` rather than `python3` directly. Use `Taskfile.yml` commands as the workflow surface (e.g., `task lint`, `task test`, `task stack:up`).

## Repository Structure

```
src/finding_extractor/     # Python package: agent, API, CLI, worker, persistence
  api/                     # FastAPI layer
    __init__.py            # App factory, create_app(), main()
    routes.py              # API route handlers
    schemas.py             # Request/response contract models
    services.py            # API business logic (enqueue, lookups)
    dependencies.py        # FastAPI dependency injection
    mappers.py             # Response mapping helpers
  db/                      # Persistence layer
    store.py               # Public persistence facade
    engine.py              # Engine/session lifecycle + migration preflight
    reports.py             # Report persistence helpers + StoredReport types
    extractions.py         # Extraction persistence helpers + StoredExtraction types
    jobs.py                # Job persistence helpers + StoredJob type
    corrections.py         # Correction persistence helpers + StoredCorrection type
    users.py               # User persistence helpers + StoredUser type
    tables.py              # SQLModel table definitions
  models.py                # Core Pydantic models (ReportExtraction, findings, etc.)
  core/                    # Foundation: config, base model, logging, observability
    config.py              # Centralized pydantic-settings configuration
    base_model.py          # StrictBaseModel shared base class
    logging_setup.py       # Structured logging bootstrap
    observability.py       # Logfire instrumentation setup
  worker/                  # TaskIQ async processing
    broker.py              # Redis broker configuration
    extraction_jobs.py     # Background extraction task
    coding_jobs.py         # Background coding task
  coding/                  # Post-extraction coding pipeline
    prompt.py              # Coding prompt constants and prompt builders
    agents.py              # Coding agent factory helpers
    runtime.py             # Coding runtime orchestration
    types.py               # Structured-output response models for coding agents
  cli/                     # CLI entry points
    extract.py             # Single-report extraction CLI
    code.py                # Post-extraction coding CLI
    batch.py               # Batch extraction CLI
    batch_engine.py        # Batch execution engine
    batch_state.py         # Batch run state management
    eval_cmd.py            # Evaluation harness CLI
    runtime_budget.py      # Token budget helpers
  examples/                # Few-shot extraction examples
    __init__.py            # Example loader
    chunk_examples.yaml    # Chunk-level extraction examples
    ct_abdomen.yaml        # CT abdomen example
    xr_chest.yaml          # Chest X-ray example
  llm/                     # LLM configuration subpackage
    defaults.py            # Canonical model IDs and curated model list
    policy.py              # Model ID validation and SOTA selection
    catalog.py             # Multi-provider model discovery with Redis caching
    resilience.py          # Resilient model/agent construction with fallback
    model_settings.py      # Reasoning resolution, presets, provider settings
  extractor/               # Extraction pipeline + text processing
    orchestrator/          # Public orchestration facade + internal helpers
      __init__.py          # Public orchestration import surface
      run.py               # Workflow coordinator
      types.py             # Orchestration result/review types
      chunks.py            # Chunk building + bounded-concurrency execution
      merge.py             # Merge/dedupe + failed-chunk metadata helpers
      review.py            # Review + targeted re-extraction helpers
    agent.py               # PydanticAI extraction agent and prompt building
    runtime.py             # Shared extraction runtime (worker + CLI)
    review.py              # Validator review sub-agent
    exam_info_agent.py     # Exam-info extraction sub-agent
    progress.py            # Stage-progress formatting and callback helpers
    prompt.py              # System prompt builders
    report_sections.py     # Report section parsing
    chunking.py            # Semantic chunking
    impression_chunker.py  # Impression-specific chunking
    verbatim.py            # Verbatim quote validation
  eval/                    # Evaluation framework
    task.py                # Eval task adapter
    runner.py              # Eval run orchestration
    datasets.py            # Dataset loading
    evaluators.py          # Evaluation metrics
    matching.py            # Finding matching logic
    models.py              # Eval data models
    reporting.py           # Eval result reporting
  coding_summary.py        # Coding summary display helper
tests/                     # pytest test suite
alembic/                   # Database migrations
extractor-ui/              # Static SPA frontend for extraction API
  index.html               # Markup (Alpine.js + Tailwind v4 + Flowbite 4.0.1)
  app.js                   # Single Alpine component: extractorApp()
viewer/                    # Static SPA for IPL visualization
  index.html               # Markup (Alpine.js + Tailwind v3 + Flowbite 4.0.0)
  app.js                   # Single Alpine component: iplApp()
  data/                    # Patient JSON data served by the viewer
sample_data/               # Worked examples of EFL/IPL data structures
docs/                      # Architecture, plans, and reference documentation
Taskfile.yml               # Developer workflow commands
Dockerfile                 # Backend container image
docker-compose.yml         # Full stack: API + worker + Redis + Caddy
Caddyfile                  # Reverse proxy: serves extractor-ui, proxies /api
config.toml.example        # Example TOML config for local settings
pyproject.toml             # uv build config and dependencies
```

## Key Data Structures

### 1. Exam Finding List (EFL)
Individual report findings from a single imaging exam.

**Structure:**
- `diagnosticReportId`: Unique identifier for the report
- `patientInfo`: Patient identifier and DOB
- `examInfo`: Study details including LOINC code for exam type
- `findings`: Array of observations, each with:
  - `observationId`: Unique ID for this finding instance
  - `findingCode`: OIFM code for the finding type
  - `findingDescription`: Human-readable finding name
  - `attributes`: Array of attributes (typically presence/absence)

**FHIR Representation:** DiagnosticReport containing Observation objects. Each Observation has a finding code and components with attributes (presence/absence, changes from prior).

**Key Concept:** The same finding type may appear multiple times in one exam (e.g., multiple kidney stones). Each instance gets a separate entry with its own `observationId`.

### 2. Imaging Problem List (IPL)
Aggregated findings across a patient's entire imaging history.

**Structure:**
- `patient`: Patient demographics
- `findings`: Array of aggregated findings, each with:
  - `finding_type_code`: OIFM code for this type of finding
  - `finding_type_display`: Human-readable name
  - `observations`: Array of all times this finding was documented, each containing:
    - Reference to the source report and observation
    - Exam date and type
    - Presence/absence status

**FHIR Representation:** Report containing Condition objects (labeled with the finding identifier), where each Condition also contains Observation objects documenting which DiagnosticReports the finding appeared in.

**IPL Generation:** The IPL aggregates multiple EFLs. Multiple observations of the same finding type from one EFL (e.g., three kidney stones) are grouped together under one IPL finding entry, preserving references to each individual observation.

## Data Standards

- **FHIR**: Primary data format for medical records interchange
- **LOINC codes**: Used for exam type identification (e.g., "72133-2" = CT Abdomen and Pelvis Without Contrast)
- **Finding codes**: Use OIFM_XXXX_* format
  - Example: OIFM_GMTS_016552 = urinary tract calculus
  - Example: OIFM_MSFT_430810 = coronary artery calcifications
- **Attribute codes**: Use OIFMA_XXXX_* format for finding attributes
  - Typically used for presence (`.1` = present, `.0` = absent)
- **Code lookup**: Finding codes and their descriptions can be looked up at https://raw.githubusercontent.com/openimagingdata/findingmodels/refs/heads/main/ids.json

## Running the Project

### Full stack (Docker Compose)
```bash
task stack:up          # API + worker + Redis (no browser UI)
task stack:up:full     # API + worker + Redis + Caddy
# Extractor UI: http://localhost:8080 (after stack:up:full)
# API: http://localhost:8080/api or http://localhost:8001/api
task stack:down
```

### Backend development
```bash
task lint              # Ruff lint + format check
task test              # Unit tests (pytest)
task test:ui           # Playwright UI tests (run separately)
task test:api:e2e      # Backend API E2E against running backend stack
task test:web:e2e      # Full extractor UI E2E (requires Docker + API keys)
task db:migrate        # Run Alembic migrations
```

Testing guidance:
- Project-specific conventions: `docs/testing-practices.md`
- Generic pytest patterns skill: `.agents/skills/pytest-testing-patterns/`

### IPL Viewer (standalone)
```bash
cd viewer
python3 -m http.server 8000
# Open http://localhost:8000
```

### CLI
```bash
uv run finding-extractor <report_file> [--model <provider:model>] [--reasoning medium] [--validate] [--store]
# Write JSON to file and show table summary:
uv run finding-extractor <report_file> -o output.json -f table
uv run finding-extractor-code <extraction_json> [--model openai:gpt-5-mini] [--reasoning medium]
```

## Finding Extractor Architecture

### Agent
- PydanticAI agent with `ReportExtraction` structured output
- Multi-provider: OpenAI, Anthropic, Google, Ollama
- Per-provider reasoning/thinking modes (none through high)
- Verbatim quote validation (output validator + post-hoc)
- Few-shot examples loaded dynamically

### API (FastAPI)
- `POST /api/reports` — upsert report (dedup by SHA-256 hash)
- `GET /api/reports` — list reports (paginated)
- `GET /api/reports/{report_id}` — report with text
- `POST /api/reports/{report_id}/extract` — queue extraction (returns 202)
- `POST /api/extractions/{extraction_id}/code` — queue coding (returns 202)
- `GET /api/jobs/{job_id}` — poll job status
- `GET /api/reports/{report_id}/extractions` — list extractions
- `GET /api/extractions/{extraction_id}` — extraction detail
- `POST /api/extractions/{extraction_id}/corrections` — record correction
- `GET /api/models` — model discovery with cache metadata

### Persistence (SQLite + SQLModel)
- `reports` table — deduplicated by SHA-256 hash
- `extractions` table — full JSON payload, model name, reasoning effort
- extraction rows are updated in place when coding populates `findings[].coding`
- `corrections` table — user corrections (add_finding, update_finding, comment)
- `jobs` table — async job lifecycle (pending → running → completed/failed)

### Configuration
- Centralized `Settings` class via `pydantic-settings` in `core/config.py`
- `IPL_*` env var namespace for app settings
- Provider credentials via standard env names (`OPENAI_API_KEY`, etc.)
- Optional `config.toml` for local non-secret settings
- Reference: `docs/configuration.md`
- Logging docs:
  - `docs/logging-usage.md`
  - `docs/logging-internals.md`

## IPL Viewer

The `viewer/` directory contains a static SPA for visualizing imaging problem lists.

### Key Features
1. **Three-Level Navigation**: IPL → EFL → Report
2. **Temporal Status Tracking**: Present (green), Resolved (amber), Not Present/Ruled Out (gray)
3. **Smart Filtering**: By status and body region
4. **Body Region Inference**: Keyword matching on finding descriptions (`BODY_REGION_MAP` in `viewer/app.js`)
5. **Multi-Patient Support**: Dropdown + URL parameter (`?patient=patient-mrn0000001`)

### Viewer Data Directory
```
data/
  patients.json              # Manifest listing all patients
  patients/
    <patient-id>/
      patient.json           # Patient metadata
      ipl.json               # Imaging Problem List
      exams/
        <report-id>/
          efl.json           # Exam Finding List
          report.txt         # Raw report text
```

## Schema Reference

The EFL schema is referenced in the sample files as: `https://github.com/openimagingdata/imaging-problem-list/schema/exam-problem-list-schema.json`, but it doesn't exist yet.

## Agent Quick Reference

- **Core artifacts:** Exam Finding Lists capture single-exam observations and Imaging Problem Lists aggregate them across the patient timeline. The canonical descriptions live in `README.md` ("Exam Finding List" and "Imaging Problem List") plus the "Key Data Structures" section above.
- **Documentation map:** `README.md` = domain/FHIR framing, `CLAUDE.md` = agent workflow + project structure, `.github/copilot-instructions.md` = coding style + frontend conventions, `docs/` = architecture and plans.
- **Testing conventions:** use `docs/testing-practices.md` for this repo; use `.agents/skills/pytest-testing-patterns/` for general pytest best practices.
- **Frontend conventions:** Both SPAs use Alpine.js + Flowbite + Tailwind (viewer: v3, extractor-ui: v4). Keep Flowbite components and Alpine.js state patterns per `.github/copilot-instructions.md`.
- **Data on disk:** `data/patients.json` is the viewer manifest; each patient under `data/patients/<patient-id>/`. `sample_data/` has worked examples.
- **Backend workflow:** Use `task` commands from `Taskfile.yml`. Run tests with `task test`. Manage DB with `task db:migrate`.
