# Configuration Guide

This is the canonical configuration reference for the extraction backend.

## Precedence

Configuration sources are applied in this order:

1. runtime/init arguments
2. environment variables (`IPL_*` and provider API key vars)
3. `config.toml` (optional, non-secrets only)
4. code defaults

## Environment Variables

### App Settings (`IPL_*`)

| Env var | Type | Default | TOML key (`[ipl]`) |
|---|---|---|---|
| `IPL_DB_PATH` | path | `.finding_extractor.db` | `db_path` |
| `IPL_REDIS_URL` | string | `redis://localhost:6379` | `redis_url` |
| `IPL_REDIS_RESULT_TTL` | int | `3600` | `redis_result_ttl` |
| `IPL_MODEL` | string | `google-gla:gemini-3-flash-preview` | `default_model` |
| `IPL_FALLBACK_MODEL` | string \| null | `openai:gpt-5.2` | `fallback_model` |
| `IPL_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT` | int | `4` | `chunking_semantic_trigger_sentence_count` |
| `IPL_CHUNKING_SEMANTIC_EMBEDDING_MODEL` | string | `minishlab/potion-base-32M` | `chunking_semantic_embedding_model` |
| `IPL_CHUNKING_SEMANTIC_THRESHOLD` | float | `0.8` | `chunking_semantic_threshold` |
| `IPL_CHUNKING_SEMANTIC_CHUNK_SIZE` | int | `2048` | `chunking_semantic_chunk_size` |
| `IPL_CHUNKING_SEMANTIC_SIMILARITY_WINDOW` | int | `3` | `chunking_semantic_similarity_window` |
| `IPL_CHUNKING_SEMANTIC_SKIP_WINDOW` | int | `0` | `chunking_semantic_skip_window` |
| `IPL_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED` | bool | `true` | `chunking_impression_list_chunking_enabled` |
| `IPL_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK` | int | `3` | `chunking_impression_list_max_items_per_chunk` |
| `IPL_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK` | int | `2` | `chunking_impression_list_min_items_per_chunk` |
| `IPL_REVIEWER_ENABLED` | bool | `true` | `reviewer_enabled` |
| `IPL_REVIEWER_MODEL` | string \| null | `openai-responses:gpt-5.4-mini` | `reviewer_model` |
| `IPL_REVIEWER_REASONING` | string \| null | `low` | `reviewer_reasoning` |
| `IPL_REVIEWER_REEXTRACT_ENABLED` | bool | `true` | `reviewer_reextract_enabled` |
| `IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY` | int | `5` | `extractor_max_subagent_concurrency` |
| `IPL_SUBAGENT_TIMEOUT_SECONDS` | float \| null | `20.0` | `subagent_timeout_seconds` |
| `IPL_PRESET` | string \| null | `null` | `default_preset` |
| `IPL_REASONING` | string \| null | provider default | `default_reasoning` |
| `IPL_ALLOW_UNKNOWN_MODEL_REASONING` | bool | `false` | `allow_unknown_model_reasoning` |
| `IPL_CODING_MODEL` | string | `openai:gpt-5.2` | `coding_model` |
| `IPL_CODING_REASONING` | string \| null | `low` | `coding_reasoning` |
| `IPL_CODING_TERM_MODEL` | string \| null | `google-gla:gemini-3-flash-preview` | `coding_term_model` |
| `IPL_CODING_FALLBACK_MODEL` | string \| null | `google-gla:gemini-3.1-flash-lite-preview` | `coding_fallback_model` |
| `IPL_CODING_MAX_CONCURRENCY` | int | `8` | `coding_max_concurrency` |
| `IPL_CODING_SEARCH_LIMIT` | int | `6` | `coding_search_limit` |
| `IPL_CODING_MAX_CANDIDATES` | int | `12` | `coding_max_candidates` |
| `IPL_BATCH_RUN_DIR` | path | `.batch_runs` | `batch_run_dir` |
| `IPL_BATCH_WORKERS` | int | `4` | `batch_workers` |
| `IPL_BATCH_TIMEOUT_SECONDS` | int | `420` | `batch_timeout_seconds` |
| `IPL_BATCH_RETRIES` | int | `1` | `batch_retries` |
| `IPL_BATCH_STATUS_INTERVAL_SECONDS` | float | `5.0` | `batch_status_interval_seconds` |
| `IPL_BATCH_OUTPUT_SUFFIX` | string | `.extracted.json` | `batch_output_suffix` |
| `IPL_BATCH_RESUME` | bool | `true` | `batch_resume` |
| `IPL_MODEL_LIST_UPDATE_INTERVAL` | int | `172800` | `update_model_list_interval_seconds` |
| `IPL_LOG_LEVEL` | string | `WARNING` | `log_level` |
| `IPL_LOG_JSON` | bool | `false` | `log_json` |
| `IPL_EVAL_RUN_DIR` | path | `.eval_runs` | `eval_run_dir` |
| `IPL_EVAL_WORKERS` | int | `2` | `eval_workers` |
| `IPL_EVAL_TIMEOUT_SECONDS` | int | `120` | `eval_timeout_seconds` |
| `IPL_EVAL_RETRIES` | int | `0` | `eval_retries` |
| `IPL_EVAL_DATASET_DIR` | path | `evals/datasets` | `eval_dataset_dir` |
| `IPL_LOGFIRE_ENABLED` | bool | `false` | `logfire_enabled` |
| `IPL_LOGFIRE_SEND` | `auto\|true\|false` | `auto` | `logfire_send` |
| `IPL_LOGFIRE_SERVICE` | string | `finding-extractor` | `logfire_service_name` |
| `IPL_LOGFIRE_ENV` | string \| null | `null` | `logfire_environment` |
| `IPL_LOGFIRE_HEADERS` | bool | `false` | `logfire_capture_headers` |
| `IPL_LOGFIRE_METRICS` | bool | `false` | `logfire_system_metrics` |
| `IPL_LOGFIRE_SDKS` | bool | `false` | `logfire_instrument_provider_sdks` |

Notes:
- `IPL_LOG_LEVEL` accepts `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSET` (`WARN` alias is normalized to `WARNING`).
- `IPL_FALLBACK_MODEL` is optional and only used when primary model calls fail with provider API errors/timeouts.
- `IPL_REVIEWER_REEXTRACT_ENABLED` only controls whether reviewer-requested chunks are re-run; reviewer still runs when `IPL_REVIEWER_ENABLED=true`.
- Set `IPL_REVIEWER_ENABLED=false` to disable reviewer entirely.
- Reviewer requires a model different from the extraction model:
  - prefer `IPL_REVIEWER_MODEL` when set
  - otherwise use `IPL_FALLBACK_MODEL` if different
  - runtime raises an error if no distinct reviewer model is available
- Runtime reasoning compatibility for extraction and reviewer:
  - known incompatible pairs are auto-normalized to the nearest supported level (for example, `openai:gpt-5.2` + `minimal` -> `low`, `ollama:gpt-oss:120b` + `minimal` -> `low`)
  - if compatibility cannot be verified, runtime fails fast by default
  - set `IPL_ALLOW_UNKNOWN_MODEL_REASONING=true` to bypass fail-fast for unknown model families
  - model-specific Ollama behavior is enforced for known families:
    - `ollama:qwen3:30b-thinking` supports all reasoning levels
    - `ollama:qwen3:30b-instruct` supports `none` only
    - `ollama:gpt-oss:120b` supports `none|low|medium|high` (`minimal` normalized to `low`)
- `IPL_SUBAGENT_TIMEOUT_SECONDS` applies to all sub-agent calls (chunk extraction, exam-info, validator review). Set to `null` to disable timeouts.
- `IPL_PRESET` selects a named (model, reasoning) configuration: `fast`, `balanced`, `quality`, `local`. When set, overrides `IPL_MODEL` and `IPL_REASONING`.
- CORS origins are currently fixed in code to localhost defaults (not a runtime setting).
- Logging behavior reference:
  - `docs/logging-usage.md`
  - `docs/logging-internals.md`

### Provider API Keys (Always Unprefixed)

These are intentionally not `IPL_`-prefixed and are env-only:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `OPENROUTER_API_KEY`

### Ollama Configuration (Local Models)

Ollama runs models locally without API keys. Set the base URL to connect:

- `OLLAMA_BASE_URL` — Ollama server URL. Add to `.env`: `OLLAMA_BASE_URL=http://localhost:11434/v1`
- `OLLAMA_MAX_LOADED_MODELS` — Set to 4+ for multi-model runs (extraction + reviewer). This is an Ollama server env var, not an app setting.

#### NativeOutput auto-detection

Some Ollama model families (gemma4 MoE, gemma3, deepseek-r1, MedGemma) can't use PydanticAI's tool-calling protocol. The extractor auto-detects these and uses `NativeOutput` (JSON schema mode). Tool-capable families (gpt-oss, llama3/4, qwen3/3.5, nemotron) use the default tool mode. See `ollama_needs_native_output()` in `src/finding_extractor/llm/model_settings.py`.

#### Recommended local config

See `config.toml.example` for Ollama-specific settings (timeout, concurrency, model selection). Custom Modelfiles with extraction-optimized defaults are in `ollama/`.

See `docs/extraction-usage.md` for Ollama setup instructions.

### Logfire Secret (Env Only)

- `LOGFIRE_TOKEN`

## `config.toml` (Optional, Non-Secrets)

`config.toml` is optional and intended for local non-secret defaults.

Supported layouts:

1. top-level keys
2. `[ipl]` section

When both are present, keys from `[ipl]` win.

Example:

```toml
[ipl]
db_path = ".finding_extractor.db"
redis_url = "redis://localhost:6379"
redis_result_ttl = 3600
default_model = "google-gla:gemini-3-flash-preview"
fallback_model = "openai:gpt-5.2"
chunking_semantic_trigger_sentence_count = 4
chunking_semantic_embedding_model = "minishlab/potion-base-32M"
chunking_semantic_threshold = 0.8
chunking_semantic_chunk_size = 2048
chunking_semantic_similarity_window = 3
chunking_semantic_skip_window = 0
chunking_impression_list_chunking_enabled = true
chunking_impression_list_max_items_per_chunk = 3
chunking_impression_list_min_items_per_chunk = 2
reviewer_enabled = true
reviewer_model = "anthropic:claude-opus-4-6"
reviewer_reasoning = "low"
reviewer_reextract_enabled = true
extractor_max_subagent_concurrency = 5
subagent_timeout_seconds = 20.0
# default_preset = "fast"  # overrides default_model and default_reasoning
default_reasoning = "medium"
allow_unknown_model_reasoning = false
batch_run_dir = ".batch_runs"
batch_workers = 4
batch_timeout_seconds = 420
batch_retries = 1
batch_status_interval_seconds = 5.0
batch_output_suffix = ".extracted.json"
batch_resume = true
update_model_list_interval_seconds = 172800
eval_run_dir = ".eval_runs"
eval_workers = 2
eval_timeout_seconds = 120
eval_retries = 0
eval_dataset_dir = "evals/datasets"
log_level = "WARNING"
log_json = false

logfire_enabled = false
logfire_send = "auto"
logfire_service_name = "finding-extractor"
logfire_environment = "dev"
logfire_capture_headers = false
logfire_system_metrics = false
logfire_instrument_provider_sdks = false
```

Use the starter template at `config.toml.example`.

## Secrets Policy

Secrets are rejected from `config.toml`. Put them in env vars only.

Rejected TOML keys include:

- `openai_api_key`
- `anthropic_api_key`
- `google_api_key`
- `logfire_token`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `OPENROUTER_API_KEY`
- `LOGFIRE_TOKEN`

## Local-Only Mode (PHI-Safe)

Set `IPL_LOCAL_ONLY=true` (or pass `--local-only` to `finding-extractor` / `finding-extractor-batch`) to guarantee no report text or extraction output leaves the machine.

> ⚠️ **Known limitation — Modelfile aliases are not inspected.** A local Ollama model built from a Modelfile whose `FROM` points at a `:cloud` / `-cloud` source bypasses the tag-suffix check. If you use Modelfile aliases, verify each one's `FROM` line yourself before running on PHI. Tracked in `docs/plans/local-only-future-tightening.md`.

### What it enforces

Every entry point below validates the resolved model, cloud-suffix tag, and Ollama endpoint before any model call:

| Entry point | Enforcement |
|---|---|
| Settings load | Rejects cloud `IPL_MODEL` / `IPL_FALLBACK_MODEL` / `IPL_REVIEWER_MODEL`; rejects missing or non-loopback `OLLAMA_BASE_URL` |
| `finding-extractor` CLI | Rejects cloud `--model`, cloud `--preset`, and `--logfire`; prints manifest with resolved endpoint |
| `finding-extractor-batch` CLI | Same as above; detached child inherits `IPL_LOCAL_ONLY=true` via subprocess env |
| API `POST /reports/{id}/extract` | 422 if `body.model` is non-Ollama, cloud-routed, or endpoint is remote |
| API `POST /extractions/{id}/code` | 422 — coding is disallowed entirely in local-only mode |
| Extraction worker | Fails the job with `LOCAL_ONLY_VIOLATION` if it reaches here with a cloud model |
| Logfire | Short-circuited; no traces sent regardless of other flags |

### What counts as "local"

- `OLLAMA_BASE_URL` host must be a loopback literal (`127.0.0.1`, `::1`) or a loopback name (`localhost`). Hostnames resolve via `socket.getaddrinfo`; every returned address must be loopback.
- Models with an Ollama cloud-routed tag (`:cloud` or `-cloud` suffix, e.g. `qwen3.5:cloud`, `gpt-oss:120b-cloud`) are rejected — these get proxied to `ollama.com` through the local `ollama serve` process and would leak PHI despite the local wire endpoint.

### What is NOT covered

- `finding-extractor-eval` does not enforce local-only. Eval datasets are fixture data curated in-repo; they are not PHI. Running eval with a cloud model is a valid workflow.
- **Modelfile aliases** — see the warning at the top of this section.
- Air-gapped deployments where Ollama runs on a named private-network host rather than loopback. An `IPL_LOCAL_ONLY_ALLOW_HOSTS` escape hatch was prototyped and then cut as YAGNI — the three loopback gates are unconditional today. See `docs/plans/local-only-future-tightening.md` for the trigger to reopen if someone needs this.

## Common Setup

```bash
# copy starter file
cp config.toml.example config.toml

# provider secret(s)
export OPENAI_API_KEY=...

# optional runtime overrides
export IPL_MODEL=google-gla:gemini-3-flash-preview
export IPL_REASONING=high
```
