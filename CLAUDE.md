# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Imaging Problem List (IPL) project extracts structured findings from radiology reports and aggregates them into patient-level imaging problem lists. It has a PydanticAI-based extraction agent (with FastAPI API, TaskIQ workers, and CLI), two static SPA frontends (IPL viewer and extractor UI), and data specifications for Exam Finding Lists (EFLs) and Imaging Problem Lists (IPLs) with FHIR mappings.

## Conventions & Gotchas

- **Build system:** `uv` manages the `.venv` -- use `uv run` rather than `python3` directly.
- **Workflow surface:** `Taskfile.yml` is the command surface. Run `task --list` to discover available commands. All tasks have `desc:` fields.
- **Setup:** See `SETUP.md` for new developer setup.
- **Frontends:** Both SPAs (`viewer/` and `extractor-ui/`) use Alpine.js + Flowbite + Tailwind via CDN (no build step). Prefer Flowbite components and Alpine.js state patterns over custom JS and hand-rolled Tailwind.
- **Configuration:** Centralized `pydantic-settings` in `core/config.py` with `IPL_*` env var namespace. Never manipulate `os.environ` directly. Full reference: `docs/configuration.md`.
- **Testing:** Project-specific conventions in `docs/testing-practices.md`. General pytest patterns in `.agents/skills/pytest-testing-patterns/`.

## Domain Model

### Exam Finding List (EFL)

Per-exam list of findings (present/absent) extracted from a single radiology report.

- Each finding has an OIFM code, description, and attributes (presence/absence, change from prior)
- The same finding type may appear multiple times (e.g., multiple kidney stones) -- each gets its own entry with a unique `observationId`
- FHIR mapping: **DiagnosticReport** containing **Observation** objects with component attributes
- Examples: `sample_data/` and `viewer/data/patients/.../exams/*/efl.json`

### Imaging Problem List (IPL)

Per-patient aggregation of findings across all imaging exams, with temporal tracking.

- Groups observations of the same finding type across exams, preserving references to each source report
- Tracks temporal status: currently present, resolved, never-present/ruled-out
- FHIR mapping: **Report** containing **Condition** objects (one per finding type), each referencing **Observation** objects from source **DiagnosticReports**

### Data Standards

- **FHIR**: Primary interchange format. Do not invent new mapping schemes.
- **LOINC codes**: Exam type identification (e.g., "72133-2" = CT Abdomen and Pelvis Without Contrast)
- **Finding codes**: `OIFM_XXXX_*` format (e.g., `OIFM_GMTS_016552` = urinary tract calculus)
- **Attribute codes**: `OIFMA_XXXX_*` format (`.1` = present, `.0` = absent)
- **Code lookup**: https://raw.githubusercontent.com/openimagingdata/findingmodels/refs/heads/main/ids.json

## Architecture Notes

These are design decisions that aren't obvious from reading the code:

- **Chunked extraction pipeline:** Long reports are semantically chunked, extracted concurrently (bounded), then merged/deduped. A reviewer sub-agent can flag issues and trigger targeted re-extraction of specific chunks.
- **Multi-provider LLM support:** OpenAI, Anthropic, Google, OpenRouter, Ollama. Each provider has different reasoning/thinking mode support -- `llm/model_settings.py` handles normalization. Some Ollama families need `NativeOutput` (JSON schema mode) instead of tool-calling.
- **Verbatim quote validation:** Extraction output includes verbatim quotes from the report. Validated both as a PydanticAI output validator and post-hoc.
- **Post-extraction coding pipeline:** After extraction, a separate coding agent maps findings to standardized OIFM codes. This is a distinct step from extraction.
- **Persistence:** SQLite via SQLModel + Alembic migrations. Reports deduped by SHA-256 hash. Extraction rows updated in-place when coding completes.
- **Async jobs:** TaskIQ workers process extraction/coding jobs via Redis broker. API returns 202 + job ID for polling.

## Documentation Pointers

- `README.md` -- domain overview, FHIR framing, developer workflows
- `AGENTS.md` -- symlink to this file (for Cursor, Windsurf, and other agent tools)
- `docs/` -- architecture docs, usage guides, plans (explore with `ls docs/`)
- `docs/configuration.md` -- full configuration reference
- `docs/testing-practices.md` -- project-specific test conventions
