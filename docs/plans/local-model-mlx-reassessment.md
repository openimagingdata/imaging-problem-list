# Local Model Reassessment: MLX Runtime + New Model Generations

Created: 2026-07-01
Status: Planned (not started)

## Why

The 2026-05-14 eval round made `ollama:gemma4:26b-nvfp4` the local default extractor (code, presets, and tests all reflect this), but the local-model landscape has moved again and we decided to reassess wholesale rather than patch documentation piecemeal:

- Ollama has released past 0.24.0; MLX runtime capabilities (sampler, threading, quantization formats) keep shifting the speed/quality tradeoffs on Apple Silicon.
- New MLX-enabled builds of **gemma4** and **qwen3.6** may change the 2026-05-14 verdicts (which found gemma4 26B MoE NVFP4 fastest and MLX-bf16 variants either retired or default).
- **Ornith 1.0** (DeepReinforce AI, released 2026-06-25, MIT license) is a new candidate family: 9B/31B dense, 35B/397B MoE; `ornith:9b` (5.6 GB) and `ornith:35b` (21 GB) are on Ollama. Caveat: it is RL-tuned for *agentic coding* (Terminal-Bench 2.1, SWE-Bench); fit for radiology finding extraction is unverified. MLX support appears partial (GGUF-first on Ollama).

## Known inconsistency deliberately left in place until this round

Discovered during the 2026-07-01 merge: three artifacts still name `qwen3.6:35b-a3b-mlx-bf16` as the local default extractor while code says `gemma4:26b-nvfp4`. **Do not patch these ahead of the reassessment** — they get swept into consistency with whatever this round decides:

- `docs/model-selection-notes.md` — "Current Defaults" #5 and curated-list entries/order
- `.env.ollama.example` — `IPL_MODEL`, `IPL_FALLBACK_MODEL` (`gpt-oss:20b`, retired 2026-05-14), `IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY=1` (code auto-default is now 2)
- `docs/extraction-usage.md` — provider table "local default", model examples, Ollama profile pull list and `.env.ollama.example` summary

Source of truth for the current code state: `src/finding_extractor/llm/defaults.py` (`COMMON_MODELS`), `src/finding_extractor/llm/model_settings.py` (`EXTRACTION_PRESETS["local"]`), and the 2026-05-14 DEV_LOG entry.

## Scope

1. **Version/capability survey** (research first, no pulls yet):
   - Current Ollama release notes since 0.24.0 — MLX runtime changes, `reasoning_effort` handling, tool-call renderer fixes (the 0.22.1 breakage forced gemma4 onto `NativeOutput`; check whether it was fixed, which could reopen tool-mode for gemma4), issue #6544 (`num_ctx`, → PR-026).
   - Latest MLX-enabled gemma4 and qwen3.6 tags: new quantizations (NVFP4/mxfp8 successors), size/speed claims.
   - Ornith 1.0: available tags, structured-output/tool-calling behavior on Ollama, thinking-mode surface, whether an MLX build exists.
2. **Candidate matrix + bench** on the established harness (6-report bench, concurrency=2, same protocol as 2026-05-14): incumbent `gemma4:26b-nvfp4`, incumbent reviewer/fallback `qwen3.6:35b-a3b-*`, newest MLX gemma4/qwen3.6 builds, `ornith:35b` (and `ornith:9b` only if 35B shows signal). Logfire monitoring on per standing practice.
3. **Quality pass**: reviewer eval + finding-name overlap analysis (the gemma4/qwen3.6 complementarity result, Jaccard 0.22–0.50, feeds PR-027 — check whether Ornith adds a third complementary vocabulary or is redundant).
4. **Decide defaults** (extractor / reviewer / fallback / concurrency) and update code: `defaults.py`, `model_settings.py` presets and per-family branches, `core/config.py` local-only auto-defaults, tests.
5. **Consistency sweep** (closes the drift above): `model-selection-notes.md`, `.env.ollama.example`, `extraction-usage.md`, `configuration.md` if touched. Verify with an `rg` for the outgoing model IDs across active docs.
6. **Wrap-up**: DEV_LOG entry, new section in `eval-ollama-models-report.md`, mark this plan complete/archive.

## Interactions with other active work

- `docs/plans/pydantic-ai-thinking-capability-simplification.md` — its Ollama branch is a deliberate no-change zone; if this round changes the model roster, the per-family branches in `build_ollama_settings` / `_ollama_supported_reasoning_for_model` change here, not there. Sequence whichever lands first carefully.
- **PR-025** (collapse manual Ollama reasoning plumbing) — the version survey in step 1 doubles as the parity-check trigger evidence.
- **PR-026** (`num_ctx`) — re-check issue #6544 status during step 1.
- **PR-027** (combined-extractor pipeline) — step 3's overlap analysis directly informs whether the merge-pipeline idea should include Ornith.

## Non-goals

- No cloud-provider default changes (Gemini Flash / GPT-5.2 defaults untouched).
- No local-only policy changes (separate: `docs/plans/local-only-future-tightening.md`).

## References

- [Ornith 1.0 announcement/site](https://ornith.site/), [Ollama library: ornith](https://ollama.com/library/ornith), [Ornith-1.0-35B on Hugging Face](https://huggingface.co/deepreinforce-ai/Ornith-1.0-35B), [local run guide](https://codersera.com/blog/how-to-run-ornith-1-0-locally-2026/)
- 2026-05-14 round: DEV_LOG entry + `eval-ollama-models-report.md` §"2026-05-14 round"
