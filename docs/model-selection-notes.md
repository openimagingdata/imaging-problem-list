# Model Selection Notes

Last updated: 2026-03-16
Status: Active reference

## Current Defaults

1. Extraction model default: `google-gla:gemini-3-flash-preview`
2. Extraction fallback default: `openai:gpt-5.2`
3. Reviewer model: inherits fallback (`openai:gpt-5.2`), reasoning=`low`
4. Provider default reasoning:
   - `google`: `low`
   - `openai`: `medium`
   - `anthropic`: `medium`
   - `openrouter`: `medium`
   - `ollama`: `none`

## What We Learned (Chunk-Extraction Focus)

1. Prompt size and schema fit matter more than forcing higher reasoning.
2. Gemini Flash is the best default throughput baseline for chunk extraction.
3. GPT-5.2 is a strong fallback for resilience when primary provider calls fail.
4. Repeated Sonnet diagnostics showed 4.6 faster than 4.5 for this chunk task, but still slower than Flash/GPT defaults.
5. Gemini model-family reasoning settings must be model-aware:
   - `gemini-3.1-pro*`: supports `low|high`
   - `gemini-3-flash*`: supports `minimal|low|medium|high`

## Curated Common Models

Canonical source in code:
- `src/finding_extractor/llm/defaults.py`
- `src/finding_extractor/llm/model_settings.py` (`EXTRACTION_PRESETS`, `format_preset_help_summary()`)

1. `google-gla:gemini-3-flash-preview` (default extraction)
2. `openai:gpt-5.2` (default fallback)
3. `anthropic:claude-opus-4-6` (high-quality validator/extraction option)
4. `google-gla:gemini-3.1-pro-preview` (strong Google quality option)
5. `ollama:qwen3:30b-instruct` (local baseline, reasoning=`none`)
6. `ollama:qwen3:30b-thinking` (local thinking-capable model)
7. `ollama:gpt-oss:120b` (local heavy reasoning-capable model)

Reasoning notes for curated local models:
- `ollama:qwen3:30b-thinking`: all reasoning inputs accepted; runtime maps `none` to `think=false` and non-`none` to `think=true`
- `ollama:qwen3:30b-instruct`: `none` only
- `ollama:gpt-oss:120b`: `none|low|medium|high` accepted; `minimal` normalizes to `low`

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

### Best combinations by total runtime

| Extractor | Reviewer | Total | Findings | Re-extractions |
|-----------|----------|------:|---------:|---:|
| flash-lite | flash | 10.5s | 42 | 0 (reviewer misses real issues) |
| flash | flash-lite | 13.3s | 43 | 3 (reviewer over-triggers) |
| **flash** | **gpt-5.2** | **19.4s** | **44** | **1** (current default, best quality) |
| gpt-5.2 | flash | 20.8s | 44 | 0 (slow extractor, permissive reviewer) |

## Operational Guidance

1. Start with defaults for routine extraction runs.
2. Move to `openai:gpt-5.2` directly for reliability testing or provider isolation.
3. `quality` preset is pinned to `anthropic:claude-opus-4-6` intentionally for maximum-quality review/extraction runs; use selectively when latency/cost are acceptable.
4. Re-run focused model comparison after major prompt/schema changes.

## Planned Improvements

1. Move reasoning compatibility rules to one table-driven registry to reduce branching logic.
2. Add an integration smoke matrix for common model/reasoning pairs, including:
   - `google-gla:gemini-3-flash-preview` + `low`
   - `google-gla:gemini-3.1-pro-preview` + `low`
   - `openai:gpt-5.2` + `low` (and `minimal` normalization)
   - `anthropic:claude-opus-4-6` + `low`
   - `ollama:qwen3:30b-instruct` + `none`
   - `ollama:qwen3:30b-thinking` + `low`
   - `ollama:gpt-oss:120b` + `medium`
