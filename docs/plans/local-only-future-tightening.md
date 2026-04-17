# Plan: Future Local-Only Tightening

**Status:** Not started. Active backlog.
**Context:** The hardening pass ([`docs/archive/local-only-mode-hardening.md`](../archive/local-only-mode-hardening.md)) closed the urgent PHI-egress gaps — shared `enforce_local_only` helper, Layer 1 settings validation, wiring into batch CLI / API / worker / Logfire, cloud-suffix detection for Ollama Turbo. This document collects what we **deliberately deferred** and what we learned along the way, so we can pick it back up when there's a concrete trigger.

Each item names the trigger that should prompt action — not "someday," but "when X happens, reopen this."

## Deferred items

### 1. Modelfile alias detection

**What:** A local Ollama model whose `FROM` points at a `:cloud` / `-cloud` source is not inspected. Current enforcement catches direct references like `ollama:qwen3.5:cloud` but not an alias such as `ollama:my-local-alias` built from a Modelfile whose `FROM` is `qwen3.5:cloud`.

**Why deferred:** Implementation requires an HTTP call to `/api/show` on the resolved model and parsing the Modelfile text / `details.parent_model` field. Ollama's API surface here is not stable across versions, and we'd be parsing unstructured Modelfile text as authoritative — best-effort at best. The hardening pass chose to document this as a known limitation and put a loud warning in the CLI manifest instead.

**Trigger to reopen:** Someone actually builds a local Modelfile that proxies to cloud and it hits production. Or: Ollama exposes a stable `model.source` field in a future version.

**Sketch of implementation:**
- After model-availability preflight, GET `/api/show` with `{"name": resolved}`
- Inspect the `modelfile` text field for `FROM\s+\S*:(cloud|[a-z0-9.-]+-cloud)` (case-insensitive)
- Inspect `details.parent_model` if present
- Reject if either indicates cloud routing
- Document as best-effort (API instability)

### 2. `HF_HUB_OFFLINE` enforcement for chunking model download

**What:** The semantic chunker downloads `minishlab/potion-base-32M` from HuggingFace on first run via `chonkie`. Weights-only download, no PHI sent, but the network touch could surprise a PHI operator who expected "no egress at all."

**Why deferred:** The original local-only plan explicitly allowed model downloads as "no PHI sent." The distinction stands, but first-run operators may not know it. Not a security concern; UX concern.

**Trigger to reopen:** An operator complains ("why did it hit HuggingFace?") or we ship to a genuinely air-gapped environment where no outbound connections are allowed.

**Sketch:**
- Set `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` when `local_only_mode=True`
- Fail with a clear "run `uv run python -c 'from chonkie import SemanticChunker; SemanticChunker()'` once online to pre-download" error if the weights aren't cached
- Optionally: vendor the weights into the repo (small model, but license check needed)

### 3. Typed `ollama_base_url: AnyHttpUrl | None`

**What:** Lean on pydantic's `AnyHttpUrl` for the URL parsing/scheme validation we hand-wrote in `enforce_endpoint_locality`.

**Why deferred:** Works today with `urlparse`. Refactor-tax, not a bug.

**Trigger:** Next time someone touches that code, or if we add another URL-typed setting.

### 4. End-to-end smoke test for the happy path

**What:** A `task test:local-only:smoke` that runs a real `finding-extractor ... --local-only` against local Ollama + a small sample report, asserts the manifest prints and extraction completes. Complements our rejection tests, which only prove that bad input fails.

**Why deferred:** Integration tests that require a running Ollama can't go in `task test` (CI-safe unit suite). We have a pattern (`task test:api:e2e`, `task test:web:e2e`) for preconditioned integration tests. Local-only should follow it.

**Trigger:** Before the next PHI pilot, or as soon as CI gains an Ollama-capable runner.

**Sketch:**
- New Taskfile target `task test:local-only:e2e`
- Precondition: `curl http://localhost:11434/api/tags` succeeds
- Runs extractor against a known-safe test fixture under `--local-only`
- Asserts exit 0, output has `[local-only] Preflight passed`, extraction JSON has findings

### 5. Egress verification (lsof / tcpdump style assertion)

**What:** Above the rejection tests, above the happy-path smoke, the ultimate check: assert that during a local-only extraction, no non-loopback TCP connections are opened. Belt-and-suspenders that the Python-level guards actually matched reality.

**Why deferred:** Platform-specific (lsof on macOS, ss on Linux, netstat elsewhere). Would need careful thought about how to run alongside the extraction without interfering.

**Trigger:** Real PHI pilot, audit requirement, or an incident where we suspect egress we didn't catch.

**Sketch:**
- Background `lsof -i -p <pid>` sampler during a smoke run
- Fail if any address other than `127.0.0.1`/`::1` appears (with exceptions for DNS, HF Hub if item #2 isn't yet resolved)

### 6. Evaluation CLI enforcement

**What:** `finding-extractor-eval` does not enforce local-only. The hardening plan explicitly scoped it out ("eval datasets never contain PHI").

**Why deferred:** By design — eval datasets are curated in-repo. Running eval with cloud models is a valid workflow.

**Trigger to reopen:** If anyone ever proposes running eval against patient-derived data. Then eval needs the same enforcement.

### 7. `IPL_LOCAL_ONLY_ALLOW_HOSTS` (cut from hardening pass)

**What:** A comma-separated list of hostnames that bypass the loopback check, intended for air-gapped deployments where Ollama runs on a named private-network host.

**Why deferred:** Added speculatively in the hardening pass, no real user requesting it. Cut (see commit history) to keep the surface minimal. The three-gate check (provider / cloud-suffix / loopback endpoint) is enforced without exception today.

**Trigger to reopen:** A real deployment asks for it. At that point the design should include:
- Explicit opt-in setting, not default
- Allowlisted hostnames only (not IP literals — those should stay loopback-gated)
- DNS resolution still runs on the allowlisted name (to check the name actually resolves somewhere)
- Manifest logs the resolved IP

## New ideas surfaced during the hardening pass

These don't fit the local-only scope but came out of the audit:

- **Eval report refresh.** Smoke-testing `gemma4-radextract` (MoE) vs `qwen3.5:35b-a3b` under `IPL_LOCAL_ONLY=false` showed gemma4-MoE more reliable on longer reports — the opposite of what `docs/eval-ollama-models-report.md` currently recommends. Consider rerunning the comprehensive dataset with the current pipeline and updating the recommendation.
- **Qwen3.5 post-completion hang.** Dry-run under Ollama completed all chunk POSTs cleanly, then the process idled at 0% CPU for 5+ minutes. Logfire trace ends cleanly after the last chunk; no exception. Likely an asyncio-wait bug in merge/validate. Worth a separate bug hunt; instrumentation is already in place.
- **gemma4-dense reliability.** Hit `extraction_failed:section_failures_remaining` on XR shoulder in ~8.5 minutes. The same error fired on qwen3.5:35b-a3b during the smoke eval. Shared failure mode — suggests a pipeline-level retry/contract bug rather than per-model.

## Out of scope for this plan

- OS-level network isolation (`sandbox-exec`, `pf` rules).
- Vendoring `potion-base-32M` weights into the repo.
- Auditing the `findingmodel` / `anatomic_locations` packages (the coding path stays conservatively blocked under local-only).
