# Plan: Evaluate Ollama `nemotron-cascade-2`

## Context

We want to evaluate `https://ollama.com/library/nemotron-cascade-2` in this repo's
existing extractor evaluation workflow and capture what we learn in the active
evaluation/reference docs.

As of 2026-04-10, the Ollama library page describes `nemotron-cascade-2` as:
- a 30B MoE model with 3B active parameters
- tool-capable
- thinking-capable
- 24GB download size
- 256K context window

That creates two concrete tasks:
1. verify or add the repo-side model-policy/runtime support needed to evaluate it
2. run an actual local eval when the model is available, then record findings in
   the evaluation docs

## Execution Steps

### 1. Inspect current support surface

Status: completed

- Review the current Ollama reasoning/tool-support policy in
  `src/finding_extractor/llm/model_settings.py`.
- Review existing Ollama evaluation/reporting docs and commands:
  `docs/eval-ollama-models-report.md`, `docs/eval-usage.md`,
  `docs/extraction-usage.md`, `Taskfile.yml`.
- Check local Ollama availability and installed models to see whether the
  evaluation can be run immediately.

### 2. Add repo support for `nemotron-cascade-2`

Status: in progress

- Update model-policy/runtime handling if `nemotron-cascade-2` needs explicit
  family recognition for tool support and reasoning control.
- Add or extend unit tests for the supported reasoning/output-mode behavior.
- Keep changes narrowly scoped to evaluated behavior rather than speculative
  model-family expansion.

### 3. Run the evaluation

Status: pending

- If the model is not already present locally, request approval to pull it into
  the local Ollama model store.
- Run at least one extractor eval using the existing harness, starting with the
  smoke dataset and then a broader dataset if runtime/behavior is acceptable.
- Capture the exact model string, reasoning level, dataset, and notable runtime
  or quality characteristics from the run artifacts.

### 4. Update active documentation

Status: pending

- Update `docs/eval-ollama-models-report.md` with `nemotron-cascade-2` findings.
- Update any active user/reference docs that mention recommended Ollama models
  or supported reasoning behavior, if the evaluation changes those statements.
- Add a concise `docs/DEV_LOG.md` entry summarizing the support/evaluation work.

### 5. Final verification and doc review

Status: pending

- Run targeted tests for the changed model-policy/runtime behavior.
- Re-read the touched docs for consistency with the final implementation and
  measured results.
- Mark this plan complete once code, eval notes, and docs all reflect the final
  state.
