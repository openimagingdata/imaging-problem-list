# Model Selection Notes

Last updated: 2026-04-24
Status: Active reference

## Current Defaults

1. Extraction model default: `google-gla:gemini-3-flash-preview`
2. Extraction fallback default: `openai:gpt-5.2`
3. Reviewer model: `openai-responses:gpt-5.4-mini`, reasoning=`low`
4. Provider default reasoning:
   - `google`: `low`
   - `openai`: `medium`
   - `anthropic`: `medium`
   - `openrouter`: `medium`
   - `ollama`: `none`
   - `vllm`: `none`
5. Local profile default: extractor `ollama:qwen3.6:35b-a3b-mlx-bf16`, reviewer `ollama:qwen3.6:35b-a3b-bf16` with reasoning=`low`, fallback `ollama:gpt-oss:20b`.
6. On-prem vLLM profile: extractor `vllm:google/gemma-4-31B-it`, reviewer/fallback `vllm:openai/gpt-oss-120b`.

## What We Learned (Chunk-Extraction Focus)

1. Prompt size and schema fit matter more than forcing higher reasoning.
2. Gemini Flash is the best default throughput baseline for chunk extraction.
3. GPT-5.2 is a strong fallback for resilience when primary provider calls fail.
4. Repeated Sonnet diagnostics showed 4.6 faster than 4.5 for this chunk task, but still slower than Flash/GPT defaults.
5. Gemini model-family reasoning settings must be model-aware:
   - `gemini-3.1-pro*`: supports `low|high`
   - `gemini-3-flash*`: supports `minimal|low|medium|high`
6. Local model guidance changes quickly. Keep the active local defaults aligned with `src/finding_extractor/llm/defaults.py`, `.env.ollama.example`, `.env.vllm.example`, and `config.toml.example`.

## Curated Common Models

Canonical source in code:
- `src/finding_extractor/llm/defaults.py`
- `src/finding_extractor/llm/model_settings.py` (`EXTRACTION_PRESETS`, `format_preset_help_summary()`)

1. `google-gla:gemini-3-flash-preview` (default extraction, reasoning=`low`)
2. `openai:gpt-5.2` (default fallback, reasoning=`low` when explicitly selected for this workflow)
3. `anthropic:claude-opus-4-6` (high-quality validator/extraction option, reasoning=`low`)
4. `google-gla:gemini-3.1-pro-preview` (strong Google quality option, reasoning=`low`)
5. `google-gla:gemini-3.1-flash-lite-preview` (fast low-cost Google option, reasoning=`low`)
6. `ollama:qwen3.6:35b-a3b-mlx-bf16` (local default extractor, reasoning=`none`)
7. `ollama:qwen3.6:35b-a3b-bf16` (local default reviewer, reasoning=`low`)
8. `ollama:qwen3.6:35b-a3b-q8_0` (local Q8 alternative, reasoning=`none`)
9. `ollama:gemma4:26b-mxfp8` (local quality extractor, profile reasoning=`none`)
10. `ollama:medgemma:27b` (local medical specialist extractor, profile reasoning=`none`)
11. `ollama:qwen3.5:9b` (cataloged local ultralight; no longer recommended on high-memory Apple Silicon)
12. `ollama:qwen3:30b-instruct` (legacy local baseline, reasoning=`none`)
13. `ollama:qwen3:30b-thinking` (legacy local thinking-capable option, reasoning=`low`)
14. `ollama:gpt-oss:120b` (local heavy reasoning option, reasoning=`medium`; no longer the recommended reviewer)
15. `vllm:google/gemma-4-31B-it` (on-prem vLLM extractor, reasoning=`none`)
16. `vllm:openai/gpt-oss-120b` (on-prem vLLM reviewer/fallback, reasoning=`medium`)

Profile-only defaults not in `COMMON_MODELS`:
- `openai-responses:gpt-5.4-mini` is the current default reviewer from settings.
- `ollama:gpt-oss:20b` is the `.env.ollama.example` lightweight fallback.

Reasoning notes for curated local models:
- `ollama:qwen3.5:*` / `ollama:qwen3.6:*`: `none|low|medium|high`; runtime sends explicit `reasoning_effort` because these families think by default on the OpenAI-compatible endpoint
- `ollama:nemotron-cascade-2*` / `ollama:nemotron-3-super*`: `none|low|medium|high`; same explicit `reasoning_effort` handling as Qwen3.5/3.6
- `ollama:qwen3:30b-instruct`: `none` only
- `ollama:qwen3:30b-thinking`: all reasoning inputs accepted; runtime maps `none` to `think=false` and non-`none` to `think=true`
- `ollama:gpt-oss:120b`: `none|low|medium|high` accepted; `minimal` normalizes to `low`
- `ollama:gemma4:*`, `ollama:medgemma:*`, and `ollama:gpt-oss:20b`: recommended with reasoning `none` through `.env.ollama` / `IPL_ALLOW_UNKNOWN_MODEL_REASONING=true`; they are not currently verified by the strict family compatibility matrix
- `vllm:google/gemma-4-31B-it`: `none` only
- `vllm:openai/gpt-oss-120b`: `none|low|medium|high` accepted; `minimal` normalizes to `low`

Structured-output notes:
- PydanticAI uses tool calls for structured output by default.
- The extractor routes configured `vllm:` models through `NativeOutput` / JSON-schema output because the current endpoints reject tool-calling requests unless launched with a tool-call parser.
- Ollama Gemma 3, DeepSeek-R1, MedGemma, `nemotron-cascade-2`, and unknown custom model names use `NativeOutput`. Gemma 4, Qwen3/3.5/3.6, gpt-oss, llama3/4, and other Nemotron families use tool mode.

## Reviewer Model Evaluation (2026-03-16)

Tested all permutations of `gemini-3.1-flash-lite-preview`, `gemini-3-flash-preview`, and `gpt-5.2` in extractor and reviewer roles on a CT abdomen report (10 chunks).

### Reviewer comparison

| Reviewer | Catches real issues? | Re-extractions | Judgment |
|----------|:----:|---:|---|
| `gpt-5.2` / low | Yes | 1 | Precise — flags only real problems |
| `gemini-3-flash-preview` | No | 0 | Permissive — misses incorrect locations |
| `gemini-3.1-flash-lite-preview` | Yes | 3–5 | Over-triggers — catches real issues plus false positives |

Key test case: extractor assigns "gallbladder" as location for a finding whose chunk text doesn't mention gallbladder. GPT-5.2 catches this consistently. Flash misses it entirely (zero rationale). Flash-lite catches it but also flags 2–4 other chunks unnecessarily.

### Reasoning level comparison (GPT-5.2 reviewer)

| Reasoning | Review avg | Re-extractions | Notes |
|-----------|----------:|---------:|---|
| `none` | 3.4s | 5 | Too aggressive — over-flags without thinking |
| `low` | 7.8s | 1 | Best balance — catches real issues only |
| `medium` | 6.7s | 1 | No improvement over low, slower overall |

### Extractor comparison

| Extractor | Avg call | Findings | Quality notes |
|-----------|----------:|---:|---|
| `gemini-3-flash-preview` | 2.0s | 42–44 | Best speed/quality balance |
| `gemini-3.1-flash-lite-preview` | 2.0s | 40–42 | Lower quality, needs more corrections |
| `gpt-5.2` | 7.0s | 43–44 | Good quality, 3.5x slower |

### Best combinations by total runtime (2026-03-16)

| Extractor | Reviewer | Total | Findings | Re-extractions |
|-----------|----------|------:|---------:|---:|
| flash-lite | flash | 10.5s | 42 | 0 (reviewer misses real issues) |
| flash | flash-lite | 13.3s | 43 | 3 (reviewer over-triggers) |
| **flash** | **gpt-5.2** | **19.4s** | **44** | **1** (previous default) |
| gpt-5.2 | flash | 20.8s | 44 | 0 (slow extractor, permissive reviewer) |

## GPT-5.4-mini/nano Evaluation (2026-03-18)

Tested `gpt-5.4-mini` (reviewer) and `gpt-5.4-nano` (extractor) across two CT abdomen reports. Both require `openai-responses:` prefix (Responses API) for reasoning + tools.

### gpt-5.4-mini as reviewer

| Extractor | Total | Findings | Re-extracts | Review avg |
|-----------|------:|---------:|------------:|-----------:|
| flash (report 1, run 1) | 15.9s | 42 | 3 | 2.1s |
| flash (report 1, run 2) | 12.4s | 43 | 1 | 1.8s |
| flash (report 2) | 14.6s | 69 | 3 | 1.8s |
| nano (report 1, run 1) | 13.1s | 43 | 1 | 1.7s |
| nano (report 1, run 2) | 15.6s | 42 | 2 | 1.9s |
| nano (report 2) | 18.6s | 70 | 2 | 1.9s |
| flash-lite (report 1) | 11.0s | 40 | 2 | 2.0s |
| flash-lite (report 2) | 17.1s | 69 | 5 | 2.0s |

gpt-5.4-mini catches the same chunk_3 location error that gpt-5.2 catches, at 2.5x the speed (1.7–2.1s vs 4–5s) and lower cost ($0.75/$4.50 per 1M vs gpt-5.2 pricing). **New default reviewer.**

### Reasoning level comparison (gpt-5.4-mini reviewer)

| Reasoning | Reasoning tokens/chunk | Re-extracts | Notes |
|-----------|----------:|---:|---|
| `none` | 0 | 3 | Over-flags (chunk_4 got 5 problems); same pattern as gpt-5.2/none |
| **`low`** | **32–323** | **1–2** | **Correct — small reasoning budget prevents over-flagging** |

gpt-5.4 family defaults to `none` if `reasoning_effort` is omitted. Explicitly setting `low` is necessary for precise reviewer judgment.

**Note:** gpt-5.4-family models require `openai-responses:` prefix (Responses API). The Chat Completions API returns 400 when combining `reasoning_effort` with `tool_choice`.

### Extractor comparison with gpt-5.4-mini reviewer

| Extractor | Avg call | Findings (2 reports) | Re-extracts | Notes |
|-----------|----------:|---:|---:|---|
| `gemini-3-flash-preview` | 2.2s | 42–43 / 69 | 1–3 | Best speed/quality balance, remains default |
| `gpt-5.4-nano` | 2.9–3.1s | 42–43 / 70 | 1–2 | Good quality, ~30% slower, viable all-OpenAI option |
| `gemini-3.1-flash-lite-preview` | 1.8s | 40 / 69 | 2–5 | Fastest per-call but more corrections needed |

## Operational Guidance

1. Start with defaults for routine extraction runs.
2. Use `.env.ollama.example` as the canonical local profile. It pairs the Qwen3.6 MLX extractor with the Qwen3.6 BF16 reviewer and `gpt-oss:20b` fallback.
3. Use `.env.vllm.example` as the canonical on-prem profile. It pairs Gemma 4 extraction with GPT OSS reviewer/fallback endpoints and keeps `VLLM_API_KEY` separate from OpenAI credentials.
4. Move to `openai:gpt-5.2` directly for reliability testing or provider isolation.
5. `quality` preset is pinned to `anthropic:claude-opus-4-6` intentionally for maximum-quality review/extraction runs; use selectively when latency/cost are acceptable.
6. Re-run focused model comparison after major prompt/schema changes.

## Planned Improvements

1. Move reasoning compatibility rules to one table-driven registry to reduce branching logic.
2. Add an integration smoke matrix for common model/reasoning pairs, including:
   - `google-gla:gemini-3-flash-preview` + `low`
   - `google-gla:gemini-3.1-pro-preview` + `low`
   - `openai:gpt-5.2` + `low` (and `minimal` normalization)
   - `anthropic:claude-opus-4-6` + `low`
   - `ollama:qwen3.6:35b-a3b-mlx-bf16` + `none`
   - `ollama:qwen3.6:35b-a3b-bf16` + `low`
   - `ollama:gemma4:26b-mxfp8` + `none`
   - `ollama:medgemma:27b` + `none`
   - `ollama:gpt-oss:120b` + `medium`
   - `vllm:google/gemma-4-31B-it` + `none`
   - `vllm:openai/gpt-oss-120b` + `medium`
