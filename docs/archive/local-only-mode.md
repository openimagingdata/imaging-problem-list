# Plan: `--local-only` mode for PHI-safe extraction

**Status:** Completed; retained as historical design notes.

Current behavior is broader than this original Ollama-only plan. `--local-only`
/ `IPL_LOCAL_ONLY=true` now permits approved inference paths: Ollama on a
loopback endpoint and configured vLLM endpoints whose hosts are explicitly
listed in `IPL_VLLM_LOCAL_ONLY_ALLOW_HOSTS`. Cloud providers, Ollama
cloud-routed model tags, unapproved vLLM hosts, Logfire, and coding remain
blocked. The current reference is `docs/configuration.md#local-only-mode`.

## Goal

Provide a single CLI flag that **guarantees** the finding-extractor pipeline does not send any **data-bearing content** (report text, extraction output, PHI) outside approved inference endpoints. The original target was `localhost:11434` (Ollama); the implemented policy now also allows configured, explicitly allowlisted vLLM hosts.

**What "local-only" means:** No report text, extraction results, or PHI-bearing payloads are sent to cloud providers or unapproved hosts. Model weight downloads (HuggingFace, etc.) and metadata-only API calls (model catalog discovery) are allowed — these don't carry input data.

We do **not** rely on OS-level network isolation (sandboxing, pf rules, etc.). The guarantee must be enforceable purely within the application.

## Background — what was learned in the audit

A thorough sweep of the codebase identified the following network egress points (full audit available; summary below):

| # | Source | What it sends | Default | Risk |
|---|---|---|---|---|
| 1 | **Logfire** (`core/observability.py`) | Spans, request bodies if `capture_headers=True` | OFF unless `IPL_LOGFIRE_ENABLED=true` | CONFIRMED — could capture report text via `instrument_httpx` |
| 2 | **Provider SDKs** (PydanticAI `infer_model`) | Whatever the agent sends | Selected by model prefix | CONFIRMED — direct PHI egress if non-Ollama model selected |
| 3 | **Model catalog** (`llm/catalog.py`) | API key + "list models" query | Lazy, needs API keys | METADATA ONLY — no PHI; **acceptable** in local-only mode |
| 4 | **HuggingFace** (`extractor/chunking.py` via Chonkie `SemanticChunker`) | Model download on first run; HEAD checks after | First run downloads `potion-base-32M` | ALLOWED — downloads model weights only, never sends input data |
| 5 | **Coding pipeline** (`coding/`) | Uses `findingmodel` and `anatomic_locations` Python packages | Loaded on import | UNVERIFIED — packages not statically audited; **conservative: disallow** |

Confirmed **not present**: webhooks, analytics beyond Logfire, runtime config fetches, remote example loaders, runtime `git`/`curl`/`pip` invocations.

Local-only by design: SQLite DB, Redis broker (we don't configure non-secure caches), local file I/O.

## Design

### Two layers of enforcement

**Layer 1 — Settings validator (`core/config.py`):** A `model_validator(mode="after")` on `ExtractorSettings` runs at config-load time when `local_only_mode=True`. It:

1. Validates all *settings-level* model fields use `ollama:` prefix: `default_model`, `fallback_model`, `reviewer_model`, `coding_model`, `coding_term_model`, `coding_fallback_model`.
2. Force-overrides `logfire_enabled = False` and clears `logfire_token` regardless of env vars.
3. Raises `ValueError` with full list of offenders on failure.

HuggingFace downloads are **not** restricted — they download model weights only and never send input data.

**Layer 2 — CLI enforcement (`cli/extract.py`, `cli/code.py`):** After the CLI resolves the *effective* model from `--model`, `--preset`, and settings defaults, a second guard runs:

1. Rejects any resolved effective model that doesn't start with `ollama:`. This catches `--local-only --model openai:gpt-5.2` and cloud-backed presets like `fast`, `balanced`, `quality`.
2. Rejects `--logfire` when `--local-only` is active — `configure_logfire(enabled_override=...)` bypasses settings, so the CLI must explicitly block it.
3. `finding-extractor-code` CLI immediately errors in local-only mode.

**Layer 3 — Runtime enforcement (`coding/runtime.py`):** The coding runtime checks `get_settings().local_only_mode` and raises before executing. This covers the API/worker path where coding is triggered via job enqueue, not the CLI.

### Why three layers

The config validator alone is not enough because:
- CLI `--model` and `--preset` resolve the effective model *after* settings load — the validator never sees them.
- CLI `--logfire` overrides `logfire_enabled` via `enabled_override` — the validator's force-disable gets bypassed.
- Coding can be triggered via API/worker, not just the CLI — a CLI-only guard misses those paths.

### CLI surface

```bash
finding-extractor REPORT.txt \
  --model ollama:qwen3.5:35b-a3b \
  --reasoning none \
  --local-only
```

Also wire into:

- The settings `local_only_mode` field can also be set via `IPL_LOCAL_ONLY=true` env var for non-CLI callers (API, worker).

### Startup manifest

When `local_only_mode=True`, the CLI prints a one-time block to stderr **before** any model call:

```
[local-only] Mode active. No report text or extraction output will leave this machine.
  model               = ollama:qwen3.5:35b-a3b
  fallback_model      = (none)
  reviewer            = disabled
  coding              = disallowed
  logfire             = disabled (overridden)
  model downloads     = allowed (no PHI sent)
```

If any precondition fails, exit with a clear error listing offending settings.

## Files to change

1. **`src/finding_extractor/core/config.py`**
   - Add `local_only_mode: bool` field with `IPL_LOCAL_ONLY` alias
   - Add a `model_validator(mode="after")` that enforces Layer 1

2. **`src/finding_extractor/cli/extract.py`**
   - Add `--local-only` flag to the click command
   - After resolving effective model (from `--model`, `--preset`, settings), validate it's `ollama:` prefixed
   - Reject `--logfire` when `--local-only` is active
   - Print the manifest at startup if active

3. **`src/finding_extractor/cli/code.py`**
   - Add `--local-only` flag, immediately error: "coding step not permitted in local-only mode"

4. **`src/finding_extractor/coding/runtime.py`**
   - At entry point, check `get_settings().local_only_mode` and raise if True

5. **`tests/test_model_policy.py`** (existing, already in Taskfile test list)
   - Add local-only tests here to avoid the "new test file not in Taskfile" problem
   - Test: model validation rejects `openai:gpt-5.2`, accepts `ollama:qwen3.5:35b-a3b`
   - Test: rejects each cloud field individually (fallback, reviewer, coding-*)
   - Test: setting forces `logfire_enabled = False` even when env var is `true`
   - Test: setting populates `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`

6. **`docs/configuration.md`** — document the flag and its semantics

## Things deliberately NOT in scope

- OS-level network isolation (`sandbox-exec`, `pf` rules) — user explicitly excluded.
- Auditing the `findingmodel` and `anatomic_locations` Python packages — out of scope for this PR; coding is conservatively disallowed in local-only mode pending that audit.
- Vendoring `potion-base-32M` weights into the repo — separate concern; we just require it to be already cached.
- Runtime network monitoring / verification — out of scope.
- Restricting model catalog discovery — sends metadata only, acceptable.
- Restricting Redis URL — trusted as local per project convention.

## Codex review findings (addressed)

1. ~~CLI model resolution bypasses config validation~~ → Added Layer 2 CLI enforcement
2. ~~`--logfire` flag bypasses logfire_enabled=False~~ → CLI rejects `--logfire` with `--local-only`
3. ~~Coding guard CLI-only but local-only claims non-CLI support~~ → Added Layer 3 runtime enforcement
4. ~~New test file not in Taskfile~~ → Tests go in existing `test_model_policy.py`
