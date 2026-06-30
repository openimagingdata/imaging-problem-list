# Simplify reasoning plumbing using PydanticAI's unified `thinking` field

## Context

We maintain a large custom layer (`src/finding_extractor/llm/model_settings.py`, ~728 lines) that translates our 5-level reasoning knob (`none` / `minimal` / `low` / `medium` / `high`) into each provider's native thinking parameters — `openai_reasoning_effort`, `anthropic_thinking` (budget-based vs adaptive based on minor version), `GoogleModelSettings` thinking config, OpenRouter effort, Ollama `reasoning_effort` / `extra_body.think`, vLLM. Much of this predates PydanticAI's new unified thinking support.

PydanticAI has since added two overlapping features that do almost exactly what our dispatcher does:

1. **Unified `thinking` field in `ModelSettings`** — accepts `True` / `False` / `'minimal'` / `'low'` / `'medium'` / `'high'` / `'xhigh'`. At request time each `Model` implementation translates it to the provider-native knob (e.g. `OpenAIChatModel._translate_thinking` → `reasoning_effort`; Anthropic → adaptive on Opus 4.6+, budget-based on older). Provider-specific settings still take precedence when both are set.
2. **`Thinking` capability** (`from pydantic_ai.capabilities import Thinking`) — purely syntactic sugar that emits `ModelSettings(thinking=effort)`.

The provider translation table in the PydanticAI docs matches what our `build_*_settings()` functions do today — including the Opus 4.6+ adaptive vs pre-4.6 budget split that our `_anthropic_uses_adaptive_thinking` / `ANTHROPIC_THINKING_BUDGETS` / `ANTHROPIC_EFFORT_MAP` implement by hand.

**Version caveat:** we're pinned at `pydantic-ai 1.68.0`; unified `thinking` and `capabilities.Thinking` ship in later 1.x releases (current latest is 1.86.1, 2026-04-24). Upgrading is a prerequisite.

**Goal:** delete the OpenAI / Anthropic / Google / OpenRouter builders and the Anthropic-version-detection helpers, leaning on PydanticAI's unified field for those providers. Keep the project-specific policy and endpoint layers untouched.

## What gets simpler, and what does not

**Delete / collapse (handled natively by unified `thinking`):**
- `build_openai_settings` (`model_settings.py:509-511`)
- `build_anthropic_settings` plus its version-aware branches (`model_settings.py:514-541`)
- `build_google_settings` (`model_settings.py:544-555`)
- `build_openrouter_settings` (`model_settings.py:558-573`)
- `_anthropic_uses_adaptive_thinking` (`model_settings.py:97-104`)
- Module-level tables `ANTHROPIC_THINKING_BUDGETS` and `ANTHROPIC_EFFORT_MAP` (`model_settings.py:78-94`)
- The dispatch branches for `openai` / `anthropic` / `google` / `openrouter` inside `get_model_settings` (`model_settings.py:669-676`)

Rough size: ~110 lines removed from `model_settings.py`.

**Keep as-is (project policy / endpoint-specific — unified field does not cover these):**
- Provider detection & model-ID validation in `llm/policy.py` (Anthropic 4.5/4.6 gate, Gemini 3 pro/flash gate, vLLM allowlist, local-only enforcement).
- **`build_ollama_settings` stays entirely on the explicit-knob path (`model_settings.py:576-610`).** This is load-bearing safety, not a stylistic choice: the in-file comment (`model_settings.py:591-595`) documents that Qwen3.5/3.6 and Nemotron families think-by-default on Ollama's OpenAI-compat endpoint and that tool-calling hangs with ~300s timeouts unless `openai_reasoning_effort="none"` is explicitly sent. PydanticAI's unified `_translate_thinking` only emits `reasoning_effort` when truthy (`False` skips the field entirely on older pathways — exact wire behavior varies by release), and Ollama also needs `extra_body.think` (bool / level) for `qwen3:30b-thinking` and `gpt-oss:120b`. Until a captured Ollama request proves `thinking=False` produces an identical wire payload to explicit `openai_reasoning_effort="none"`, we do not migrate any Ollama branch. This is a deliberate no-change zone.
- `build_vllm_settings` (`model_settings.py:613-624`) and `infer_runtime_model` / `_build_vllm_model` in `resilience.py` — base-URL routing and explicit `OpenAIChatModel` construction are project-specific. No change.
- The per-family reasoning-support matrices (`_google_supported_reasoning_for_model`, `_openai_supported_reasoning_for_model`, `_vllm_supported_reasoning_for_model`, `_ollama_supported_reasoning_for_model`) and `resolve_runtime_reasoning` — these enforce *which levels are allowed per model*, independent of how PydanticAI translates them. PydanticAI silently maps unsupported effort levels to "closest available"; we want hard errors for policy compliance.
- NativeOutput auto-detection in `resilience.resolve_output_type` — orthogonal to thinking.
- Resilience layer (`FallbackModel`, `PinnedModelSettingsModel`, `ProviderConcurrencyLimitedModel`) — unchanged.
- Presets, defaults table, capability metadata — unchanged.

**Defensive normalization inside `get_model_settings`:** `resolve_runtime_reasoning` is the front door, but `get_model_settings` is also called directly from tests and could be called by future code. Since PydanticAI silently coerces unsupported levels, `get_model_settings` must not rely on callers to pre-validate. For the cloud providers we migrate (OpenAI / Anthropic / Google / OpenRouter), `get_model_settings` will still call the per-family supported-set check (`_openai_supported_reasoning_for_model`, `_google_supported_reasoning_for_model`, etc.) and raise on mismatch before handing off to the unified field. This preserves the hard-error semantics the project relies on for policy compliance.

## Approach

Use the **unified `ModelSettings.thinking` field** rather than the `Thinking` capability. Reason: our `PinnedModelSettingsModel` composition (for `FallbackModel` stacks) operates on `ModelSettings` objects; capabilities attach at `Agent` level and wouldn't flow through the pinned-settings wrapper. The capability is a pure sugar layer over the field, so we lose nothing.

### Step-by-step

1. **Write the plan** (this file). Add a short entry in `docs/DEV_LOG.md` describing the refactor intent and linking to this plan. First step per project convention.

2. **Bump PydanticAI.** Update `pyproject.toml` pin from `pydantic-ai>=1.0.0` to `pydantic-ai>=1.80.0` (first version with unified `thinking` + `capabilities`). Run `uv sync` and the test suite to confirm the bump is clean before any code changes.

3. **Rewrite `get_model_settings`** in `src/finding_extractor/llm/model_settings.py`:
   - Map our reasoning vocabulary to the unified field: `"none" → False`, `"minimal"|"low"|"medium"|"high" → same string`.
   - For providers `openai`, `anthropic`, `google`, `openrouter`: *inside* `get_model_settings`, re-validate the level against the provider/model's supported set (reusing the existing `_*_supported_reasoning_for_model` helpers) and raise `ValueError` on mismatch; then return `ModelSettings(thinking=<mapped>)`. This keeps the hard-error policy even if a caller bypasses `resolve_runtime_reasoning`. Delete the four per-provider builders (`build_openai_settings`, `build_anthropic_settings`, `build_google_settings`, `build_openrouter_settings`) and the Anthropic version helpers/tables (`_anthropic_uses_adaptive_thinking`, `ANTHROPIC_THINKING_BUDGETS`, `ANTHROPIC_EFFORT_MAP`).
   - For `ollama`: **no change.** Keep `build_ollama_settings` exactly as it stands — including the qwen3.5/3.6/nemotron `openai_reasoning_effort="none"` branch that prevents tool-calling hangs, and the `extra_body.think` branches for `qwen3:30b-thinking` / `gpt-oss:120b`. Do not migrate any Ollama branch in this refactor.
   - For `vllm`: no change. Keep `build_vllm_settings` as-is.
   - `resolve_runtime_reasoning` stays untouched as the primary front-door validator; the per-family supported-set helpers are now also called directly from `get_model_settings` as a defensive second line for the migrated providers.

4. **Update `docs/configuration.md`** sections on reasoning-level translation to describe the unified field and the two remaining custom branches (Ollama `extra_body.think` families, vLLM endpoint routing). Update `config.toml.example` only if any user-facing env var names change (none expected).

5. **Update tests.** The bulk of the settings-shape coverage lives in `tests/test_extraction.py`, not in a dedicated model-settings file. Specifically:
   - **`tests/test_extraction.py` — substantial rewrite.** This file currently imports `_anthropic_uses_adaptive_thinking` (line 17) and asserts the legacy settings shapes:
     - `TestMultiProviderSettings` (class starting at line 88) asserts `provider_settings["openai_reasoning_effort"] == "medium"`, `provider_settings["anthropic_thinking"]["type"] == "enabled"`/`"disabled"`/`"adaptive"`, and explicit `budget_tokens` values (e.g. 1024, 4096, 10240, 16384) at multiple assertion sites (approximately lines 96-270).
     - `TestAnthropicAdaptiveDetection` (class at line 353) is dedicated to the helper we're deleting — lines 357, 360, 363, 366, 369 all exercise `_anthropic_uses_adaptive_thinking`. Delete this class outright.
     - Additional settings-shape assertions at lines 336, 343, 350, 696, 862 cover `openai_reasoning_effort`.
     For all the migrated-provider assertions, rewrite to expect the unified shape: `settings["thinking"] == "low"` / `"medium"` / `"high"` / `False`. For Anthropic specifically, we lose the ability to assert `budget_tokens` directly — that now happens inside PydanticAI at request time. Replace those assertions with (a) the unified value we set, and (b) a contract-level assertion that the settings dict is a plain `ModelSettings` (not `AnthropicModelSettings`).
   - **`tests/test_model_resilience.py`** — the `AgentModelRuntime.model_settings` shape assertions (lines 49-91) also need updating from provider-specific settings classes to the plain `ModelSettings(thinking=...)` shape.
   - **`tests/test_model_policy.py`** — unaffected; policy/validation surface is unchanged.
   - **`tests/test_model_catalog.py` / `tests/test_models.py`** — check for any shape assertions during implementation (`grep` for `anthropic_thinking` / `openai_reasoning_effort` / `_anthropic_uses_adaptive_thinking` across the full `tests/` tree before committing).
   - **New regression tests** (add to `tests/test_extraction.py` alongside the rewritten block): (a) `"none" → thinking=False` mapping, (b) each migrated provider produces `ModelSettings(thinking=...)` and not a provider-specific settings subclass, (c) direct call to `get_model_settings` with an unsupported level (e.g. `"minimal"` on `openai:gpt-5.2`) still raises `ValueError` — proving the defensive in-function validation works, (d) Ollama branches (both `reasoning_effort` and `extra_body.think` families) still emit the pre-refactor shape unchanged.

6. **Run full test suite + lint.** Per `task --list`: `task test` (lean core / unit), `task test:api` (backend unit/component without Docker), and `task lint` — which already runs ruff and `ty` (there is no separate `task typecheck`). Fix any fallout — do not defer.

7. **End-of-plan documentation sweep** (per project convention):
   - Update `docs/DEV_LOG.md` with the completed-state summary.
   - Update `docs/configuration.md` if anything shifted during implementation.
   - Mark this plan file complete; consider moving to a `docs/plans/archive/` subfolder if that is the project's archival convention (check `ls docs/plans/` first).

## Critical files

- `src/finding_extractor/llm/model_settings.py` — primary target, ~110 lines deleted and builder dispatch simplified; defensive in-function validation added for migrated providers
- `src/finding_extractor/llm/policy.py` — unchanged
- `src/finding_extractor/llm/resilience.py` — unchanged (double-check `PinnedModelSettingsModel` still behaves with plain `ModelSettings`, which it should)
- `src/finding_extractor/llm/defaults.py` — unchanged
- `src/finding_extractor/core/config.py` — unchanged
- **`tests/test_extraction.py` — major rewrite** of `TestMultiProviderSettings` block and deletion of `TestAnthropicAdaptiveDetection`; remove the `_anthropic_uses_adaptive_thinking` import (line 17); update all `openai_reasoning_effort` / `anthropic_thinking` shape assertions to the unified `thinking` shape
- `tests/test_model_resilience.py` — update settings-shape assertions on `AgentModelRuntime.model_settings`
- `tests/test_model_catalog.py`, `tests/test_models.py` — audit for legacy shape assertions (grep before committing)
- `tests/test_model_policy.py` — unchanged
- `pyproject.toml` + `uv.lock` — version bump to `pydantic-ai>=1.80.0`
- `docs/configuration.md`, `docs/DEV_LOG.md`, `config.toml.example` — docs sweep

## Existing utilities to reuse

- `provider_from_model_id` (`llm/policy.py:81`) — already the single source of truth for provider detection; rewritten `get_model_settings` keeps calling it.
- `resolve_runtime_reasoning` (`llm/model_settings.py:436`) — stays as the "resolve + validate against policy" front door; unchanged.
- `create_resilient_agent` / `build_resilient_model` (`llm/resilience.py:296`, `:255`) — continue to receive a `ModelSettings | None` from `get_model_settings` exactly as today.

## Verification

1. **Unit tests:** `uv run pytest tests/test_extraction.py tests/test_model_policy.py tests/test_model_resilience.py tests/test_model_catalog.py tests/test_models.py -v`. Settings-shape tests must show the new `thinking=...` output; policy tests must still pass unchanged. There is no `tests/test_model_settings.py`.
2. **End-to-end extraction smoke tests — one per provider branch:**
   - OpenAI (`openai:gpt-5.2`, reasoning `low`) — confirm `thinking='low'` in `ModelSettings` arrives at the model and `reasoning_effort=low` is sent on the wire (capture via Logfire or a recorded request).
   - Anthropic Opus 4.6+ — confirm adaptive-thinking path is still exercised (PydanticAI translates `thinking='high'` → adaptive + `anthropic_effort='high'` internally on 4.6+).
   - Anthropic pre-4.6 (if still in the catalog) — confirm budget-based thinking is still emitted (PydanticAI translates `thinking='high'` → `budget_tokens=16384` on older models).
   - Google Gemini 3 flash — confirm thinking config is still emitted.
   - Ollama qwen3.6 (local-only flow) — **no code change; regression check only.** Explicit `openai_reasoning_effort="none"` must still be sent; tool-calling must not hang.
   - Ollama qwen3:30b-thinking / gpt-oss:120b — `extra_body.think` branch still intact.
   - vLLM gpt-oss-120b — reasoning still plumbed through to the configured endpoint.
3. **Full batch run:** `uv run finding-extractor-batch` against a small `sample_data/` fixture with the default preset to catch any regression in the real extraction path. (The project scripts are `finding-extractor`, `finding-extractor-batch`, `finding-extractor-code`, `finding-extractor-api`, `finding-extractor-eval` — per `pyproject.toml [project.scripts]`.)
4. **Lint:** `task lint` (runs ruff + ty + web + json + toml + migration drift in one pass). There is no separate `task typecheck`.
5. **Documentation review:** re-read `docs/configuration.md` and `README.md` reasoning sections after the change to make sure user-facing docs still match reality.
