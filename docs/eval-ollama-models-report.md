# Local Ollama Model Extraction Evaluation

**Date:** 2026-04-03 (updated 2026-04-08)
**Hardware:** Mac Studio M3 Ultra, 192GB unified memory
**Ollama version:** 0.20.0 (updated 0.20.3)

## Summary

We evaluated local Ollama models for radiology report finding extraction using the IPL extractor pipeline. **Qwen3.5 models (Q4_K_M quantization) are now the recommended local models**, outperforming gpt-oss in both extraction quality and memory efficiency after fixing a critical thinking-mode compatibility issue.

## Models Tested

| Model | Params | Quant | Tool Support | Extraction Quality | Speed | Verdict |
|---|---|---|---|---|---|---|
| **qwen3.5:35b-a3b** | **35B (3B active)** | **Q4_K_M** | **yes** | **Excellent** | **~12s/chunk** | **Recommended** |
| **qwen3.5:9b** | **9B** | **Q4_K_M** | **yes** | **Excellent** | **~11s/chunk** | **Recommended (lightweight)** |
| **qwen3.5:27b** | **27B** | **Q4_K_M** | **yes** | **Excellent** | **~28s/chunk** | **Recommended (quality)** |
| gpt-oss:120b | 120B | MXFP4 | yes | Excellent | ~16s/chunk | Good, but 86GB footprint |
| gpt-oss:20b | 20B | MXFP4 | yes | Very good | ~14.5s/chunk | Good lightweight option |
| nemotron-3-super:120b | 120B (12B active) | Q4_K_M | yes | Excellent | ~35 tok/s | Viable but slower |
| qwen3.5:27b-mlx-bf16 | 27B | MLX bf16 | yes | Good | ~82s/chunk | Too slow for practical use |
| qwen3.5:35b-a3b-mlx-bf16 | 35B (3B active) | MLX bf16 | yes | Not tested | >240s/chunk | Impractical |
| qwen3.5:9b-mlx-bf16 | 9B | MLX bf16 | yes | Fair | ~20s/chunk | 40% chunk timeout rate |
| gemma4:31b | 31B | Q4_K_M | yes | Good | ~23 tok/s | Slow on this hardware |
| llama3.3 | 70B | Q4_K_M | yes | Good | ~17 tok/s | Slow on this hardware |
| deepseek-r1:70b/32b | 70B/32B | Q4_K_M | **no** | Not tested | N/A | No tool support in Ollama |
| gemma3:27b | 27B | Q4_K_M | **no** | Not tested | N/A | No tool support in Ollama |
| MedGemma variants | 27B | various | **no** | Not tested | N/A | No tool support; NativeOutput works |

## Speed Comparison

### Qwen3.5 Q4_K_M vs gpt-oss MXFP4 (CT Abdomen, 10 chunks)

| Model | Quant | Size | Avg chunk | Total | Findings |
|---|---|---|---|---|---|
| qwen3.5:35b-a3b | Q4_K_M | 23GB | ~12s | ~2.5 min | 41 |
| qwen3.5:9b | Q4_K_M | 6GB | ~11s | ~2.5 min | 42 |
| gpt-oss:120b | MXFP4 | 86GB | ~16s | ~2.6 min | 38 |
| qwen3.5:27b | Q4_K_M | 17GB | ~28s | ~5.1 min | 45 |
| gpt-oss:20b | MXFP4 | 86GB | ~14.5s | ~2.2 min | 34 |

The Qwen3.5 MoE (35b-a3b) and 9b models match or beat gpt-oss:120b on speed while using a fraction of the memory. The 27b dense model is slower but extracts the most findings.

### MLX-bf16 Variants (Not Recommended)

MLX-bf16 models run at full 16-bit precision but are bottlenecked by memory bandwidth:

| Model | Size | Avg chunk | Reliability |
|---|---|---|---|
| qwen3.5:27b-mlx-bf16 | 54GB | ~82s | 100% (very slow) |
| qwen3.5:9b-mlx-bf16 | 18GB | ~20s | ~60% (frequent hangs) |
| qwen3.5:35b-a3b-mlx-bf16 | 70GB | >240s | Impractical |

### gpt-oss Per-Report Timing (Full Pipeline, from 2026-04-03)

Reports tested from `sample_data/example2/`:

| Report | Modality | gpt-oss:120b | gpt-oss:20b |
|---|---|---|---|
| XR Shoulder | XR | 1.5 min | 1.1 min |
| XR Chest | XR | 2.3 min | 2.2 min |
| US Abdomen | US | 2.2 min | 2.0 min |
| CT Abdomen | CT | 2.6 min | 2.2 min |
| MR Brain | MR | 2.8 min | 2.4 min |
| **Average** | | **2.3 min** | **2.0 min** |

Average chunk time: gpt-oss:120b ~16s/chunk, gpt-oss:20b ~14.5s/chunk.

## Extraction Quality

### Reliability

All three Qwen3.5 Q4_K_M models achieved **10/10 successful chunks** on CT abdomen with the `reasoning_effort` fix. The 9b model needed more retries (5 across the run) but completed everything. Both gpt-oss models also achieved 10/10 across 5 reports.

Historical issues (resolved):
- qwen3.5 models initially appeared broken — **all hangs were caused by Qwen3.5's default thinking mode**, not model quality (see "Qwen3.5 Thinking Mode Fix" below)
- qwen3.5:27b-mlx-bf16: too slow at bf16 precision (~82s/chunk)
- Earlier runs (before prompt fixes): gpt-oss:120b failed 3/5 reports due to schema confusion from mismatched few-shot examples

### Quality Comparison: gpt-oss:120b vs gpt-oss:20b

Both models find the same clinically significant findings. Differences are minor:

**XR Shoulder** (GT: 9 findings)
- 120b: 19 findings (11 present, 6 absent, 2 possible) -- all GT present findings covered
- 20b: 16 findings (8 present, 5 absent, 3 possible) -- all GT present findings covered
- Both correctly identify: calcific tendonitis, high-riding humeral head, AC joint degenerative changes, absent fractures/dislocations

**XR Chest** (GT: 20 findings, 12 present)
- 120b: 32 findings (22 present) -- finds all GT present findings including pneumonia, DISH, fractures, calcifications, osteopenia
- 20b: 27 findings (18 present) -- same key findings, slightly less granular
- Both correctly identify the acute T9 compression fracture, healed rib fractures, healed clavicle fracture

**US Abdomen** (GT: 21 findings, 6 present)
- 120b: 30 findings (11 present) -- hepatic steatosis, gallstones, bilateral renal calculi, parapelvic cyst, aortic calcification
- 20b: 28 findings (12 present) -- same findings; 20b extracts slightly more detail (echogenicity, IVC patency)

**CT Abdomen** (GT: 31 findings, 7 present + 1 indeterminate)
- 120b: 38 findings (13 present, 1 possible) -- all GT present findings plus DISH as possible
- 20b: 34 findings (11 present, 1 possible) -- same key findings, slightly fewer sub-findings
- Both correctly extract bilateral renal calculi with sizes, hepatic steatosis, calcifications, spine degeneration

**MR Brain** (GT: 22 findings, 5 present)
- 120b: 46 findings (12 present) -- cerebral atrophy, white matter disease, sinus disease
- 20b: 41 findings (10 present) -- same key findings
- Both extract the specific 5mm right frontal subcortical white matter lesion

### Quality Assessment

Both models produce clinically reasonable extractions. Key observations:

1. **All clinically significant findings are captured** by both models across all reports
2. **Both over-extract vs ground truth** — this is expected because the GT uses standardized OIFM codes while models produce more granular findings. The merge/coding pipeline handles consolidation.
3. **120b extracts slightly more** (10-15% more findings) — mostly additional granularity, not additional clinical information
4. **Presence/absence classification is accurate** — both correctly identify absent findings from normal statements
5. **DISH correctly marked as "possible"** — both models handle hedged language appropriately
6. **Attribute extraction is good** — sizes, laterality, severity, change_from_prior all captured

## Configuration

### .env.ollama

```
OLLAMA_BASE_URL=http://localhost:11434/v1
IPL_ALLOW_UNKNOWN_MODEL_REASONING=true
IPL_SUBAGENT_TIMEOUT_SECONDS=300
IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY=1
IPL_REVIEWER_ENABLED=false
```

### Key findings about pipeline configuration

- **Multi-model runs** require `OLLAMA_MAX_LOADED_MODELS=4` to keep extraction + reviewer models loaded simultaneously
- **Concurrency must be 1** — multiple concurrent Ollama requests degrade performance
- **Timeout needs to be generous** (300s) for non-MXFP4 models; gpt-oss models rarely need more than 45s per chunk
- **Fallback model** should be another Ollama model to avoid accidental cloud API calls
- See `config.toml.example` for recommended local settings

## NativeOutput for Models Without Tool Support

Several Ollama model families (gemma4 MoE, gemma3, deepseek-r1, MedGemma) can't use PydanticAI's tool-calling protocol. The extractor now **automatically detects** these and uses `NativeOutput` (JSON schema mode) instead. This is handled by `ollama_needs_native_output()` in `model_settings.py` and `resolve_output_type()` in `resilience.py`, applied across both extraction and coding agents.

When primary and fallback models have different output mode requirements, the system biases to native output (which works for all models).

## Qwen3.5 Thinking Mode Fix (2026-04-08)

Qwen3.5 models think by default — unlike Qwen3 (which had separate `-instruct` and `-thinking` tags), Qwen3.5 always emits reasoning tokens before responding. On Ollama's OpenAI-compatible API (`/v1/chat/completions`), these tokens go into the `reasoning` field, leaving `content` empty. This causes:

- Tool-calling responses with empty content → infinite retries → timeouts
- The model appears "stuck" but is actually generating reasoning tokens that PydanticAI can't see

**Fix:** Send `reasoning_effort: "none"` via the OpenAI-compatible API. This is implemented in `build_ollama_settings()` in `model_settings.py`, which sets `openai_reasoning_effort` for all Qwen3.5 models. Higher reasoning levels (`low`, `medium`, `high`) are also supported.

Key details:
- The native Ollama API (`/api/chat`) uses `"think": false` — but PydanticAI uses the OpenAI-compatible endpoint
- The OpenAI-compatible endpoint ignores `"think"` and `extra_body.think` — only `reasoning_effort` works
- Qwen3's `/nothink` token does not work with Qwen3.5
- `_ollama_supported_reasoning_for_model()` now recognizes `qwen3.5` as supporting `none/low/medium/high`

## Recommendations

1. **Use qwen3.5:35b-a3b (Q4_K_M) as the default local extraction model** — fastest, excellent quality, only 23GB memory
2. **Use qwen3.5:9b (Q4_K_M) as the ultralight option** — 6GB footprint, competitive speed/quality, more retries needed
3. **Use qwen3.5:27b (Q4_K_M) for maximum extraction thoroughness** — extracts the most findings, 2x slower
4. **gpt-oss:120b remains a solid option** if already downloaded — reliable, well-tested
5. **Avoid MLX-bf16 variants** — memory bandwidth bottleneck makes them 3-15x slower than Q4_K_M
6. **NativeOutput auto-detection is implemented** — models without tool support (gemma4 MoE, gemma3, deepseek-r1, MedGemma) are automatically detected and use JSON schema mode
7. **Custom Modelfiles** in `ollama/` provide extraction-optimized defaults for gemma4 variants

## Logfire

All runs are traced at: https://logfire-us.pydantic.dev/talkasab/imaging-problem-list
