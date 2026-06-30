# Plan: On-Prem vLLM Model Support

## Context

Two configured on-premises vLLM deployments should be usable anywhere the
extractor accepts a model ID:

- Gemma 4 31B: `vllm:google/gemma-4-31B-it`
- GPT OSS 120B: `vllm:openai/gpt-oss-120b`

The deployments expose OpenAI-compatible chat completion endpoints. PydanticAI's
current documented integration path for OpenAI-compatible APIs is
`OpenAIChatModel` with `OpenAIProvider(base_url=..., api_key=...)`, so the
project should build explicit model objects instead of trying to route these
through a cloud provider shorthand.

## Implementation Plan

1. Add this plan to `docs/plans/` before implementation.
2. Add `vllm` as a supported provider prefix in the model policy.
3. Add runtime settings for the on-prem vLLM base URLs and optional API key.
4. Build `vllm:*` models as `OpenAIChatModel` instances with deployment-specific
   `OpenAIProvider` objects.
5. Add vLLM reasoning behavior:
   - `google/gemma-4-31B-it`: no explicit reasoning controls.
   - `openai/gpt-oss-120b`: support `none`, `low`, `medium`, `high`; normalize
     `minimal` to `low`.
6. Document configuration and example usage in `config.toml.example`,
   `docs/configuration.md`, and `docs/extraction-usage.md`.
7. Add concise user-facing notes to `docs/DEV_LOG.md`.
8. Add regression tests for model validation, settings resolution, runtime model
   construction, and reasoning normalization.
9. Extend `--local-only` so configured, allowlisted vLLM endpoints are permitted
   while cloud providers and unapproved vLLM hosts remain blocked.
10. Run targeted tests and update this plan with the final status.

## Status

- 2026-04-24: Plan created.
- 2026-04-24: Implementation complete. Added `vllm:` policy/runtime support,
  model-specific reasoning handling, vLLM endpoint configuration,
  docs, and regression tests. Targeted verification passed:
  `uv run pytest tests/test_model_policy.py tests/test_extraction.py tests/test_model_resilience.py tests/test_config.py`.
- 2026-04-24: Review hardening complete. vLLM construction now uses a
  non-secret placeholder key when `VLLM_API_KEY` is unset so `OPENAI_API_KEY`
  is never sent to on-prem endpoints. vLLM model IDs canonicalize to exact
  served names before runtime requests.
- 2026-04-24: Local-only follow-up complete. `--local-only` /
  `IPL_LOCAL_ONLY=true` allows configured vLLM models whose hosts are listed in
  `IPL_VLLM_LOCAL_ONLY_ALLOW_HOSTS` while continuing to reject cloud providers,
  Ollama cloud tags, and unapproved vLLM hosts. Targeted verification passed:
  `uv run pytest tests/test_model_policy.py tests/test_batch_cli.py tests/test_api.py tests/test_tasks.py tests/test_config.py tests/test_model_resilience.py tests/test_extraction.py`.
