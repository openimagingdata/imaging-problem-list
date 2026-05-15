# Pending Refactoring Backlog

Last updated: 2026-05-14
Status: Active

This is the canonical near-term refactoring/cleanup queue. Longer-horizon improvements live in `docs/future-improvements.md`.

## Open Items

| ID | Priority | Item | Origin |
|---|---|---|---|
| PR-005 | medium | Expand targeted tests for `extraction_review` label allowlist/reextract decisions, and model-catalog fallback regression. | `docs/archive/extractor-agent-roadmap.md` |
| PR-010 | low | Evaluate lightweight agent-instance caching per model only if profiling shows measurable benefit. | former `docs/code-review-2026-02-15.md` |
| PR-015 | low | Reconcile archived CLI persistence residuals: keep/retire `--store-include-validation` and confirm explicit `--store` failure/validation exit-code tests. | `docs/archive/persistence-cli-plan.md` |
| PR-019 | medium | Enforce migration discipline on direct API startup: avoid `create_all()`-bootstrapped unstamped schemas when running `finding-extractor-api` outside the Taskfile/Docker migration path. | PR review on `refactor/package-restructuring` |
| PR-020 | medium | Finish active-doc sweep after package restructuring; update remaining references to removed modules, renamed callbacks, and deleted `ValidationResult.is_valid` semantics. Detailed scope below. | PR review on `refactor/package-restructuring` |
| PR-025 | low | Collapse manual Ollama `reasoning_effort` prefix-matching in `src/finding_extractor/llm/model_settings.py` once Ollama 0.21.3+ native `reasoning_effort`→thinking mapping is parity-verified. Detailed scope below. | 2026-05-14 eval round (Track D) |
| PR-026 | low | Investigate `num_ctx` tuning for Ollama models on the OpenAI-compat endpoint. Currently silently dropped (Ollama issue #6544); the only workaround is a custom Modelfile, which 2026-04-20 eval retired for reliability. Defer until we have evidence num_ctx is a bottleneck. | 2026-05-14 eval round |
| PR-027 | low | Explore combined-extractor pipeline: run `gemma4:26b-nvfp4` + `qwen3.6:35b-a3b-mlx-bf16` in parallel and merge findings. 2026-05-14 quality analysis showed finding-name Jaccard overlap is 0.22–0.50 between the two — they extract complementary vocabularies (Gemma 4 = anatomical-systematic checklist; qwen3.6 = pathology-named). | 2026-05-14 quality comparison |

## Detailed Scope for PR-025

**Context.** Ollama 0.21.3+ ships native `reasoning_effort`→thinking mapping on the OpenAI-compatible endpoint. Our `build_ollama_settings` and `_ollama_supported_reasoning_for_model` currently special-case qwen3.5/3.6, nemotron-3-super, gemma4, qwen3:30b-thinking, and gpt-oss:120b with per-prefix branches (~50 lines total). If the native mapping covers all these families equivalently, the manual plumbing is redundant.

**Pre-condition (do not skip).** Empirically verify on a current Ollama release that bypassing `build_ollama_settings` (i.e., returning `None` for the qwen3.6 prefix) yields the same per-call latency and same empty-`reasoning`/populated-`content` behavior as the manual plumbing. Test specifically with `reasoning_effort=none` on `qwen3.6:35b-a3b-mlx-bf16` and `reasoning_effort=low` on a Nemotron H-MoE model. Capture Logfire trace URLs in the commit message.

**Risks.** The manual plumbing exists because of real bugs (3–5× latency spikes on qwen3.6 at default thinking, FallbackExceptionGroup on chunks with malformed CoT). The collapse must not regress these.

**Scope on collapse.** `_ollama_supported_reasoning_for_model` simplifies to a single tool-capable set plus an explicit "no-reasoning" set for llama-family and qwen3:30b-instruct. `build_ollama_settings` returns `OpenAIChatModelSettings(openai_reasoning_effort=level)` uniformly for tool-capable Ollama families. The `extra_body={"think": ...}` branches for `qwen3:30b-thinking` and `gpt-oss:120b` are evaluated separately — they predate the `reasoning_effort` mapping and may still be needed.

**Test updates.** `tests/test_presets.py`, `tests/test_model_resilience.py`, `tests/test_model_policy.py` simplify in lockstep. If any family fails parity, keep its manual branch with a code comment citing the Logfire trace URL and date.

## Detailed Scope for PR-026

**Context.** Research agent finding 2026-05-14: Ollama's OpenAI-compatible endpoint silently drops `extra_body.options`, so `num_ctx` cannot be set per-request (Ollama issue #6544). The only documented workaround is `ollama create` with a `PARAMETER num_ctx 32768` Modelfile, but the 2026-04-20 eval retired the `gemma4-radextract` custom Modelfile because baked-in decoding parameters caused 2/3 reports to fail.

**Trigger to revisit.** Any of: (a) Ollama merges a fix for #6544 and `extra_body.options` is honored; (b) we have evidence that 256K-context KV cache pressure is a bottleneck for our chunk sizes (currently all chunks <4K tokens, so unlikely); (c) we adopt a context-heavy model where the default context window matters.

**Decision tree if Ollama fixes it.** Add `num_ctx=32768` to `build_ollama_settings` for the local-only path. No Modelfile needed.

## Detailed Scope for PR-027

**Context.** 2026-05-14 quality analysis on the 3 baseline reports showed `gemma4:26b-nvfp4` and `qwen3.6:35b-a3b-mlx-bf16` extract **complementary** finding vocabularies. Jaccard finding-name overlap is 0.22 (MR brain) to 0.50 (XR chest). Gemma 4 surfaces anatomical-systematic checkpoints ("cerebellar tonsil position", "ventricular prominence"); qwen3.6 surfaces pathology-named findings ("ischemic change", "leukoaraiosis"). The 2026-04-20 eval found the same pattern between qwen3.6 and MedGemma; the "strong combination" idea was noted but not implemented.

**Sketch.** Run both extractors on the same report (in parallel if memory headroom allows; sequentially otherwise), merge findings by (finding_name, body_region, presence) tuple — keep both names when descriptions overlap. Output is a union with per-finding provenance ("extracted_by": ["gemma4", "qwen3.6"]).

**Open questions.** (a) Cost/latency budget — both extractors at concurrency=2 against the same 6 reports is ~17 min vs 7 min for one. (b) Merge heuristics — Jaccard <0.50 means many names won't normalize cleanly; need a deduplication strategy that doesn't lose unique catches from either side. (c) Reviewer interaction — does the reviewer still triggers re-extraction sensibly against a merged extraction table?

**Trigger to revisit.** Any user-driven need for higher recall (e.g. completeness audits, IPL temporal-tracking workflows that depend on catching anatomical-systematic negatives).

## Detailed Scope for PR-020

Only active docs should be updated in this pass. Archived docs under `docs/archive/` are historical snapshots and do not need path/name cleanup.

1. `docs/api-internals.md`
- Replace the stale `api_models.py` reference with the current split: request/response contracts live in `api/schemas.py`; store/domain-to-response conversion lives in `api/mappers.py`.
- Update the `api/schemas.py` module description near the top so it no longer says the file contains mapping helpers.
- Review the app lifecycle section so it accurately describes current startup behavior: `create_app()` still calls `store.init()`, while the intended Alembic path is Taskfile/Docker migration preflight rather than API self-migration.

2. `docs/extraction-usage.md`
- Remove the stale statement that `--validate` always returns `is_valid=True`; `ValidationResult.is_valid` was removed and the output now consists of `verbatim_errors` plus `coverage_warnings`.
- Update the Python API example comment from `status_callback` to `progress_callback`.
- Re-read the validation semantics section to ensure it matches current runtime behavior: post-run validation can still produce verbatim errors, and strict reliability mode can fail the run on validation or unrecovered section failures.

3. `docs/eval-internals.md`
- Replace `batch_cli.py` references with the actual current module owning the behavior being described: `cli/batch.py` for Click entrypoints and `cli/batch_engine.py` for run-engine internals.
- Replace `eval_cli.py` with `cli/eval_cmd.py` anywhere the current eval CLI module is referenced.
- Recheck the “Adding a New Evaluator” section so file/module names line up with the current package layout.

4. `docs/coding-agent-design.md`
- Replace `llm_config.defaults` with `llm.defaults`.
- Replace `llm_config.providers` with `llm.model_settings`.
- Sweep the surrounding text for any other pre-restructure module paths or “validator redesign” wording that should now point at the current reviewer/model-settings vocabulary.

5. Cross-doc verification pass
- Run one final `rg` over active docs (excluding `docs/archive/`) for these stale terms: `api_models.py`, `llm_config`, `ValidationResult.is_valid`, `is_valid=True`, `status_callback`, `batch_cli.py`, and `eval_cli.py`.
- If a stale hit is intentional historical commentary, move that note to `docs/archive/` or reword it so it is clearly framed as historical context rather than current guidance.

## Recently Resolved (2026-03 Package Restructuring)

All items below were resolved during the package restructuring effort on `refactor/package-restructuring`:

- **PR-001/002**: Typed `ProgressCallback` Protocol and consolidated emit helpers (`extractor/progress.py`)
- **PR-003**: Reasoning workaround moved to provider settings layer (`resolve_runtime_reasoning()`)
- **PR-004/011**: Extracted `_build_review_callback()` helper; no passthrough chunk duplication found
- **PR-006**: Removed dead `ValidationResult.is_valid` field
- **PR-007**: Inline orchestrator gate-semantics comments added
- **PR-008**: Unified all runtime modules to structlog
- **PR-009**: Removed dead `apply_coding` UI stage label
- **PR-012**: `examples/` is now a subpackage
- **PR-013/014**: Package restructuring (subpackages, `ExtractorSettings`, `ExtractorDeps` move)
- **PR-016**: Testing practices synced with conftest.py fixtures
- **PR-017**: `coding_summary.py` kept at top level (cross-cutting concern)
- **PR-018**: Dead `_resolve_coding_adjudicator_reasoning()` removed

## Scope Rules

- Add near-term cleanup/refactor items here.
- Keep longer-horizon improvements in `docs/future-improvements.md`.
- When an item is completed, move it to "Recently Resolved" and add a concise entry to `docs/DEV_LOG.md`.
