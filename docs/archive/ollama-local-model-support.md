# Plan: Proper Ollama Local Model Support

## Context

Local Ollama models with thinking behavior (gemma4 MoE, deepseek-r1, gemma3, MedGemma) fail with PydanticAI's default tool-calling output mode. They work with `NativeOutput` (JSON schema mode). Models like gpt-oss and qwen3.5 work fine with tools. We need to detect which mode a model needs and apply it automatically across both extraction and coding workflows.

Additionally, Ollama-specific settings (timeout, concurrency) need to be part of the project's config flow via `config.toml`, not a side `.env.ollama` file. Multi-model Ollama (extraction + reviewer) works with sufficient `OLLAMA_MAX_LOADED_MODELS` — this is Ollama server config documented in setup docs, not our app config.

## First step: copy plan into repo

Copy this plan to `docs/plans/ollama-local-model-support.md` and update it there as implementation proceeds.

## Changes

### 1. Add Ollama output mode detection

**File:** `src/finding_extractor/llm/model_settings.py`

Add `ollama_needs_native_output(model_name: str) -> bool`:
- Returns True for families with known tool-calling issues: `gemma4` (non-dense variants), `gemma3`, `deepseek-r1`, `medgemma`
- Returns False for families known to work with tools: `gpt-oss`, `llama3`, `qwen3`, `qwen3.5`, `nemotron`
- Conservative default for unknown families: True (native output is safer)

Only applies when `provider_from_model_id(model_name) == "ollama"`. Returns False for all non-Ollama models.

### 2. Add shared output_type wrapping helper

**File:** `src/finding_extractor/llm/resilience.py`

Add a utility function:
```python
def resolve_output_type(output_type: Any, model_name: str, fallback_model_name: str | None = None) -> Any:
    """Wrap output_type in NativeOutput if any configured Ollama model needs it.
    
    When primary and fallback use different output modes (e.g. gpt-oss with tools + 
    gemma4 needing native), bias to native — native output works for all models,
    while tool mode doesn't.
    """
    needs_native = ollama_needs_native_output(model_name)
    if fallback_model_name and not needs_native:
        needs_native = ollama_needs_native_output(fallback_model_name)
    if needs_native:
        from pydantic_ai import NativeOutput
        return NativeOutput(output_type)
    return output_type
```

Apply in `create_resilient_agent()` before passing `output_type` to `Agent()`, passing both `model_name` and the fallback model name from settings.

### 3. Apply wrapping in coding agents

**File:** `src/finding_extractor/coding/agents.py`

In `create_finding_term_agent()`, `create_location_term_agent()`, `create_finding_selector_agent()`, and `create_location_selector_agent()`: call `resolve_output_type(output_type, model_name)` when constructing `Agent()`.

This requires threading the model_name through to these functions. Currently they receive `AgentModelRuntime` which has a `.model` but not the string model name. Options:
- Add `model_name: str` to `AgentModelRuntime` dataclass
- Or pass model_name alongside runtime to the coding agent constructors

Adding it to `AgentModelRuntime` is cleaner — it's already a dataclass that bundles model config.

### 4. Move Ollama settings into config.toml

**File:** `config.toml.example`

Add Ollama-appropriate settings as comments showing the recommended values for local use:
```toml
# For local Ollama use, uncomment and adjust:
# subagent_timeout_seconds = 300
# extractor_max_subagent_concurrency = 1
# allow_unknown_model_reasoning = true
# default_model = "ollama:gpt-oss:20b"
# fallback_model = "ollama:gpt-oss:20b"
# reviewer_model = "ollama:gpt-oss:120b"
```

These are all existing settings — no new config fields needed. Just documenting the Ollama-appropriate values.

`OLLAMA_BASE_URL` and `OLLAMA_MAX_LOADED_MODELS` are Ollama server env vars, documented in setup docs only.

### 5. Create Modelfiles

**Directory:** `ollama/`

- `ollama/gemma4-radextract.Modelfile` — already exists (FROM gemma4:26b)
- `ollama/gemma4-radextract-dense.Modelfile` — new, FROM gemma4:31b
- `ollama/README.md` — build instructions and usage

### 6. Update documentation

- `docs/extraction-usage.md` — update Ollama section: new model families, NativeOutput behavior, Modelfile usage, `OLLAMA_MAX_LOADED_MODELS` for multi-model, `config.toml` settings for local use
- `docs/configuration.md` — update Ollama model family list with new families
- `docs/eval-ollama-models-report.md` — update with NativeOutput findings
- `docs/DEV_LOG.md` — add entry

### 7. Tests (in existing test files listed in Taskfile.yml)

**`tests/test_model_policy.py`** (or whichever file covers model_settings):
- `ollama_needs_native_output()` returns True for gemma4, gemma3, deepseek-r1, medgemma
- Returns False for gpt-oss, llama3, qwen3.5, nemotron
- Returns False for non-Ollama models (openai:gpt-5.2, etc.)

**`tests/test_model_resilience.py`**:
- `resolve_output_type()` wraps in NativeOutput when `ollama_needs_native_output` is True
- Does NOT wrap when False
- Wraps when primary is tool-capable but fallback needs native (bias to native)
- Does NOT wrap when both are tool-capable
- `create_resilient_agent()` passes wrapped output_type through to Agent
- `AgentModelRuntime` carries model_name

**`tests/test_extraction_runtime.py`**:
- Reviewer callback is configured correctly when extraction and reviewer are distinct Ollama models (unit-level wiring check, not live Ollama server test)

**Tests for coding agents** (in the existing coding test file, or `test_model_resilience.py`):
- Each of the four coding agent factories (`create_finding_term_agent`, `create_location_term_agent`, `create_finding_selector_agent`, `create_location_selector_agent`) applies `resolve_output_type` and uses the correct model_name from `AgentModelRuntime`
- Verify NativeOutput wrapping flows through when runtime carries an Ollama model that needs it

## Files to Modify/Create

| File | Change |
|---|---|
| `src/finding_extractor/llm/model_settings.py` | Add `ollama_needs_native_output()` |
| `src/finding_extractor/llm/resilience.py` | Add `resolve_output_type()`, apply in `create_resilient_agent()`, add `model_name` to `AgentModelRuntime` |
| `src/finding_extractor/coding/agents.py` | Apply `resolve_output_type()` in agent constructors |
| `config.toml.example` | Add commented Ollama settings |
| `ollama/gemma4-radextract.Modelfile` | Already exists |
| `ollama/gemma4-radextract-dense.Modelfile` | New |
| `ollama/README.md` | New |
| `docs/extraction-usage.md` | Update Ollama section |
| `docs/configuration.md` | Update model families |
| `docs/eval-ollama-models-report.md` | Update findings |
| `docs/DEV_LOG.md` | Add entry |
| `tests/test_model_policy.py` | Native output detection tests |
| `tests/test_model_resilience.py` | resolve_output_type + agent wrapping tests |
| `tests/test_extraction_runtime.py` | Ollama reviewer path test |

## Verification

1. `task test` — all existing + new tests pass
2. Small snippet: `resolve_output_type(ExtractedChunkFindings, "ollama:gemma4:26b")` returns NativeOutput-wrapped
3. Small snippet: `resolve_output_type(ExtractedChunkFindings, "ollama:gpt-oss:120b")` returns unwrapped
4. CLI: `gemma4-radextract` on shoulder XR — succeeds
5. CLI: `gpt-oss:20b` on shoulder XR — still succeeds (no regression)
6. CLI: `gpt-oss:20b` extraction + `gpt-oss:120b` review with `OLLAMA_MAX_LOADED_MODELS=4` — both models load, review works
