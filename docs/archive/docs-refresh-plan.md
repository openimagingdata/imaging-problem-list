# Docs Refresh Plan

Status: Complete

## Goal

Refresh the active documentation after recent package, model, and local-runtime changes. Keep the current documentation structure, fix incorrect active reference docs, and move or relabel plan documents that are no longer active.

This is a documentation-only cleanup. Do not change runtime behavior, public APIs, schemas, migrations, or tests except where a docs example exposes an already-supported command or option.

## Audit Summary

The overall docs structure is sound. The top-level split between usage guides, internals guides, configuration, testing, backlogs, plans, work log, and archive should stay in place.

The stale areas to fix are concentrated in a few active docs:

- `docs/configuration.md`: update the Ollama output-mode text. It currently says Gemma 4 cannot use PydanticAI tool-calling, but current policy/tests treat Gemma 4 as tool-capable and keep Gemma 3/MedGemma on `NativeOutput`.
- `docs/extraction-usage.md`: update validation semantics. Remove the stale claim that `--validate` always returns `is_valid=True` and no `verbatim_errors`; `ValidationResult.is_valid` was removed. Also replace the Python API example's `status_callback` wording with `progress_callback`.
- `docs/eval-internals.md`: replace stale module names. Use `cli/batch.py` and `cli/batch_engine.py` instead of `batch_cli.py`, and `cli/eval_cmd.py` instead of `eval_cli.py`.
- `docs/model-selection-notes.md`: reconcile the curated/default model list with `src/finding_extractor/llm/defaults.py`, `.env.ollama.example`, `.env.vllm.example`, and `config.toml.example`. The current note under-represents Qwen3.6, Gemma 4, MedGemma, and vLLM choices.
- `docs/eval-ollama-models-report.md`: fix internal drift in reviewer/default recommendations. Earlier text still implies no reason to change from gpt-oss reviewer/fallback, while later reviewer grading recommends `qwen3.6:35b-a3b-bf16` with `reasoning=low`.
- `docs/plans/`: move or clearly relabel completed/historical plans. At minimum review `coding-cli-plan.md`, `local-only-mode.md`, and `ollama-local-model-support.md`.

Do not edit `docs/archive/` for stale module names unless a link is broken. Archived docs are historical records.

## Recommended Cleanup Sequence

1. Fix incorrect active reference docs first:
   - `docs/configuration.md`
   - `docs/extraction-usage.md`
   - `docs/eval-internals.md`
   - `docs/model-selection-notes.md`
   - `docs/eval-ollama-models-report.md`

2. Reconcile model/default documentation against current sources:
   - `src/finding_extractor/llm/defaults.py`
   - `.env.ollama.example`
   - `.env.vllm.example`
   - `config.toml.example`
   - `src/finding_extractor/llm/model_settings.py` for reasoning/output-mode policy
   - `tests/test_model_policy.py`, `tests/test_extraction.py`, and `tests/test_model_resilience.py` for expected behavior

3. Clean up plan-document status:
   - Move completed plans from `docs/plans/` to `docs/archive/`, or create `docs/plans/archive/` if keeping plan history grouped is preferred.
   - If a plan is retained in place, mark it clearly as historical or active backlog.
   - Keep genuinely active plans in `docs/plans/`.

4. Update navigation after moves:
   - Update `docs/README.md` "Active Plans".
   - Add a small "Reports / Benchmarks / Draft References" section for `docs/eval-ollama-models-report.md` and `docs/technical-imaging-findings.md`.
   - Ensure `docs/pending-refactoring.md` no longer lists PR-020 once this cleanup is complete.

5. Add a concise `docs/DEV_LOG.md` entry after implementation:
   - Mention corrected stale active docs.
   - Mention any plan-document moves.
   - Keep it as a development log entry, not a user-facing changelog.

## Follow-On Implementation Prompt

Use this prompt for the agent or engineer doing the actual docs cleanup:

```text
Update the active project documentation to remove stale package, validation, model-default, and local-runtime references identified in docs/plans/docs-refresh-plan.md.

Constraints:
- Documentation-only changes unless a docs example reveals an already-supported command spelling that must be copied exactly.
- Do not edit archived docs for stale prose. Only update archive links if a moved document requires it.
- Keep the current top-level documentation structure. Do not do a broad reorganization.
- Move or clearly relabel completed plans under docs/plans/.
- Update docs/README.md after any plan moves.
- Update docs/DEV_LOG.md with the final completed-state summary.

Implementation targets:
- Fix docs/configuration.md Ollama NativeOutput/tool-calling statements for Gemma 4, Gemma 3, MedGemma, qwen, gpt-oss, and nemotron families.
- Fix docs/extraction-usage.md validation semantics and progress_callback example.
- Fix docs/eval-internals.md stale cli module references.
- Reconcile docs/model-selection-notes.md with src/finding_extractor/llm/defaults.py, .env.ollama.example, .env.vllm.example, and config.toml.example.
- Resolve internal recommendation drift in docs/eval-ollama-models-report.md.
- Move or mark completed/historical plans, especially coding-cli-plan.md, local-only-mode.md, and ollama-local-model-support.md.

Acceptance checks:
- Run an active-doc stale-term search excluding docs/archive/.
- Run a Markdown local-link check.
- Run task test only if docs examples are changed in a way that implies CLI/runtime behavior.
- Show git diff and summarize only the docs changed.
```

## Acceptance Checks

Run these checks after the docs cleanup is implemented:

```bash
rg -n "api_models\.py|api_routes\.py|api_services\.py|api_dependencies\.py|batch_cli\.py|eval_cli\.py|llm_config|ValidationResult\.is_valid|is_valid=True|status_callback|code_assinger|extractor-agent-plans|docs/extractor-agent-plans" \
  docs README.md SETUP.md DEPLOYMENT.md \
  --glob '!docs/archive/**'
```

Expected result: no active-doc hits except intentional historical context in `docs/DEV_LOG.md` or checklist text that explicitly describes what was fixed.

```bash
uv run python -c 'import pathlib,re; roots=[pathlib.Path("README.md"), pathlib.Path("SETUP.md"), pathlib.Path("DEPLOYMENT.md"), *pathlib.Path("docs").rglob("*.md")]; bad=[]; pat=re.compile(r"\[[^\]]+\]\(([^)]+)\)"); \
for f in roots: \
    text=f.read_text(); \
    [bad.append((str(f), m.group(1))) for m in pat.finditer(text) if "://" not in m.group(1) and not m.group(1).startswith("#") and (lambda p: p and not (f.parent / p).resolve().exists())(m.group(1).split("#",1)[0].strip("<>"))]; \
print("broken links:", len(bad)); [print(f"{f}: {u}") for f,u in bad]'
```

Expected result: `broken links: 0`.

Run `task test` only if documentation examples or defaults are changed in a way that should be backed by executable behavior. For pure prose/link/status updates, the stale-term search and link check are sufficient.

## Structural Recommendation

Keep the current docs organization. It is still navigable and maps well to the project:

- Usage guides and internals guides remain paired by subsystem.
- `docs/README.md` remains the main index.
- `docs/archive/` remains historical.
- `docs/pending-refactoring.md` remains the near-term cleanup queue.
- `docs/future-improvements.md` remains the longer-horizon backlog.

Make only narrow structural changes:

- Move completed plans out of the active `docs/plans/` list, or mark them plainly as historical.
- Add a reports/benchmarks/drafts section to `docs/README.md`.
- Keep benchmark reports and ontology drafts discoverable without presenting them as current operational runbooks.

## Assumptions

- `dev` is the intended base for this cleanup.
- The branch that contains this document is only a planning branch.
- No public APIs, schemas, migrations, or runtime behavior should change as part of the plan document itself.
- The later implementation branch may update active docs and move docs files, but should still avoid broad reorganization.
