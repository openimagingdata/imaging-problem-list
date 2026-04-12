# Plan: Harden `--local-only` / `IPL_LOCAL_ONLY` Enforcement for PHI Workloads

**Status:** Drafted, not started
**Depends on:** `docs/plans/local-only-mode.md` (merged as commit `23dfc91`)
**Context:** PHI workloads are the next use case. Current enforcement only covers the single-report `finding-extractor` CLI. Batch, API, and worker paths can still reach cloud providers with `IPL_LOCAL_ONLY=true` set. This plan closes those gaps so the guarantee holds on every **PHI-eligible** entry point.

**Explicit scope:** `finding-extractor-eval` is **out of scope** for this plan. Eval datasets are fixture data curated in-repo; they are not PHI. Running eval with a cloud model is a valid workflow. If users ever want to run eval against PHI, that requires a separate (and reconsidered) change — for now the guarantee is "local-only protects the PHI paths; eval can still use cloud models."

## The gaps (confirmed by code audit 2026-04-12)

| Entry point | Current state | Risk |
|---|---|---|
| `finding-extractor-batch` | No `local_only` handling in `cli/batch.py` | PHI batch run could hit cloud model |
| `finding-extractor-eval` | No `local_only` handling in `cli/eval_cmd.py` | **Not a PHI risk** — eval datasets are synthetic/sample. Coverage would be for consistency only, deprioritized. |
| API `POST /reports/{id}/extract` | `services.py:46` uses `body.model or settings.default_model` then only validates syntax | Client-supplied `{"model": "openai:..."}` bypasses everything |
| Worker extraction jobs | Executes whatever model the job was enqueued with | If enqueue bypassed check, worker completes the cloud call |
| Settings `default_model` | Layer 1 validator deliberately skips it (deferred to CLI Layer 2) | `IPL_LOCAL_ONLY=true` + `IPL_MODEL=openai:gpt-5.2` in env passes settings load |

## Design

### Principle

**Move the enforcement from the CLI boundary into a shared preflight function** that every entry point (CLI, API, worker, batch, eval) calls. The CLI-only check was a deliberate shortcut in the original plan; for PHI it is the wrong layer.

### New shared helper

Add `finding_extractor.llm.policy.enforce_local_only(model_name: str, settings: ExtractorSettings) -> None`:

- Raises `LocalOnlyViolation(ValueError)` if `settings.local_only_mode` is True and any of the following:
  1. `provider_from_model_id(model_name) != "ollama"`, OR
  2. The model reference matches Ollama's **cloud-routed** naming convention (see next section), OR
  3. The Ollama endpoint in `OLLAMA_BASE_URL` does **not** resolve to a loopback / private / explicitly-allowlisted host (see "Endpoint-locality check" below).
- Message includes the offending model/host and the enforcement path ("API request", "batch CLI", "worker", "settings default").
- Centralizes the check so all callers benefit from future improvements (e.g. an allowlist of local model-name prefixes).

### Reject Ollama cloud-routed models

Since mid-2025 Ollama supports **cloud models** (branded "Turbo") that the local `ollama serve` process proxies to `ollama.com`. A request to `http://localhost:11434/v1/chat/completions` with a cloud model name keeps the endpoint local on the wire but still ships the prompt to Ollama's cloud infrastructure. The `ollama:` prefix check and the endpoint-locality check would both pass — PHI would still leave the machine.

How the Ollama server distinguishes them (from the source):
- The server parses the model reference and checks `modelRef.Source`. If it equals `modelSourceCloud`, the request is intercepted and routed through the cloud proxy instead of the local scheduler.
- At the naming layer (what we have access to at preflight), cloud models carry a cloud suffix:
  - `:cloud` as a tag, e.g. `qwen3.5:cloud`, `glm-5:cloud`, `kimi-k2.5:cloud`
  - `-cloud` at the end of a tag, e.g. `gpt-oss:120b-cloud`

Rule in `enforce_local_only`:

1. Strip the `ollama:` provider prefix.
2. Split on `:` to get `(repo, tag)` (tag is optional).
3. Reject if:
   - `tag == "cloud"` (case-insensitive), OR
   - `tag.endswith("-cloud")` (case-insensitive), OR
   - `repo.endswith(":cloud")` / `repo.endswith("-cloud")` as a defensive fallback if the tag split was ambiguous.
4. Also reject if the model-availability preflight (`GET /api/tags`) reports a name matching those patterns — covers the case where a cloud model was aliased via a Modelfile pointing at a cloud source.
5. Log the exact reason in the error message ("model '<name>' is an Ollama cloud-routed model (`-cloud` / `:cloud` suffix); cloud-routed models proxy through ollama.com and are not permitted under --local-only").

The Modelfile-alias case is worth flagging: if a user creates a local Modelfile named `gemma4-local` whose `FROM` points at `gpt-oss:120b-cloud`, the reference we see is `ollama:gemma4-local`. Mitigation: in the preflight, after confirming the model is present locally, call `/api/show` for the resolved name and inspect the `details.parent_model` / `modelfile` text for any cloud suffix in the resolved source. Reject on match. Document this as best-effort (Ollama's API surface may not expose the full chain) and mention it as a known limitation.

### Endpoint-locality check (`OLLAMA_BASE_URL`)

`ollama:` as a model-name prefix does **not** mean the endpoint is local — `OLLAMA_BASE_URL` can point at any HTTP endpoint. Any path that claims to keep data on the machine must also assert that the Ollama endpoint is local.

Rules:

1. Parse `OLLAMA_BASE_URL`. If unset, reject (Ollama will refuse anyway, but fail loud at preflight).
2. Scheme must be `http` or `https`.
3. Host must be one of:
   - `localhost` or `localhost.localdomain`
   - An IPv4 address in `127.0.0.0/8`
   - IPv6 `::1`
   - A hostname the user explicitly allowlisted via a new setting `IPL_LOCAL_ONLY_ALLOW_HOSTS` (comma-separated). This exists for air-gapped deployments where Ollama runs on another host reachable only via a private network; the user must opt into each hostname.
4. If the host is a name (not an IP), resolve it via `socket.getaddrinfo` and require **every** returned address to match rule 3. Reject if resolution fails or any address is public.
5. Apply this check in the shared preflight and in every entry point listed below.

Log the resolved host/IP(s) in the manifest so operators can audit what "local" actually meant at runtime.

### Close Layer 1 gap: validate `default_model`

### Close Layer 1 gap: validate `default_model` and `OLLAMA_BASE_URL`

In `config.py::_enforce_local_only`, also validate `default_model`. When `local_only_mode` is True and `default_model` is non-Ollama, raise `ValueError` at settings load. This catches `IPL_LOCAL_ONLY=true` + `IPL_MODEL=openai:...` before any entry point runs.

Also call the endpoint-locality check from the validator so a settings-load-time failure covers `IPL_LOCAL_ONLY=true` with `OLLAMA_BASE_URL=https://ollama.some-vendor.com/v1`.

Rationale: the original plan deferred this to CLI Layer 2 to allow CLI overrides, but:
- CLI overrides can still be applied *after* settings load by re-building settings with `model_copy(update=...)` (already done in `extract.py:275-287`).
- API and worker paths never hit CLI Layer 2, so settings must be the source of truth for them.

### Per-entry-point enforcement

| Entry point | Change |
|---|---|
| `cli/batch.py` | Add `--local-only` flag mirroring `extract.py`. Call `enforce_local_only(effective_model, settings)` before run. Print same manifest. |
| `cli/eval_cmd.py` | **Out of scope** — eval is not a PHI path. See "Explicit scope" note at the top of this plan. |
| `api/services.py::enqueue_extraction_job` | After resolving `model_name`, call `enforce_local_only(model_name, settings)`. On violation, return HTTP 422 with body explaining that the server is in local-only mode and the requested model or endpoint is not local. |
| `worker/extraction_jobs.py` | Defence in depth: at job start, after model resolution, call `enforce_local_only` against `settings`. Fail the job with a stable public error code (`LOCAL_ONLY_VIOLATION`). |
| `api/services.py::enqueue_coding_job` | Already covered by `coding/runtime.py:264` — but add an early 422 in the API so we reject at enqueue time rather than fail the job silently. |

### CLI preset guard

`--preset fast|balanced|quality` currently resolves to cloud models. When `--local-only` is active, presets should either:
- Be rejected with a clear error, OR
- Only resolve to the `local` preset.

Pick rejection — it's less surprising.

### Logfire defence in depth

Layer 1 already forces `logfire_enabled=False` and clears `logfire_token`. Add a second check in `core/observability.py::configure_logfire`: if `settings.local_only_mode` is True, short-circuit and log a warning, regardless of the `enabled_override` argument. This prevents any future code path from enabling Logfire via an override when local-only is set.

### `body.model` explicit rejection

When the API is in local-only mode and `body.model` is explicitly set to a non-Ollama provider, return a dedicated error — don't fall back to the default. Reason: silent substitution would surprise callers and mask misconfiguration.

## Testing

Add to `tests/test_model_policy.py` (already in Taskfile test list):

1. `enforce_local_only` raises for each cloud provider (`openai:`, `anthropic:`, `google-gla:`, `openrouter:`)
2. `enforce_local_only` passes for `ollama:<anything>` with a loopback `OLLAMA_BASE_URL`
3. `enforce_local_only` is a no-op when `local_only_mode=False`
4. Layer 1 now rejects `default_model=openai:...` with `local_only_mode=True`
4a. `enforce_local_only` rejects `OLLAMA_BASE_URL=https://ollama.example.com/v1` (public host) under `local_only_mode=True`, even with an `ollama:` model
4b. `enforce_local_only` accepts `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`, `http://[::1]:11434/v1`, and `http://localhost:11434/v1`
4c. `enforce_local_only` accepts a hostname listed in `IPL_LOCAL_ONLY_ALLOW_HOSTS` even if it resolves to a private address; rejects the same hostname when not listed
4d. `enforce_local_only` rejects when hostname resolution fails or returns any public address
4e. `enforce_local_only` rejects `ollama:qwen3.5:cloud`, `ollama:gpt-oss:120b-cloud`, `ollama:glm-5:cloud`, `ollama:Qwen3.5:CLOUD` (case-insensitive)
4f. `enforce_local_only` accepts `ollama:qwen3.5:35b-a3b`, `ollama:gpt-oss:120b`, `ollama:gemma4-radextract` (no cloud suffix)
4g. `enforce_local_only` rejects a locally-aliased model (e.g. `ollama:my-alias`) whose `/api/show` response reveals a `-cloud`/`:cloud` parent; documents this as best-effort

Add to `tests/test_api.py`:

5. `POST /reports/{id}/extract` with `{"model": "openai:gpt-5.2"}` returns 422 when `IPL_LOCAL_ONLY=true`
6. `POST /reports/{id}/extract` with `{"model": "ollama:qwen3.5:35b-a3b"}` succeeds under the same setting
7. `POST /extractions/{id}/code` returns 422 when `IPL_LOCAL_ONLY=true` (instead of 202 → failed job)

Add to `tests/test_tasks.py`:

8. Extraction worker fails the job with `LOCAL_ONLY_VIOLATION` when given a cloud model under `IPL_LOCAL_ONLY=true`

Add to `tests/test_batch_cli.py`:

9. `--local-only` with cloud `--model` errors
10. `--local-only` with `ollama:...` succeeds (or gets past the preflight)

## Documentation

- Update `docs/configuration.md` local-only section to reflect the new enforcement matrix (every entry point, not just CLI)
- Update `docs/plans/local-only-mode.md` to cross-reference this hardening plan and strike the "CLI-only validation" language
- Note in `docs/DEV_LOG.md`
- Update `CHANGELOG.md` entry for users: "`--local-only` now enforced in batch, API, and worker paths (previously single-report CLI only). It also verifies `OLLAMA_BASE_URL` resolves to a local/allowlisted host and rejects Ollama cloud-routed models (`:cloud`, `-cloud` suffixes). Eval is unchanged (not a PHI path)."

## Out of scope

- Auditing `findingmodel` / `anatomic_locations` packages (still conservatively blocks coding)
- OS-level network isolation
- Runtime network verification / tcpdump-style assertions
- Vendoring HuggingFace model weights

## Completion checklist

- [ ] Add `enforce_local_only` helper (model + cloud-suffix + endpoint locality) with tests
- [ ] Add `IPL_LOCAL_ONLY_ALLOW_HOSTS` setting
- [ ] Layer 1: validate `default_model` and `OLLAMA_BASE_URL` in `_enforce_local_only`
- [ ] `cli/batch.py`: `--local-only` flag + preflight
- [ ] ~~`cli/eval_cmd.py`~~ — out of scope; eval is not a PHI path
- [ ] `api/services.py`: enforce in both extraction and coding enqueue paths
- [ ] `worker/extraction_jobs.py`: defence-in-depth check
- [ ] `core/observability.py`: short-circuit logfire under local-only
- [ ] CLI: reject cloud-backed presets under local-only
- [ ] Extend `extract.py` manifest to include resolved Ollama host/IP
- [ ] Tests 1-10 (including 4a-4d endpoint-locality cases) added and passing
- [ ] `docs/configuration.md`, `docs/plans/local-only-mode.md`, `DEV_LOG.md`, `CHANGELOG.md` updated
- [ ] Mark this plan complete
