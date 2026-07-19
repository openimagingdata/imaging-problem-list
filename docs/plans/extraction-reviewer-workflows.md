# Extraction Reviewer: Integration and Workflow Maximization

Created: 2026-07-07
Status: Phase A in progress

## Context and decisions (2026-07-07)

The extraction reviewer (`extraction_reviewer/`, design in [extraction-reviewer.md](extraction-reviewer.md)) was built and finished on `feature/review-maker` but sat unintegrated on a stale base. Meanwhile the extractor-evals redesign was descoped to a v1 that needs exactly this kind of tool: **10 human-adjudicated gold cases** scored by an honest matcher (see the descope note in [extractor-evals-redesign.md](extractor-evals-redesign.md)).

Decisions made:
- The reviewer is a keeper and becomes the **primary human-review instrument** for extraction QA *and* gold adjudication.
- Its vanilla-JS/no-CDN architecture is a **sanctioned exception** to the Alpine/Flowbite convention — the offline `file://` zero-install requirement justifies it (documented here rather than changing the tool).
- Integration path: cherry-copy onto a fresh branch from dev (not rebase) — the stale branch's `tests/test_model_policy.py` edit is an unrelated holdover, superseded on dev, and is deliberately dropped.

## Phase A — Land on dev (this branch: `feature/extraction-reviewer`)

1. [x] Copy `extraction_reviewer/` + `docs/plans/extraction-reviewer.md` verbatim from the worktree (excluding gitignored build output)
2. [x] Re-apply shared-file edits: `package.json` lint/format globs; `.gitignore` (`.codex/`, build output); DEV_LOG 2026-04-17 entry in chronological position
3. [x] Verify: `uv run pytest` (742 passed), eslint/htmlhint/prettier over the new globs, `build.py` smoke (667.8 KB), `pack.py --embed` smoke against the bundled samples
4. [ ] Merge to dev; remove the `feature/review-maker` branch + `../imaging-problem-list-review` worktree (`wt`)

Deferred from the old branch: nothing else — the samples ship as-is (they predate the example2 laterality/typo fixes; refreshing them happens naturally in Phase B when gold work touches sample data).

## Phase B — Gold-adjudication mode (serves evals v1)

The reviewer currently emits *verdicts* (`*.review.json`: approve / flag+comment / missed findings). Gold adjudication needs *corrected truth* (`*.gold.v1.json`). Two-step approach, cheapest first:

1. **Converter script (`scripts/review_to_gold.py`)** — applies a review JSON to its source extraction JSON: approved findings pass through; flagged findings surface for correction; missed findings become stub entries to fill in. Output is a gold *draft* the adjudicator finalizes in an editor. No UI changes required.
2. **Minimal UI additions** (only what the converter can't infer):
   - Structured correction on "flag": which field is wrong (presence / laterality / body region / attribute value / evidence span) and the corrected value — replaces free-text-only comments for the common cases.
   - Per-report metadata picker: `difficulty` (easy/medium/hard) + controlled `tags` (the evals plan vocabulary: negation_heavy, laterality_sensitive, nonfinding_heavy, long_multichunk, reviewer_lift_candidate, …) — feeds `gold_manifest.yaml` directly.
3. **Not in scope**: full in-tool structured editing of every finding field. Revisit only if converter+editor round-trips prove too slow during the first 10-case adjudication.

Acceptance: one half-day session produces the 10-case `gate` set (per the evals-v1 gate recipe) using pack.py-bundled reports + the converter, with manifest metadata captured in-tool.

## Phase C — Workflow integration

1. **Taskfile targets**: `review:build` (build.py), `review:pack -- <reports-dir>` (zip/embed bundle) so the tool is discoverable via `task --list`.
2. **Batch-run handoff**: document (and if needed, glue) pointing `pack.py` at a `finding-extractor-batch` output directory + source reports — extract → bundle → send to reviewer becomes one documented flow. This composes with the windows-csv handoff: the same colleague running CSV extractions can receive a reviewer bundle for the outputs.
3. **`docs/human-review-workflow.md`**: rewrite around the reviewer tool as the instrument (current doc predates it), folding in the evals plan's adjudication rules (verbatim evidence spans, blanket-negative policy, exam_info completion).
4. **Eval ingestion**: `finding-extractor-eval import-gold` (evals v1) consumes the converter's output + manifest. The reviewer→converter→import-gold pipeline is the documented source-of-truth path for gold.
5. **Docs index + README**: reviewer listed in the main README's tooling section; both reviewer plan docs indexed.

## Sequencing

Phase A now. Phase B and evals-v1 code (matcher, import-gold) proceed in parallel — both must land before the half-day adjudication session. Phase C items 1–2 are cheap and ride with Phase B; 3–4 land with evals v1. All of this precedes the local-model MLX reassessment round, which then gets gold-scored accuracy columns (see [local-model-mlx-reassessment.md](local-model-mlx-reassessment.md)).

## Open questions

- Gold schema: the evals plan names `*.gold.v1.json` but doesn't fix the schema; proposal is "extraction schema + adjudication provenance fields." To be settled at the start of evals-v1 implementation.
- Should reviewer bundles for the colleague workflow (windows-csv) include the REVIEWER_GUIDE by default? (Currently yes via build.py embedding.)
