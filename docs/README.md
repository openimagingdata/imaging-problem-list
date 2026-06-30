# Documentation Index

## Reference — How Things Work Now

### Extraction
- [extraction-usage.md](extraction-usage.md) — CLI usage, model selection, multi-provider examples
- [extraction-internals.md](extraction-internals.md) — Runtime module map and orchestrator flow
- [model-selection-notes.md](model-selection-notes.md) — Current model defaults and chunk-extraction model guidance
- [report-sections.md](report-sections.md) — Report sectioning and semantic chunking patterns

### API & Backend
- [api-usage.md](api-usage.md) — API endpoint reference for consumers
- [api-internals.md](api-internals.md) — API/worker module architecture for maintainers
- [dev-ops.md](dev-ops.md) — Docker Compose topology and operational setup
- [schema-migrations.md](schema-migrations.md) — Alembic operational runbook

### Configuration
- [configuration.md](configuration.md) — Canonical env var reference and precedence

### Persistence
- [persistence-usage.md](persistence-usage.md) — ExtractionStore API for callers
- [persistence-internals.md](persistence-internals.md) — SQLModel/SQLite schema and connection setup

### Evaluation
- [eval-usage.md](eval-usage.md) — Evaluation CLI reference and CI gate examples
- [eval-internals.md](eval-internals.md) — Evaluation harness architecture and matching algorithm

### Frontend
- [frontend-usage.md](frontend-usage.md) — Extractor UI views and features
- [frontend-internals.md](frontend-internals.md) — Extractor UI code structure
- [ipl-frontend-guide.md](ipl-frontend-guide.md) — Project-specific frontend conventions (both SPAs)

### Logging
- [logging-usage.md](logging-usage.md) — Runtime logging controls for operators
- [logging-internals.md](logging-internals.md) — Logging implementation for contributors

### Testing
- [testing-practices.md](testing-practices.md) — Project-specific testing conventions

### Workflows
- [human-review-workflow.md](human-review-workflow.md) — Creating gold extractions from sample data

## Active Plans

- [coding-agent-design.md](coding-agent-design.md) — Coding agent design (future, decoupled from extraction)
- [plans/extractor-evals-redesign.md](plans/extractor-evals-redesign.md) — Evaluation harness redesign plan
- [plans/local-only-future-tightening.md](plans/local-only-future-tightening.md) — Deferred local-only hardening backlog
- [plans/nemotron-cascade-2-evaluation.md](plans/nemotron-cascade-2-evaluation.md) — Nemotron Cascade 2 support/evaluation plan
- [plans/pydantic-ai-thinking-capability-simplification.md](plans/pydantic-ai-thinking-capability-simplification.md) — Future PydanticAI thinking-field simplification
- [viewer-refactoring.md](viewer-refactoring.md) — Viewer CDN/Tailwind migration plan

## Reports / Benchmarks / Draft References

- [eval-ollama-models-report.md](eval-ollama-models-report.md) — Local Ollama model benchmark and reviewer findings
- [technical-imaging-findings.md](technical-imaging-findings.md) — Draft technical imaging findings reference

## Backlogs

- [pending-refactoring.md](pending-refactoring.md) — Near-term refactoring/cleanup queue
- [future-improvements.md](future-improvements.md) — Longer-horizon improvement backlog

## Work Log

- [DEV_LOG.md](DEV_LOG.md) — Chronological development log with milestone evidence

## Archive

- [archive/](archive/) — Completed plans, historical artifacts, and rotated logs
