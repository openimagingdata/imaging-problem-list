# Finding Extractor Usage

Extract structured findings from radiology reports using an LLM agent.

## How Extraction Works (High-Level)

At runtime, the extractor uses one shared orchestration path across CLI, API worker jobs, batch runs, and evals.

1. Parse report sections deterministically.
2. Keep extraction scope to `findings` and `impression`.
3. Chunk those sections (impression list-aware, semantic grouping for longer text).
4. Run chunk extraction sub-agents in parallel (dedicated chunk prompt + `ExtractedChunkFindings` schema).
5. Merge + dedupe findings, optionally run targeted re-extraction review, then finalize output.
6. Emit status stages throughout; return JSON and optionally persist to SQLite.

```mermaid
flowchart LR
    A[Report Text] --> B[Sectionize<br/>findings + impression]
    B --> C[Chunking<br/>list + semantic]
    C --> D[Parallel chunk extraction]
    D --> E[Merge + dedupe]
    E --> F[Optional validator review<br/>targeted re-extract]
    F --> G[Final extraction JSON]
    G --> H[Optional DB persistence]
```

For implementation-level details and full stage contracts, see `docs/extraction-internals.md`.

## Quick Start

```bash
uv run finding-extractor report.txt
```

Output is JSON with extracted findings, locations, attributes, and non-finding text segments.

Note: Coding (OIFM finding code and location code assignment) is a separate, independent step — see `docs/coding-agent-design.md`.

## Choosing a Model

Pass any [pydantic-ai model string](https://ai.pydantic.dev/models/) via `--model` or the `IPL_MODEL` env var.

| Provider | Example `--model` value | API key env var |
|----------|------------------------|-----------------|
| OpenAI | `openai:gpt-5.2` (fallback default) | `OPENAI_API_KEY` |
| Anthropic | `anthropic:claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| Google | `google-gla:gemini-3-flash-preview` (default) | `GOOGLE_API_KEY` |
| OpenRouter | `openrouter:meta-llama/llama-3.1-70b` | `OPENROUTER_API_KEY` |
| Ollama | `ollama:qwen3.6:35b-a3b-mlx-bf16` (local default) | *(none, local)* |

```bash
# Anthropic
uv run finding-extractor report.txt -m anthropic:claude-opus-4-6

# Google
uv run finding-extractor report.txt -m google-gla:gemini-3-flash-preview
uv run finding-extractor report.txt -m google-gla:gemini-3.1-pro-preview

# OpenRouter (aggregates many providers)
uv run finding-extractor report.txt -m openrouter:meta-llama/llama-3.1-70b

# Local Ollama (see Ollama setup below)
uv run finding-extractor report.txt -m ollama:qwen3.6:35b-a3b-mlx-bf16
uv run finding-extractor report.txt -m ollama:gemma4:26b-mxfp8                 # quality alt
uv run finding-extractor report.txt -m ollama:gpt-oss:120b --reasoning medium  # legacy
```

### Ollama Setup

Ollama runs models locally without API keys — the right choice for **PHI-sensitive workloads**. For those runs, always pass `--local-only` (see "Local-only (PHI-safe)" below) to enforce that no report text or output can reach a cloud endpoint.

Steps:

1. **Install and start Ollama:** Follow [ollama.com](https://ollama.com). Minimum version 0.21.0 (MLX runtime, Gemma 4 tool-calling).
2. **Pull the recommended local models** (on Apple Silicon / M-series; see `docs/eval-ollama-models-report.md` for benchmark rationale):
   - `ollama pull qwen3.6:35b-a3b-mlx-bf16` — **extraction default**, 70 GB, MLX runtime
   - `ollama pull qwen3.6:35b-a3b-bf16` — **reviewer default**, 71 GB (GGUF)
   - `ollama pull gpt-oss:20b` — fallback, 13 GB
   - `ollama pull gemma4:26b-mxfp8` — quality-first extraction alternative, 26 GB
   - `ollama pull medgemma:27b` — medical-domain specialist extractor, 17 GB
3. **Use the committed `.env.ollama` file** (rather than hand-setting env vars) — it already pins all the right models, reasoning levels, and timeouts:
   ```bash
   uv run --env-file .env.ollama finding-extractor report.txt
   ```
4. **Multi-model runs** (extractor + reviewer both loaded): `export OLLAMA_MAX_LOADED_MODELS=4` in your shell.

The committed `.env.ollama` sets:
- `IPL_MODEL=ollama:qwen3.6:35b-a3b-mlx-bf16`, `IPL_REASONING=none`
- `IPL_REVIEWER_ENABLED=true`, `IPL_REVIEWER_MODEL=ollama:qwen3.6:35b-a3b-bf16`, `IPL_REVIEWER_REASONING=low`
- `IPL_FALLBACK_MODEL=ollama:gpt-oss:20b`
- `OLLAMA_BASE_URL=http://localhost:11434/v1`
- `IPL_SUBAGENT_TIMEOUT_SECONDS=300`, `IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY=1`

#### Local-only (PHI-safe)

For PHI workloads, always add `--local-only`. This enforces a three-gate guard at load time: provider must be Ollama, no cloud-suffix tags (`:cloud`, `-cloud`), and `OLLAMA_BASE_URL` must resolve to loopback. Also disables Logfire and blocks any non-Ollama fallback.

```bash
# Single report
uv run --env-file .env.ollama finding-extractor /path/to/report.txt --local-only

# Batch (a directory of reports)
uv run --env-file .env.ollama finding-extractor-batch run \
  /path/to/reports/ \
  --glob '*.txt' \
  --output-dir /path/to/results/ \
  --local-only \
  --timeout-seconds 1800   # BF16 reviewer runs are ~11 min/report; 30 min headroom
```

See `docs/configuration.md` §"Local-only Mode (PHI Safety)" for the full enforcement matrix, limitations (Modelfile alias inspection not yet implemented), and reference command.

#### NativeOutput for models without tool support

Some Ollama families (gemma3, deepseek-r1, MedGemma) don't support PydanticAI's tool-calling protocol. The extractor auto-detects these and uses `NativeOutput` (JSON schema mode) instead. Gemma 4 *does* support tool-calling as of Ollama 0.20.6; it is not on the NativeOutput list. See `ollama_needs_native_output()` in `src/finding_extractor/llm/model_settings.py`.

## Reasoning / Thinking Level

The `--reasoning` flag controls how much "thinking" the model does before responding. Higher levels improve extraction quality at the cost of latency and tokens.

```bash
uv run finding-extractor report.txt --reasoning high
uv run finding-extractor report.txt --reasoning none
```

Levels: `none`, `minimal`, `low`, `medium`, `high`

Reasoning defaults are provider-specific (`openai=medium`, `anthropic=medium`, `google=low`, `openrouter=medium`, `ollama=none`). You can override with `--reasoning` or `IPL_REASONING`.

For Ollama, reasoning is model-specific:
- `ollama:qwen3.5:*` / `ollama:qwen3.6:*`: `none|low|medium|high` — thinks by default on the OpenAI-compatible endpoint; `reasoning_effort:none` is required to disable (the extractor sends this automatically)
- `ollama:gemma4:*`: `none|low|medium|high` — same `reasoning_effort` handling as Qwen3.6; routed through `NativeOutput` (JSON-schema) rather than tool-calling because Ollama 0.22.1's renderer change broke gemma4 tool-calls under suppressed thinking
- `ollama:nemotron-3-super:*`: same `none|low|medium|high` handling as Qwen3.5/3.6 (cascade-2 and nano retired 2026-05-14)
- `ollama:gpt-oss:120b` / `ollama:gpt-oss:20b`: `none|low|medium|high` (`minimal` normalizes to `low`)
- `ollama:qwen3:30b-thinking`: `none|minimal|low|medium|high` (mapped to `think=false|true`)
- `ollama:qwen3:30b-instruct`: `none` only
- `ollama:medgemma:*`: `none` only (Gemma 3-based, no reasoning surface)

Configuration details (env vars, `config.toml`, precedence, and secrets policy):
- `docs/configuration.md`

## All CLI Options

```
finding-extractor <report_file> [OPTIONS]

Options:
  --exam-type TEXT          Exam description for context (e.g., "CT Chest")
  --output, -o PATH         Write JSON to file (combine with -f table to also show summary)
  --model, -m TEXT          Model override (default: IPL_MODEL env var)
  --reasoning, -r LEVEL     none | minimal | low | medium | high
  --format, -f FORMAT       json (default) | table
  --validate / --no-validate  Run post-extraction coverage analysis (default: --validate)
  --store / --no-store      Persist to SQLite (default: --no-store)
  --db-path PATH            SQLite path (default: IPL_DB_PATH or .finding_extractor.db)
  --logfire / --no-logfire  Enable or disable Logfire observability for this run
  --verbose                 Emit INFO-level logs for this run
```

### `--validate` semantics (enabled by default)

Validation is enabled by default. Use `--no-validate` to disable it.

`--validate` runs a **coverage analysis** that checks whether all report text lines are accounted for by extracted findings or non-finding text segments. It does **not** perform verbatim quote checking — that is handled automatically by the agent's output validator, which retries the model when quotes don't match. As a result, `--validate` always returns `is_valid=True` with no `verbatim_errors`; it only produces `coverage_warnings`.

## Logfire Observability

Logfire is optional and disabled by default.

```bash
# Enable globally for API/worker/CLI runs via env
export IPL_LOGFIRE_ENABLED=true

# Enable only for one CLI invocation
uv run finding-extractor report.txt --logfire
```

For complete Logfire env options and defaults, see `docs/configuration.md`.

Supported instrumentation in this project includes:
- `pydantic_ai` agent runs
- `httpx` model/provider HTTP calls
- FastAPI request handling
- SQLAlchemy database operations
- Redis operations

## Logging Output Controls

Structured logging is configured via env vars:

```bash
export IPL_LOG_LEVEL=WARNING
export IPL_LOG_JSON=false
```

- `IPL_LOG_LEVEL`: `CRITICAL|ERROR|WARNING|INFO|DEBUG|NOTSET` (also accepts `WARN`)
- `finding-extractor --verbose ...`: one-run override to emit `INFO` logs.
- `IPL_LOG_JSON`: emit machine-readable JSON logs when `true`

## Python API

```python
from finding_extractor.extractor.runtime import run_extraction_runtime

result = await run_extraction_runtime(
    report_text="FINDINGS: Clear lungs. No pleural effusion.",
    study_description="Chest XR",
    model="anthropic:claude-sonnet-4-5",
    reasoning="high",
    validate=True,
    reliability_mode="strict",
    store=None,
    db_path=None,
    source_ref=None,
    report_id=None,
    # Optional: receive stage status messages during extraction
    # status_callback=async_fn_that_takes_a_string,
)

for finding in result.extraction.findings:
    print(f"{finding.finding_name}: {finding.presence}")
```

## Output Format

The JSON output contains:

- `exam_info` — study description, date, modality, body part
- `findings[]` — each with `finding_name`, `presence`, `location`, `attributes`, `report_text`, and optional `coding`
- `non_finding_text[]` — technique, indication, impression, etc.
- `findings[].coding.finding_code` — OIFM coding status (`coded|unmapped`), selected code, method, candidates
- `findings[].coding.location_code` — anatomic location coding status (`coded|unmapped`), selected code, method, candidates

Use `--format table` for a human-readable summary instead of JSON. Combine `-o output.json -f table` to write JSON to file and show the table summary on the terminal.

## Persistence

Use `--store` to persist reports/extractions to SQLite. See `docs/persistence-usage.md` for details.

## Batch Extraction CLI

For many reports at once, use `finding-extractor-batch` (local in-process runner).

Interactive mode (cloud models):

```bash
uv run --env-file .env finding-extractor-batch run sample_data/example3 \
  --glob "*.txt" \
  --workers 4 \
  --model openai:gpt-5-mini \
  --reasoning medium \
  --validate \
  --resume \
  --mode interactive \
  --allow-slow
```

Interactive mode (local / PHI-safe):

```bash
uv run --env-file .env.ollama finding-extractor-batch run /path/to/reports/ \
  --glob '*.txt' \
  --output-dir /path/to/results/ \
  --local-only \
  --timeout-seconds 1800
```

Note: for local runs keep `--workers 1` (the default) — Ollama serializes per GPU.

Detached mode:

```bash
uv run --env-file .env finding-extractor-batch run sample_data/example3 \
  --glob "*.txt" \
  --mode detached \
  --allow-slow
```

Watch detached status:

```bash
uv run finding-extractor-batch status --run-id <run_id> --watch
```

Configuration defaults for workers, timeouts, retries, run dir, and suffix can be set via:
- env vars (`IPL_BATCH_*`)
- `config.toml` (`[ipl]`)

Batch runs also use a runtime preflight guard:
- `--max-predicted-runtime-seconds` (default `900`)
- `--allow-slow` to explicitly override when long runs are intentional

Reference:
- `docs/configuration.md`
