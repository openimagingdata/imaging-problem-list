# Local Ollama Model Extraction Evaluation

**Date:** 2026-04-03
**Hardware:** Mac Studio M3 Ultra, 192GB unified memory
**Ollama version:** 0.20.0

## Summary

We evaluated local Ollama models for radiology report finding extraction using the IPL extractor pipeline. **gpt-oss:120b (MXFP4) and gpt-oss:20b (MXFP4) are the recommended local models.** Both produce high-quality extractions at high speed with 100% reliability across all test reports.

## Models Tested

| Model | Params | Quant | Tool Support | Extraction Quality | Speed | Verdict |
|---|---|---|---|---|---|---|
| gpt-oss:120b | 120B | MXFP4 | yes | Excellent | ~72 tok/s | **Recommended** |
| gpt-oss:20b | 20B | MXFP4 | yes | Very good | ~65 tok/s | **Recommended (lightweight)** |
| nemotron-3-super:120b | 120B (12B active) | Q4_K_M | yes | Excellent | ~35 tok/s | Viable but slower |
| qwen3.5:27b-mlx-bf16 | 27B | MLX bf16 | yes | Good | ~12 tok/s | Too slow, timeouts |
| qwen3.5:35b-a3b | 35B (3B active) | Q4_K_M | yes | Good | ~40 tok/s | Viable MoE option |
| gemma4:31b | 31B | Q4_K_M | yes | Good | ~23 tok/s | Slow on this hardware |
| llama3.3 | 70B | Q4_K_M | yes | Good | ~17 tok/s | Slow on this hardware |
| deepseek-r1:70b/32b | 70B/32B | Q4_K_M | **no** | Not tested | N/A | No tool support in Ollama |
| gemma3:27b | 27B | Q4_K_M | **no** | Not tested | N/A | No tool support in Ollama |
| MedGemma variants | 27B | various | **no** | Not tested | N/A | No tool support; NativeOutput works |

## Speed: MXFP4 Dominates on Apple Silicon

The MXFP4 quantization format used by gpt-oss models runs dramatically faster than Q4_K_M on Apple Silicon M3 Ultra. This is the single biggest factor in model selection for local use.

**Ollama raw eval rates (tok/s):**
- gpt-oss:120b (MXFP4): 72 tok/s
- gpt-oss:20b (MXFP4): ~65 tok/s (estimated)
- nemotron-3-super:120b (Q4_K_M): 35 tok/s
- gemma4:31b (Q4_K_M): 23 tok/s
- qwen3.5:27b (Q4_K_M): 19 tok/s
- llama3.3 (Q4_K_M): 17 tok/s

## Per-Report Timing (Full Pipeline)

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

Both gpt-oss models achieved **10/10 successful extractions** (5 reports x 2 models). No timeouts, no schema failures, no retries needed for schema compliance.

Other models had issues:
- qwen3.5:27b-mlx-bf16: timed out on CT abdomen chunk (>300s)
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

## Recommendations

1. **Use gpt-oss:120b as the default local extraction model** — best quality, fast, reliable
2. **Use gpt-oss:20b as the lightweight/reviewer option** — nearly identical quality, slightly faster
3. **NativeOutput auto-detection is implemented** — models without tool support (gemma4 MoE, gemma3, deepseek-r1, MedGemma) are automatically detected and use JSON schema mode
4. **Custom Modelfiles** in `ollama/` provide extraction-optimized defaults for gemma4 variants
5. **Monitor MXFP4 availability** — as more models ship MXFP4 quantizations, they become viable local options

## Logfire

All runs are traced at: https://logfire-us.pydantic.dev/talkasab/imaging-problem-list
