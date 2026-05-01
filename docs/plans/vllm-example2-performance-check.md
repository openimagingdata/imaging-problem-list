# Plan: vLLM Example2 Performance Check

## Context

Confirm that the configured vLLM endpoints work through the extractor and
capture basic performance characteristics on representative reports from
`sample_data/example2/`.

Target models:

- `vllm:google/gemma-4-31B-it`
- `vllm:openai/gpt-oss-120b`

## Plan

1. Write this plan before running model calls.
2. Select a small report subset from `sample_data/example2/` that covers CT,
   XR, US, and MR if feasible.
3. Run extractor-only checks first:
   - disable reviewer with `IPL_REVIEWER_ENABLED=false`
   - disable fallback with `IPL_FALLBACK_MODEL=null`
   - disable persistence with CLI default `--no-store`
   - keep validation enabled
4. Capture wall-clock duration, exit status, finding count, warning/validation
   status, and any provider/runtime errors for each run.
5. Compare Gemma 4 and GPT OSS on the same reports where both complete.
6. Update this plan with final status and summarize results for the user.

## Status

- 2026-04-24: Plan created. Runs pending.
- 2026-04-24: Initial Gemma 4 run reached the endpoint but failed with
  `tool_choice="required" requires --tool-call-parser to be set`. Updated the
  runtime to route `vllm:` models through `NativeOutput` / JSON-schema output
  instead of tool calling.
- 2026-04-24: Targeted regression tests passed after the routing change:
  `uv run pytest tests/test_model_resilience.py tests/test_extraction.py tests/test_config.py tests/test_model_policy.py`
  (`227 passed`).
- 2026-04-24: Completed extractor-only performance checks with reviewer disabled,
  serial chunk extraction, semantic chunking trigger set to `32`, validation
  enabled, and longer subagent timeouts.
- 2026-04-24: Added local `.env.vllm` plus tracked `.env.vllm.example` for the
  tested Gemma 4 extractor / GPT OSS reviewer profile.
- 2026-04-24: Added matching local `.env.ollama` plus tracked
  `.env.ollama.example` and updated usage docs so vLLM and Ollama profile-based
  configuration are documented side by side.
- 2026-04-24: Applied review hardening for vLLM credentials and exact served
  model names. `VLLM_API_KEY` is isolated from `OPENAI_API_KEY`; accepted case
  variants are normalized before runtime requests.
- 2026-04-24: Local-only follow-up: configured vLLM endpoints are allowed under
  `--local-only` / `IPL_LOCAL_ONLY=true` only when their hosts are listed in
  `IPL_VLLM_LOCAL_ONLY_ALLOW_HOSTS`; cloud providers and unapproved vLLM hosts
  remain blocked.

## Results

| Report | Model | Reasoning | Wall time | Findings | Verbatim errors | Notes |
|---|---|---:|---:|---:|---:|---|
| `xr_chest_20210614.md` | `vllm:google/gemma-4-31B-it` | `none` | 49.25 s | 28 | 0 | Impression chunk retried once |
| `xr_chest_20210614.md` | `vllm:openai/gpt-oss-120b` | `medium` | 30.24 s | 27 | 0 | Impression chunk retried once |
| `xr_chest_20210614.md` | `vllm:openai/gpt-oss-120b` | `low` | 23.80 s | 25 | 0 | Impression chunk retried twice |
| `ct_abdomen_20230118.md` | `vllm:google/gemma-4-31B-it` | `none` | 65.43 s | 54 | 0 | Clean completion |
| `ct_abdomen_20230118.md` | `vllm:openai/gpt-oss-120b` | `medium` | 65.71 s | 53 | 0 | Findings chunk retried once |
| `ct_abdomen_20230118.md` | `vllm:openai/gpt-oss-120b` | `low` | 56.54 s | 46 | 0 | Findings retried twice; impression retried once |

### Gemma Extractor + GPT OSS Reviewer

Reviewer-enabled runs used `vllm:google/gemma-4-31B-it` as extractor
(`reasoning=none`) and `vllm:openai/gpt-oss-120b` as reviewer.

| Report | Reviewer reasoning | Wall time | Findings | Verbatim errors | Review behavior |
|---|---:|---:|---:|---:|---|
| `xr_chest_20210614.md` | `low` | 43.68 s | 28 | 0 | Reviewed 2 chunks, no issues |
| `xr_chest_20210614.md` | `medium` | 39.77 s | 28 | 0 | Reviewed 2 chunks, no issues |
| `ct_abdomen_20230118.md` | `medium` | 127.70 s | 56 | 0 | Flagged findings chunk, re-extracted successfully |

All completed outputs had coverage warnings. That is expected for the current
strict coverage heuristic and should be interpreted separately from endpoint
connectivity/performance.
