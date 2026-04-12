# Setup Guide

## Prerequisites

- **uv** -- Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **Node.js + npm** -- for web linting/formatting tools
- **Docker + Docker Compose** -- for running the full stack (API + worker + Redis)
- **Task** -- task runner ([install](https://taskfile.dev/installation/))

## Quick Start

```bash
# 1. Install Python and Node dependencies
task setup

# 2. Set up configuration
cp config.toml.example config.toml
# Edit config.toml as needed (non-secrets only)

# 3. Set provider API keys (at least one required for extraction)
export OPENAI_API_KEY=...
# and/or:
export ANTHROPIC_API_KEY=...
export GOOGLE_API_KEY=...
export OPENROUTER_API_KEY=...
# Or put these in a .env file (used by batch/eval commands via --env-file .env)

# 4. Verify setup
task lint
task test
```

## Running

Run `task --list` to see all available commands. Key workflows:

- `task stack:up` / `task stack:up:full` -- start Docker stack
- `task test` -- run unit tests
- `task lint` -- run all linters
- `uv run finding-extractor <report.txt>` -- extract findings from a report

See `docs/configuration.md` for the full configuration reference.

## Local Models (Ollama)

For PHI-safe local extraction without API keys:

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull qwen3.5:35b-a3b`
3. Set `OLLAMA_BASE_URL=http://localhost:11434/v1` in `.env`
4. See `docs/extraction-usage.md` and `config.toml.example` (Ollama section) for recommended settings
