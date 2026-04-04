# Ollama Modelfiles

Custom Ollama model configurations optimized for radiology extraction.

## Building

```bash
# gemma4 26B MoE (fast, 3.8B active params)
ollama create gemma4-radextract -f ollama/gemma4-radextract.Modelfile

# gemma4 31B Dense (higher quality, slower)
ollama create gemma4-radextract-dense -f ollama/gemma4-radextract-dense.Modelfile
```

## What the Modelfiles set

Conservative decoding defaults for structured extraction:
- Low temperature (0.1) and fixed seed for consistency
- 32K context window
- 2K max output tokens
- Extraction-focused system prompt

The Modelfiles do **not** include the output schema — that's handled per-request by PydanticAI.

## Usage

```bash
uv run finding-extractor report.txt --model ollama:gemma4-radextract
uv run finding-extractor report.txt --model ollama:gemma4-radextract-dense
```

## Multi-model setup

For extraction + review with different models, set `OLLAMA_MAX_LOADED_MODELS=4` in your environment so Ollama keeps both models loaded:

```bash
export OLLAMA_MAX_LOADED_MODELS=4
```

See `config.toml.example` for recommended settings.

## NativeOutput

Models like gemma4, gemma3, deepseek-r1, and MedGemma don't support PydanticAI's tool-calling mode reliably. The extractor automatically detects these and uses PydanticAI's `NativeOutput` (JSON schema mode) instead. No manual configuration needed.
