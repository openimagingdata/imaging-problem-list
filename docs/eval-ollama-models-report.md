# Local Ollama Model Extraction Evaluation

**Date:** 2026-04-20 (supersedes 2026-04-19)
**Hardware:** Mac Studio M3 Ultra, 256 GB unified memory
**Ollama version:** 0.21.0

## Summary

**`qwen3.6:35b-a3b-mlx-bf16` is the new recommended local default** — the Ollama MLX runtime (shipped in v0.19 for the `qwen35moe` architecture) delivers full bf16 precision at **1.68× the throughput of Q8_0** on M3 Ultra. On 256 GB unified memory, Q4 quantizations are the floor, not the default — higher-precision variants win on both speed (better kernel paths) and reliability (fewer tool-call syntax errors). Ollama 0.20.6 fixed Gemma 4 tool-calling; Ollama 0.21.0 added a dedicated MLX runtime for Gemma 4.

**The MLX runtime is the story of this round.** Qwen3.6 uses the `qwen35moe` architecture, which has been MLX-accelerated since Ollama 0.19; we initially overlooked this and defaulted to the GGUF Q8 path. Direct comparison: MLX-bf16 averages **76 s / 37.7 findings** across 3 reports vs Q8_0's **128 s / 35.3 findings**.

## Models Tested (2026-04-19)

Results below are from the IPL extractor pipeline run with `IPL_REVIEWER_ENABLED=false` on three reports from `sample_data/example2/`: `ct_abdomen_20251007.md`, `xr_chest_20220315.md`, `mr_brain_20230125.md`. "Avg chunk fails" is across all three runs.

| Model | Params | Quant | Size | Avg time | Avg findings | Chunk fails | Verdict |
|---|---|---|---:|---:|---:|---:|---|
| **qwen3.6:35b-a3b-mlx-bf16** | 35B (3B active) | MLX bf16 | 70 GB | **76 s** | 37.7 | 0 | **Recommended (default)** — MLX runtime |
| qwen3.6:35b-a3b-q8_0 | 35B (3B active) | Q8_0 | 38 GB | 128 s | 35.3 | 0 | Q8 alternative (GGUF path) |
| **gemma4:26b-mxfp8** | 25.8B (3.8B active) | MXFP8 | 26 GB | 178 s | 38.0 | 0 | **Recommended (quality)** |
| gemma4:26b-mlx-bf16 | 25.8B (3.8B active) | MLX bf16 | 51 GB | 180 s | 37.0 | 0 | Kept for comparison with MXFP8 |
| **medgemma:27b** | 27.4B | Q4_K_M | 17 GB | 184 s | 36.7 | 0 | **Recommended (medical specialist)** |
| qwen3.5:35b-a3b | 35B (3B active) | Q4_K_M | 23 GB | 156 s | 43 | — | Legacy; flaky on 1/3 runs |
| qwen3.6:35b-a3b-bf16 | 35B (3B active) | BF16 | 71 GB | 158 s | 34 | 0 | Generic bf16 GGUF; dominated by MLX-bf16 |
| qwen3.6:35b-a3b-mxfp8 | 35B (3B active) | MXFP8 | 37 GB | 197 s | 38 | 0 | MXFP path slower than Q8 on Qwen |
| qwen3.6:35b-a3b-q4_K_M | 35B (3B active) | Q4_K_M | 23 GB | 148 s | 36 | 0 | Works but dominated by MLX-bf16 |
| gemma4:26b Q4_K_M | 25.8B (3.8B active) | Q4_K_M | 17 GB | 349 s | (failed) | 2 | Q4 unreliable for Gemma 4 tool-calling |
| gemma4:26b-a4b-it-q8_0 | 25.8B (3.8B active) | Q8_0 | 28 GB | 820 s | 41 | 0 | Avoid — Ollama Q8 kernel slow on Apple Silicon |

### gpt-oss (unchanged, still useful)

| Model | Params | Quant | Size | Role |
|---|---|---|---:|---|
| gpt-oss:120b | 120B | MXFP4 | 65 GB | Reliable fallback; default reviewer when staying local |
| gpt-oss:20b | 20B | MXFP4 | 13 GB | Lightweight fallback |

## Key Findings

### Qwen3.6 MLX-bf16 is the new champion
- Avg 76 s across three reports vs 128 s for Q8_0 (GGUF path) — **1.68× speedup**.
- Per-report: CT abdomen 86 s (Q8: 121 s), XR chest 58 s (Q8: 133 s, a 2.27× speedup), MR brain 85 s (Q8: 131 s).
- Slightly more findings at full bf16 precision (37.7 avg vs 35.3 for Q8).
- The MLX runtime was added to Ollama in v0.19 for the `qwen35moe` architecture. Qwen3.6 uses this same architecture — it benefits automatically.
- This supersedes the prior-round verdict that MLX-bf16 was "impractical" (based on a Qwen3.5 test on the pre-0.19 path). On Ollama 0.19+, MLX-bf16 is the fastest path for MoE Qwen on Apple Silicon.

### Qwen3.6 Q8_0 still beats our prior Qwen3.5 champion
- Even without MLX, Q8_0 averages 128 s vs 156 s for `qwen3.5:35b-a3b` Q4_K_M (~18% faster).
- Reliable first-try; Qwen3.5 failed once on `ct_abdomen_20251007` with `UnexpectedModelBehavior` on `impression_1_chunk_2` before succeeding on retry.
- Finding counts are lower than Qwen3.5 (35.3 avg vs 43) but within the "over-extraction vs GT" tolerance documented previously. Qwen3.6 appears more conservative.

### Gemma 4 quantization is counter-intuitive
- **Q4_K_M is unreliable** for Gemma 4 tool-calling — 2/10 chunks failed on the CT abdomen test (`FallbackExceptionGroup`: both primary and fallback blew up on tool-call parse).
- **MXFP8 is the reliable reading** — 0 chunk failures across 3 reports, 26 GB, ~178 s avg.
- **Q8_0 is a trap** — 820 s on CT abdomen (4.5× slower than MXFP8). Ollama's Q8_0 GGUF kernel for Gemma 4 isn't well-optimized on Apple Silicon; MXFP8 goes through a faster path.
- **MLX-BF16 is roughly tied with MXFP8** over 3 reports (180 s vs 178 s avg; 37 vs 38 findings avg). Both being kept in the catalog — 3 reports is too small a sample to tell them apart; the MLX path is fundamentally different (Ollama 0.21's dedicated MLX runtime) and deserves further characterization on more diverse reports before any retirement call.

### Qwen3.6 quantization ladder (CT abdomen timings for reference)
- `mlx-bf16` (70 GB): **86 s** — MLX runtime; fastest path on Apple Silicon for `qwen35moe` architecture.
- `q8_0` (38 GB): 121 s — GGUF path.
- `q4_K_M` (23 GB): 148 s — GGUF lower bound; dominated by MLX-bf16.
- `bf16` (71 GB): 158 s — generic bf16 GGUF path; dominated by MLX-bf16 at ~same footprint.
- `mxfp8` (37 GB): 197 s — MXFP path adds decode overhead on Qwen's GGUF runtime.

### Ollama MLX runtime covers both Qwen MoE and Gemma 4
- **Qwen `qwen35moe` architecture**: MLX runtime added in Ollama 0.19. `qwen3.6:35b-a3b-mlx-bf16` benefits directly; it's ~1.68× faster than Q8_0 on M3 Ultra at full bf16 precision.
- **Gemma 4**: dedicated MLX runtime added in Ollama 0.21. `gemma4:26b-mlx-bf16` matches MXFP8 on speed (180 s vs 178 s avg) and quality.
- The previous "MLX-bf16 is impractical" verdict (2026-04-08) was based on a Qwen3.5 test pre-0.19. It does **not** apply to current Ollama; the MLX-bf16 path is now the **fastest** option for the `qwen35moe` architecture on Apple Silicon.

### Gemma 4 tool-calling now works (Ollama 0.20.6+)
- `ollama show gemma4:26b` lists `tools` and `thinking` in capabilities.
- The extractor's `ollama_needs_native_output()` previously forced Gemma 4 through `NativeOutput`. That routing is now outdated and has been removed; Gemma 4 uses the tool-calling path like Qwen3/gpt-oss.
- `gemma3`, `medgemma` still need `NativeOutput` (no `tools` capability in their manifests).

## Code changes made this round

1. **`src/finding_extractor/llm/model_settings.py`**
   - Added `qwen3.6` to `_ollama_supported_reasoning_for_model` and `build_ollama_settings` (same `reasoning_effort` handling as Qwen3.5 — both think by default on the OpenAI-compat endpoint).
   - Added `gemma4` to the tool-capable prefix list in `ollama_needs_native_output`. `gemma3` and `medgemma` stay on `NativeOutput`.
   - `local` preset now points to `ollama:qwen3.6:35b-a3b-mlx-bf16` (the MLX runtime path); `defaults.py` exports `MODEL_OLLAMA_QWEN36_35B_A3B_MLX_BF16` as the extractor default and `MODEL_OLLAMA_QWEN36_35B_A3B_BF16` as the reviewer default.
2. **`src/finding_extractor/llm/defaults.py`**
   - Added `MODEL_OLLAMA_QWEN36_35B_A3B_{MLX_BF16,BF16,Q8}`, `MODEL_OLLAMA_GEMMA4_26B_MXFP8`, `MODEL_OLLAMA_MEDGEMMA_27B`.
   - `COMMON_MODELS` now distinguishes extractor default (`qwen3.6:35b-a3b-mlx-bf16`) from reviewer default (`qwen3.6:35b-a3b-bf16`).
3. **Custom `gemma4-radextract` Modelfiles retired** (2026-04-20 reviewer round). Tested against plain `gemma4:26b-mxfp8`: the Modelfile's baked-in decoding parameters (`temperature=0.1`, `seed=42`, `top_p=0.9`, `num_ctx=32768`) made extraction 2.2–3.4× slower and caused extraction failures in 2/3 reports. The `ollama/` directory and its Modelfiles were removed.

## Qwen3.5/3.6 thinking-mode handling (unchanged rationale)

Qwen3.5 and Qwen3.6 both emit reasoning tokens by default on Ollama's OpenAI-compatible API (`/v1/chat/completions`). These land in the `reasoning` field, leaving `content` empty — causing infinite tool-calling retries and timeouts. The fix is `reasoning_effort: "none"` (or `low`/`medium`/`high`). Qwen3's `/nothink` token and `extra_body.think` do **not** work here; only `reasoning_effort` is honored.

`build_ollama_settings()` sets `openai_reasoning_effort` for `qwen3.5`, `qwen3.6`, and `nemotron-cascade-2` prefixes.

## MedGemma (official library now, 2026-04-16 release)

`medgemma:27b` in Ollama's official library (pulled from `ollama.com/library/medgemma`) is based on Gemma 3, 27.4B parameters, Q4_K_M, 128K context, text+image. No `tools` capability — uses `NativeOutput` via the extractor's JSON-schema path. The earlier `alibayram/medgemma:27b` and `MedAIBase/MedGemma1.0:27b` community uploads are obsolete and have been purged.

Observed extraction behavior on CT abdomen: 177 s, 38 findings, 0 chunk failures — competitive with Gemma 4 MXFP8 at a smaller footprint (17 GB vs 26 GB). A promising specialist for medical-domain runs.

## Configuration (.env.ollama — unchanged)

```
OLLAMA_BASE_URL=http://localhost:11434/v1
IPL_ALLOW_UNKNOWN_MODEL_REASONING=true
IPL_SUBAGENT_TIMEOUT_SECONDS=300
IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY=1
IPL_REVIEWER_ENABLED=false
IPL_REVIEWER_MODEL=ollama:gpt-oss:120b
IPL_REVIEWER_REASONING=none
IPL_FALLBACK_MODEL=ollama:gpt-oss:20b
```

- **Concurrency 1** still matters: multiple concurrent Ollama requests degrade performance.
- **300 s timeout** is generous enough for all recommended variants; any chunk above 100 s typically indicates a tool-call parse problem, not a speed one.
- **Multi-model runs** (`OLLAMA_MAX_LOADED_MODELS=4`) still required if you enable reviewer + separate extractor model.

## Recommendations

1. **Default:** `ollama:qwen3.6:35b-a3b-mlx-bf16` — fastest (76 s avg), full bf16 precision via Ollama MLX runtime, reliable, 70 GB.
2. **Q8 alternative:** `ollama:qwen3.6:35b-a3b-q8_0` — if disk is constrained (38 GB), still fast via GGUF path (128 s avg).
3. **Quality / deeper extraction:** `ollama:gemma4:26b-mxfp8` — ~8% more findings per report, 26 GB, clean tool-calling via Ollama 0.20.6+ fixes.
4. **Alternate Gemma 4 path (kept for ongoing comparison):** `ollama:gemma4:26b-mlx-bf16` (51 GB) — the Ollama 0.21 MLX runtime path. Roughly tied with MXFP8 on our 3-report sample; retaining both until we have more data to differentiate them.
5. **Medical-domain specialist:** `ollama:medgemma:27b` (17 GB, official library) — same speed tier as Gemma 4, ~26 % more *present* findings across 3 reports, distinctly different extraction style (see "MedGemma: detailed comparison" below). Multimodal (text+image).
6. **Ultralight:** no local small-model recommended this round — `qwen3.5:9b` was retired. Pull `qwen3.6:35b-a3b-mlx-bf16` (70 GB) or the Q8 variant (38 GB); on M3 Ultra the memory headroom makes Q4/tiny options obsolete. For low-memory hardware, pull a sub-10 GB model on demand.
7. **Reviewer / fallback:** `ollama:gpt-oss:120b` / `ollama:gpt-oss:20b` — no reason to change.

**Avoid:**
- Gemma 4 Q4_K_M for tool-calling (chunk failures).
- Gemma 4 Q8_0 (slow GGUF kernel; use MXFP8 or MLX-bf16).
- Qwen3.6 MXFP8 / BF16 / Q4_K_M on this hardware — all dominated by MLX-bf16 or Q8_0.
- NVFP4 variants (Nvidia format; no Apple Silicon benefit).

## MedGemma: detailed comparison

MedGemma was evaluated on the same three reports as the other recommendations. It is a *specialist complement* to the general-purpose extractors, not a drop-in replacement.

### Per-report finding counts (present / absent / total)

| Report | qwen3.6 Q8 | gemma4 MXFP8 | medgemma |
|---|---|---|---|
| CT abdomen | 12 / 22 / 36 | 12 / 24 / 39 | **16** / 22 / 38 |
| XR chest | 20 / 10 / 30 | 21 / 11 / 32 | 20 / 11 / 31 |
| MR brain | 10 / 30 / 40 | 9 / 34 / 43 | **17** / 23 / 41 |
| **Total present** | 42 | 42 | **53** |

MedGemma extracts ~26 % more *present* findings across the 3 reports. On the MR brain case, it finds nearly 2× as many.

### Finding-name overlap (Jaccard, normalized names)

| Report | qwen3.6 ∩ gemma4 | qwen3.6 ∩ medgemma | gemma4 ∩ medgemma |
|---|---:|---:|---:|
| CT abdomen | 0.48 | 0.38 | 0.37 |
| XR chest | 0.54 | 0.50 | 0.41 |
| MR brain | 0.36 | 0.29 | 0.25 |

qwen3.6 and gemma4 agree with each other substantially more than either agrees with medgemma. **MedGemma extracts *different* findings, not just more or fewer** — it follows a medical-domain systematic checklist.

### What MedGemma uniquely catches on MR brain

Findings only MedGemma extracted (examples):
- `white matter hyperintensities` (specific anatomy: *right frontal subcortical white matter*)
- `gray-white matter differentiation`, `corpus callosum morphology`, `brainstem appearance`, `cerebellum appearance`, `cerebellar tonsil position`
- `basal cistern`, `pituitary gland size`, `intracranial artery abnormality`, `ventricular size`

These are standard neuroradiology checkpoints — the systematic mental checklist a radiologist applies to every brain MRI. The general-purpose models miss them because the report describes them as normal, not as abnormal findings; MedGemma's medical training surfaces the implicit observations.

### Tradeoffs

- MedGemma populates `location.specific_anatomy` in only ~45 % of findings (vs ~97 %+ for the generalists). Many medgemma finding names already encode the anatomy (e.g., "corpus callosum morphology"), so structured duplication is lower. Downstream code-mapping pipelines may need different heuristics.
- MedGemma captures slightly more structured `attributes` (severity/size/laterality): 31 vs 23–26 across reports.
- No `tools` capability in the model manifest → uses `NativeOutput` (JSON schema mode). Cleanly reliable in this pipeline.

### Strong combination

Running both qwen3.6 (or gemma4) and medgemma on the same report and merging is worth exploring: medgemma fills the implicit-findings gap; the generalists anchor the structured fields medgemma leaves sparse.

## Reviewer evaluation (2026-04-20)

Seven local reviewers were paired with the `qwen3.6:35b-a3b-mlx-bf16` extractor on three reports from `sample_data/example2/` with `IPL_REVIEWER_REASONING=low`. For each reviewer's flag, we manually graded TP/FP against the chunk text and the extraction table the reviewer saw. We also identified "dogs that didn't bark" — real issues multiple reviewers missed.

### Ranking

| Reviewer | MR flags | TPs | FPs | Unique catches | Avg time/report | Verdict |
|---|---:|---:|---:|---|---:|---|
| **qwen3.6:35b-a3b-bf16** | 2 | 2 | 0 | evidence-boundary + comprehensive-negative decomposition | 692 s | **Recommended reviewer** — best TP/FP ratio |
| gpt-oss:120b | 3 | 3 | 0 | none | 175 s | Fast but missed ≥4 real issues on MR |
| gemma4:26b-mlx-bf16 | 2 | 1–2 | 1 | evidence boundary | 479 s | Sophisticated, faster alternative |
| nemotron-3-super:120b | 6 | 2 | 1 | disease-name-for-blanket-normal pattern | 707 s | Aggressive, pedantic; needed reasoning-handler fix |
| nemotron-cascade-2 | ~5–6 | 2 | ~4 | paranasal sinusitis hallucination | 570 s | Cross-chunk boundary confusion — unreliable |
| gemma4:26b-mxfp8 | 1 | 0–1 | 0–1 | none | 308 s | Too conservative |
| medgemma:27b | 0 | 0 | 0 | none | 222 s | Rubber-stamps every chunk — do not use as reviewer |
| gpt-oss:20b | earlier | 0 | many | none | 170 s | **Fabricates finding names that aren't in the extraction table** — dangerous |

### Key findings

1. **gpt-oss:120b (our previous default reviewer) under-flags.** On MR brain it silently approved ≥4 real issues that other reviewers correctly caught: the "paranasal sinuses well aerated" blanket negative (chunks 6), the evidence-boundary violation on orbital mass extracted from FOLLOWING_CHUNK_CONTEXT (chunk 7), the over-specific "orbital mass absent" for blanket "orbits normal" (chunk 7), and the "paranasal sinusitis" hallucination in impression_2.

2. **qwen3.6:35b-a3b-bf16 catches sophisticated issues others miss.** On MR brain it uniquely identified that "No acute intracranial abnormality, mass, or hemorrhage" is a comprehensive negative that decomposes into three distinct absent findings — the extractor only captured two. It also caught the evidence-boundary violation (one of two reviewers to do so). Zero FPs across 18 graded chunks.

3. **Cross-family pairing works**: gemma4:26b-mxfp8 extractor + qwen3.6:35b-a3b-bf16 reviewer on MR brain produced 48 findings and 0 reviewer flags (vs qwen3.6 MLX-bf16 extractor which triggered 2 flags on the same report). Different-family pairing doesn't hide issues; it avoids same-family blind spots.

4. **`reasoning_effort=low` is required** for nemotron-3-super:120b. Without it, the model thinks by default (50+ reasoning tokens for a 3-token answer), per-call latency spikes 3–5×, and subagent calls hit the 300 s timeout. Fix: extend `build_ollama_settings()` to route `nemotron-3-super` through the same reasoning_effort path as `qwen3.5/3.6` and `nemotron-cascade-2`.

5. **`medgemma:27b` is a bad reviewer**. It flagged 0/10 MR chunks, including chunks where multiple other reviewers correctly identified real issues. It produces plausible-sounding "the extraction accurately represents..." rationales but does not engage critically. Good as a specialist extractor; useless as a reviewer.

6. **`gpt-oss:20b` must not be used as a reviewer**. Three of its four MR flags cited finding names that literally did not appear in the extraction table it was shown — it fabricates its own input.

7. **`.env.ollama` updated**: `IPL_REVIEWER_MODEL=ollama:qwen3.6:35b-a3b-bf16`, `IPL_REVIEWER_REASONING=low`. Previous default (`gpt-oss:120b` / `none`) was both the wrong model and the wrong reasoning level.

### Code change (reviewer round)

- `src/finding_extractor/llm/model_settings.py`: added `nemotron-3-super` to `_ollama_supported_reasoning_for_model` and `build_ollama_settings` reasoning_effort handlers. Without this, the reviewer role for `nemotron-3-super:120b` silently thinks and times out.
- `src/finding_extractor/llm/defaults.py`: added `MODEL_OLLAMA_QWEN36_35B_A3B_BF16`; `COMMON_MODELS` now explicitly distinguishes the extractor default (MLX-bf16) from the reviewer default (bf16 GGUF).

## Logfire

All runs are traced at: https://logfire-us.pydantic.dev/talkasab/imaging-problem-list

Caveat from this round: Logfire retention of trace data is short (hours). For extended evaluations, query Logfire promptly as each run completes; otherwise `agent run` span attributes (rationales, problems, thinking traces) age out before analysis.

---

# 2026-05-14 round — Ollama 0.23.1→0.24.0 catch-up and new local default

**Date:** 2026-05-14
**Hardware:** Mac Studio M3 Ultra, 256 GB unified memory
**Ollama version at bench time:** 0.23.1–0.23.3 (matrix); 0.24.0 confirmation smoke
**Plan reference:** `~/.claude/plans/please-come-up-with-fuzzy-nygaard.md`

## Summary

**`gemma4:26b-nvfp4` is the new recommended local default extractor**, displacing `qwen3.6:35b-a3b-mlx-bf16`. It wins every report on speed (67s avg vs qwen3.6's 109s on 6 reports), produces ~30% more *present* findings (130 vs 100 total), and uses one-quarter the disk (17 GB vs 70 GB).

The win required two changes that overturn the 2026-04-20 routing decisions:
1. **Gemma 4 is now routed through `NativeOutput`**, not tool-calling. Ollama 0.22.1's "Gemma 4 renderer refined for thinking + tool-calling" release note hid a regression: with `reasoning_effort=none` and tool-calling, Gemma 4 26B produces malformed tool calls ~50% of the time. JSON-schema output sidesteps the tool-call parser entirely.
2. **`gpt-oss:20b` retired as fallback model.** It was triggering `FallbackExceptionGroup` because both primary and fallback chunks failed; the 2026-04-20 reviewer eval already flagged it as fabricating finding names. Replaced with `ollama:qwen3.6:35b-a3b-mlx-bf16` as a known-good local fallback.

Disk net change this round: started 461 GB across 10 models; ended at ~278 GB across 7 models (about 183 GB recovered).

## Models retired this round (disk + code)

| Model | Size | Reason |
|---|---|---|
| `nemotron-cascade-2:latest` | 24 GB | 2026-04-20 verdict: cross-chunk boundary confusion |
| `nemotron-3-super:120b` | 86 GB | 2026-04-20 verdict: aggressive, pedantic, 707s avg |
| `qwen3.6:35b-a3b-q8_0` | 38 GB | Dominated by MLX-bf16 on Apple Silicon |
| `gemma4:31b-mlx-bf16` | 62 GB | Dense 31B on Apple Silicon: hardware-bound 4.2× slower than 26B MoE at batch=1; not salvageable per Incept5 MLX benchmark and Google's MTP guidance (gains require batch≥4) |
| `gemma4:26b-mlx-bf16` | 51 GB | Identical findings to mxfp8/nvfp4 on 2026-04-20 + this round, no speed advantage |
| `granite4.1:30b` | 17 GB | 2/6 chunk failures on 2026-05-14 matrix; 3–5× slower than gemma4-nvfp4 when it works |
| `nemotron-3-nano:30b-a3b-q8_0` | 33 GB | Slowest of 4 candidates (382s avg); needed NativeOutput + reasoning=low; no quality advantage |

## Models added and kept (disk)

| Tag | Size | Role |
|---|---|---|
| `gemma4:26b-nvfp4` | 17 GB | **New default extractor** (NativeOutput, reasoning=none) |

## Routing fixes this round (`src/finding_extractor/llm/model_settings.py`)

1. **Gemma 4 → `NativeOutput`.** Tool-calling worked on Ollama 0.21 (2026-04-20: 178s avg, 0 failures). On Ollama 0.22.1+ with `reasoning_effort=none`, the 26B variants flake intermittently (~50% chunk-failure rate with malformed tool calls). With thinking left on, latency jumps to ~500s/report. JSON-schema output bypasses the broken tool-call parsing and lets us suppress thinking cleanly. Result: 67s avg / 6-of-6 clean on this round's bench.
2. **`reasoning_effort=none` honored for Gemma 4** via `build_ollama_settings`, alongside qwen3.5/3.6 and nemotron-3-super.
3. **`nemotron-cascade-2`, `nemotron-3-nano`, `granite4.1` routing branches removed** (models retired this round; their routing logic deleted along with them).
4. **`extractor_max_subagent_concurrency` local-only auto-default raised from 1 → 2** in `core/config.py` (see Track C).

## Extractor matrix — 6 reports × 4 candidates, `reviewer_enabled=false`, concurrency=2

Reports: `ct_abdomen_20251007`, `xr_chest_20220315`, `mr_brain_20230125`, `ct_chest_20220922`, `us_abdomen_20220208`, `xr_shoulder_20210522` (all in `sample_data/example2/`).

| Model | Routing | Reasoning | 6-report avg | Reports clean | Findings avg | Present avg |
|---|---|---|---|---|---|---|
| **`gemma4:26b-nvfp4`** | **NativeOutput** | **none** | **67s** | **6/6** | **35.5** | **21.7** |
| `qwen3.6:35b-a3b-mlx-bf16` (prior default) | tools | none | 109s | 6/6 | 33.2 | 16.7 |
| `granite4.1:30b` | NativeOutput | none | 289s | 4/6 | 39 (when works) | 19.3 |
| `nemotron-3-nano:30b-a3b-q8_0` | NativeOutput | low | 382s | 6/6 | 31.2 | 17.0 |

Per-report wall time:

| Report | qwen3.6 | gemma4 nvfp4 | granite4.1 | nemotron-nano |
|---|---:|---:|---:|---:|
| ct_abdomen | 209s | **76s** | 329s | 438s |
| xr_chest | 75s | **59s** | 173s | 357s |
| mr_brain | 99s | **72s** | 291s ✗ | 378s |
| ct_chest | 117s | **104s** | 419s | 565s |
| us_abdomen | 80s | **60s** | 260s ✗ | 332s |
| xr_shoulder | 72s | **34s** | 262s | 223s |

Note: qwen3.6's `ct_abdomen` 209s is partly cold-load on the first model swap of the matrix; warm-load runs averaged ~89s. The conclusion (gemma4-nvfp4 wins on speed) holds either way.

## Quality comparison: gemma4 vs qwen3.6 — complementary, not redundant

Same 3 baseline reports (ct_abdomen, xr_chest, mr_brain). Finding-name Jaccard overlap is **0.22–0.50** between gemma4-nvfp4 and qwen3.6 — they extract genuinely different findings.

Pattern (MR brain, illustrative): gemma4-nvfp4 found 22 *present* findings vs qwen3.6's 11. The 28 names unique to gemma4 are anatomical-systematic ("gray-white matter differentiation", "cerebellar tonsil position", "ventricular prominence", "skull fracture") — the radiologist's mental checklist applied to every brain MRI. The 25 names unique to qwen3.6 are pathology-vocabulary ("ischemic change", "leukoaraiosis", "intracranial arterial stenosis/occlusion") — findings as named in the report text.

This is the same pattern the 2026-04-20 eval found between qwen3.6 and MedGemma. **Gemma 4 26B is essentially playing MedGemma's role at qwen3.6 speed.**

Implication: a combined-extractor pipeline (gemma4 + qwen3.6 → merge) may capture both vocabularies. Out of scope for this round, but worth noting.

## NVFP4 vs MXFP8

Both `gemma4:26b-nvfp4` (16 GB, 6.3B active params per manifest) and `gemma4:26b-mxfp8` (26 GB, 8.7B active) ran clean on the same 3 baseline reports with NativeOutput + reasoning=none:

| Variant | ct_abdomen | xr_chest | mr_brain | Avg | Findings (3-report total) |
|---|---:|---:|---:|---:|---:|
| `gemma4:26b-nvfp4` | 71s | 81s | 84s | 79s | 115 |
| `gemma4:26b-mxfp8` | 89s | 54s | 87s | 77s | 112 |

Effectively tied. NVFP4 wins on disk (9 GB smaller). Recommended as primary; mxfp8 kept as alternative for comparison.

## Track C — concurrency sweep on `qwen3.6:35b-a3b-mlx-bf16`

Tested `IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY` at 1, 2, 4 across the 6-report corpus.

| Concurrency | 6-report total | Clean | Notes |
|---|---:|---:|---|
| 1 | 2161s (includes 1794s cold-load outlier on ct_abdomen) | 5/6 | First-model-load cascade timed out one report |
| **2** | **608s** | **6/6** | Safe ceiling; modest 10–25% per-report speedup |
| 4 | 642s | 5/6 | Chunk failure on mr_brain; ct_abdomen 3.6× slower than c=2 |

**Verdict:** c=2 is the safe lift. The expected 2× win from concurrency didn't materialize — Ollama still serializes most of the work internally on Apple Silicon at batch=1 — but c=2 is a clean modest improvement. Bumped local-only auto-default from 1 → 2 in `core/config.py`; `.env.ollama` updated to match.

## Configuration changes (`.env.ollama`)

```
IPL_MODEL=ollama:gemma4:26b-nvfp4         # was: ollama:qwen3.6:35b-a3b-mlx-bf16
IPL_REASONING=none                        # unchanged
IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY=2  # was: 1
IPL_FALLBACK_MODEL=ollama:qwen3.6:35b-a3b-mlx-bf16  # was: ollama:gpt-oss:20b
IPL_REVIEWER_MODEL=ollama:qwen3.6:35b-a3b-bf16      # unchanged
IPL_REVIEWER_REASONING=low                # unchanged
IPL_REVIEWER_ENABLED=true                 # unchanged
```

## Updated recommendations (supersede 2026-04-20)

1. **Default extractor:** `ollama:gemma4:26b-nvfp4` — fastest, smallest, most present findings, NativeOutput path, reasoning=none.
2. **Alternative extractor:** `ollama:gemma4:26b-mxfp8` — equivalent quality at ~equivalent speed, larger disk footprint. Useful for A/B compares.
3. **Tool-calling alternative extractor:** `ollama:qwen3.6:35b-a3b-mlx-bf16` — slower (109s avg) but exercises a different code path; useful for cross-family validation. Captures different vocabulary (pathology-named vs anatomical-systematic).
4. **Reviewer:** `ollama:qwen3.6:35b-a3b-bf16`, reasoning=low — unchanged.
5. **Local fallback:** `ollama:qwen3.6:35b-a3b-mlx-bf16` (was `gpt-oss:20b`). Pointing the fallback at the same family as our extractor alternative avoids the gpt-oss:20b fabrication risk.
6. **Medical specialist:** `ollama:medgemma:27b` — unchanged. Note: gemma4-nvfp4 now overlaps with MedGemma's systematic-anatomy style at much higher speed; MedGemma stays available for explicitly medical-domain runs.
7. **Heavy reasoning:** `ollama:gpt-oss:120b` — unchanged.

## Ollama 0.24.0 note

Ollama 0.24.0 (released 2026-05-14) reworked the MLX sampler "for improved generation quality on Apple Silicon." This directly affects our new default's runtime path. The matrix bench above was on 0.23.1–0.23.3. Confirmation smoke on 0.24.0 with `gemma4:26b-nvfp4` + xr_chest: **65s, 30 findings, 19 present** (vs 59s / 29 / 18 on 0.23.x — within run-to-run variance; one more finding total and one more present). Recommendation (gemma4-nvfp4 as default) holds on 0.24.0; no code or config change needed.

## Logfire

All runs are traced at: https://logfire-us.pydantic.dev/talkasab/imaging-problem-list — capture span attributes promptly; retention is short.
