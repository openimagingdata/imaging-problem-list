# Extractor Evals Redesign Plan

Last updated: 2026-03-18
Status: Active

## Purpose

Replace the current eval harness with a decision-grade system for extractor model,
prompt, and pipeline changes.

This plan is optimized for:

1. model-selection decisions first
2. adjudicated gold as source of truth
3. both `extractor_only` and `full_pipeline` evaluation views
4. two tiers shipped together: a fast gate and a deeper benchmark

## Current Problems To Fix

1. The current `smoke` dataset is in-sample because it is built from few-shot prompt
   examples.
2. The current `comprehensive` dataset is only 9 cases and is too skewed to guide
   broad decisions.
3. Current gold is too close to reviewed extractor output in the extractor's own schema.
4. Attribute scoring only checks keys, not values.
5. Matching logic uses presence/location/attribute bonuses before those same fields
   are scored, which can hide semantic errors.
6. Eval runs currently call the runtime with validation disabled and discard runtime
   diagnostics that would help explain regressions.
7. Saved run artifacts are too thin for root-cause analysis.
8. Default eval tasks are not aligned with the current default model stack.

## Core Decisions

1. The new primary datasets are `gate` and `benchmark`.
2. `gate` and `benchmark` must both be held out from prompt examples and any other
   reference cases used in extraction prompting.
3. Source of truth is adjudicated gold in `*.gold.v1.json` files, not raw
   `*.extracted.json` output.
4. Reviewed model output remains useful only as draft material for human review.
5. Every decision-grade eval must run in two variants:
   - `extractor_only`
   - `full_pipeline`
6. All eval runs use `validate=True` and `reliability_mode="lenient"` so quality can
   still be scored when warnings occur.
7. Strict-contract behavior is reported as a derived metric from runtime outputs. Eval
   runs do not perform a second strict replay.
8. `full_pipeline` means reviewer enabled with explicit frozen reviewer config.
9. `extractor_only` means reviewer disabled, with all other runtime settings held
   constant.
10. LLM-as-judge can be added later only as a supplementary diagnostic. It is not a
    gate and it does not replace gold scoring.

## Implementation Contract

### Eval task output

The current task returns only `ExtractedReportFindings`. That is insufficient for the
new design.

Add a new internal output model in `src/finding_extractor/eval/models.py`:

1. `FrozenPipelineConfig`
   - `pipeline_variant`
   - `validate_output`
   - `reliability_mode`
   - `extractor_model`
   - `extractor_reasoning`
   - `reviewer_enabled`
   - `reviewer_model`
   - `reviewer_reasoning`
2. `EvalCaseOutput`
   - `extraction`
   - `validation_result`
   - `warning_payload`
   - `pipeline_diagnostics`
   - `usage`
   - `frozen_config`
3. `EvalCaseArtifact`
   - case name
   - dataset name
   - expected output
   - actual output
   - metric scores and reasons
   - assertion results and reasons
   - pipeline diagnostics
   - warning payload
   - usage
   - structured diff

The eval task adapter should return `EvalCaseOutput`, not bare `ExtractedReportFindings`.
Evaluators should score `ctx.output.extraction` plus the diagnostics carried on the
same object.

### Frozen run configuration

`EvalRunConfig` must be extended so each run is reproducible even if settings change.
The frozen run config persisted to disk must include:

1. dataset path
2. run id
3. extractor model and reasoning
4. reviewer enabled flag
5. reviewer model and reasoning
6. pipeline variant
7. validate flag
8. reliability mode
9. workers
10. timeout seconds
11. retries
12. threshold map

The runner must not rely on ambient settings for reviewer configuration once the eval
run starts.

### Exit-code contract

Define runner exit codes explicitly:

1. `0`: run completed and all enabled thresholds passed
2. `1`: run completed but one or more thresholds failed
3. `2`: task failure, timeout, evaluator failure, dataset error, or artifact-write error

Threshold failures and infrastructure failures must not share the same exit code.

## Dataset Contract

### Initial split targets

1. `benchmark`: 30 adjudicated cases
2. `gate`: 10 adjudicated cases

### Case-selection rules

1. No few-shot prompt example may appear in either split.
2. No single modality may exceed 40% of `benchmark`.
3. No single body region may exceed 40% of `benchmark`.
4. `gate` must include at least:
   - 1 negation-heavy case
   - 1 laterality-sensitive case
   - 1 non-finding-heavy case
   - 1 long multi-chunk case
   - 1 known reviewer-lift case
5. Every case must carry:
   - `source_file`
   - `modality`
   - `body_region`
   - `difficulty`
   - `tags`

### Controlled annotation policy

Do not leave metadata free-form.

1. `difficulty` is one of:
   - `easy`
   - `medium`
   - `hard`
2. Allowed `tags` are:
   - `negation_heavy`
   - `comparison_heavy`
   - `laterality_sensitive`
   - `multi_instance_same_finding`
   - `impression_driven`
   - `nonfinding_heavy`
   - `long_multichunk`
   - `reviewer_lift_candidate`
3. `modality` and `body_region` come from gold `exam_info` unless explicitly
   overridden in metadata.

### Gold import workflow

Add `finding-extractor-eval import-gold`.

Input contract:

1. report files: `<case>.txt` or `<case>.md`
2. gold files: `<case>.gold.v1.json`
3. required manifest: `gold_manifest.yaml`

`gold_manifest.yaml` must be the single source of metadata not carried by the gold
schema. For each case it stores:

1. `difficulty`
2. `tags`
3. optional `notes`
4. optional split override if a case must be forced into `gate` or `benchmark`

Import behavior:

1. reject missing gold files
2. reject invalid gold JSON
3. reject missing manifest entries
4. reject invalid difficulty or tag values
5. infer `modality` and `body_region` from gold `exam_info`
6. write deterministic dataset YAML with stable case ordering

### Adjudication rules

Before gold import, reviewers must normalize these areas consistently:

1. blanket negatives become clinically meaningful absent findings only when they are
   part of extractor truth today
2. non-finding spans must be segmented in the same style expected by current
   evaluators
3. `exam_info` fields must be filled when supported by report text or explicit study
   description, otherwise null
4. `report_text` evidence spans must stay verbatim

Update `docs/human-review-workflow.md` to carry these rules directly.

## Eval Surface Changes

### CLI and Taskfile

1. Add `finding-extractor-eval import-gold`.
2. Add `finding-extractor-eval run --pipeline-variant extractor_only|full_pipeline`.
3. Add explicit reviewer options to `run`:
   - `--reviewer-model`
   - `--reviewer-reasoning`
4. Add `finding-extractor-eval report --slice`.
5. `--slice` accepts exactly:
   - `modality`
   - `body_region`
   - `difficulty`
   - `tag`
6. Add Taskfile commands:
   - `task eval:gate`
   - `task eval:benchmark`
   - `task eval:gate:report`
7. Keep `eval:smoke` and `eval:comprehensive` only as temporary migration aliases,
   then retire them from active docs once `gate` and `benchmark` are stable.

### Run artifacts

Keep `report.json` compact for the pydantic-evals report view, but stop overloading it
as the only source of truth.

Write this run layout:

```text
.eval_runs/<run_id>/
  run_config.json
  report.json
  results.json
  results.jsonl
  cases/
    <case_name>.json
```

Each `cases/<case_name>.json` stores the `EvalCaseArtifact` payload. Full raw report
text is not persisted by default.

## Scoring Contract

### Output-quality metrics

Keep these metric ids:

1. `finding_precision`
2. `finding_recall`
3. `finding_f1`
4. `presence_accuracy`
5. `body_region_accuracy`
6. `laterality_accuracy`
7. `attribute_value_precision`
8. `attribute_value_recall`
9. `attribute_value_f1`
10. `exam_info_accuracy`
11. `verbatim_pass`
12. `verbatim_rate`
13. `nonfinding_category_accuracy`

### Matching rules

Replace the current primary matcher with a quote-first matcher that does not use the
fields later being scored.

Primary matching contract:

1. compare findings using only:
   - normalized `report_text`
   - normalized `finding_name`
2. score candidate pairs with:
   - exact normalized `report_text` match first
   - otherwise weighted similarity: `0.7 * report_text_similarity + 0.3 * finding_name_similarity`
3. do not use presence, laterality, body region, specific anatomy, attributes, or
   exam-info fields in the primary match score
4. when two pairs tie, break ties by:
   - higher `report_text` similarity
   - higher `finding_name` similarity
   - stable order by first occurrence of the quote in the source report
5. keep the match threshold explicit and configurable in code, but do not expose it
   on the CLI in the first implementation

If a diagnostic matcher using location or attributes remains useful, keep it separate
from the scored path and label it diagnostic-only in docs and code.

### Metric definitions

1. presence, location, and attribute metrics are computed only on primary matched pairs
2. attribute-value matching compares normalized `(key, value)` pairs, not keys alone
3. `attribute_value_f1` is the harmonic mean of attribute-value precision and recall
4. `exam_info_accuracy` is the mean of exact-match subchecks for:
   - modality
   - body_region
   - body_part
   - contrast
   - laterality
   - study_description presence-sensitive normalized string match
5. `study_date` is excluded from `exam_info_accuracy` in the first implementation

### Pipeline-health metrics

Keep these metric ids:

1. `validation_warning_rate`
2. `strict_would_fail_rate`
3. `section_failure_rate`
4. `reviewer_request_rate`
5. `reviewer_reextract_rate`
6. `case_timeout_rate`
7. `mean_task_duration_seconds`
8. `mean_requests`
9. `mean_input_tokens`
10. `mean_output_tokens`

Definitions:

1. `strict_would_fail_rate` is derived from the lenient run output using the current
   strict-runtime contract:
   - fail if `validation_error_count > 0`
   - fail if `section_failure_count > 0`
2. `reviewer_request_rate` and `reviewer_reextract_rate` are always `0.0` for
   `extractor_only`
3. task timeouts count as run failures and also increment `case_timeout_rate`

## Gate Policy

### Phase-1 behavior

During Phase 1 and Phase 2, `task eval:gate:report` is the default command for local
and CI visibility. It does not fail the build on score thresholds yet.

`task eval:gate` becomes blocking only after:

1. the 10-case held-out gate set exists
2. the new metrics are implemented
3. three consecutive runs of the default stack are stable enough to set thresholds

### Threshold ratification

Thresholds are not to be invented ad hoc in code.

When the gate corpus is ready:

1. run the default stack three times on `gate` for both variants
2. review per-case artifacts
3. set the initial threshold table in this plan and in `Taskfile.yml`
4. record the final chosen values in `docs/DEV_LOG.md`

Until that ratification step is complete, only infrastructure failures are blocking.

### Final blocking gate surface

Once ratified, the blocking gate must evaluate `full_pipeline` only and must enforce:

1. `finding_f1`
2. `presence_accuracy`
3. `body_region_accuracy`
4. `laterality_accuracy`
5. `attribute_value_f1`
6. `verbatim_pass`
7. `strict_would_fail_rate`

`extractor_only` remains a comparison view, not a release gate.

## Reporting Plan

1. Every report shows:
   - overall metrics
   - slice summaries
   - variant comparison when both runs are available
2. Slice summaries are supported for:
   - modality
   - body region
   - difficulty
   - tag
3. Reports must make reviewer lift or reviewer harm obvious instead of hiding it
   inside one aggregate average.
4. Benchmark reporting is the primary decision tool.
5. Gate reporting stays compact and fail-fast.

## Implementation Phases

### Phase 0: runner and schema foundation

1. add `FrozenPipelineConfig`, `EvalCaseOutput`, and `EvalCaseArtifact`
2. update `make_eval_task()` to return runtime diagnostics with validation enabled
3. extend `EvalRunConfig` and CLI `run` options to freeze reviewer config and variant
4. add new exit-code contract
5. write per-case artifact files

### Phase 1: dataset and gold workflow

1. add `import-gold`
2. add `gold_manifest.yaml` contract
3. update human-review docs with adjudication rules
4. build initial held-out `gate` and seed `benchmark`
5. remove prompt-example leakage from active eval datasets

### Phase 2: evaluator and reporting redesign

1. replace the primary matcher
2. implement attribute-value and exam-info scoring
3. add pipeline-health evaluators
4. add slice reporting
5. add variant comparison to reporting docs and CLI

### Phase 3: gate adoption

1. populate final 30-case benchmark
2. ratify threshold table from actual runs
3. wire `task eval:gate` as blocking
4. retire old dataset/task names from active docs

## Documentation Plan

This plan document is the first required planning artifact. During implementation:

1. keep this file updated as decisions land or scope changes
2. update `docs/eval-usage.md` to reflect the new datasets, CLI surface, task names,
   and gate policy
3. update `docs/eval-internals.md` to reflect the new runtime output model,
   matcher/scoring logic, and artifact layout
4. update `docs/human-review-workflow.md` so gold creation, adjudication, and import
   match the real workflow
5. update `docs/DEV_LOG.md` as phases complete
6. end with a final active-doc sweep so this plan, the usage docs, and the internals
   docs all agree, then mark this plan complete

## Test Plan

### Dataset/import tests

1. gold import rejects missing gold files
2. gold import rejects invalid gold JSON
3. gold import rejects missing manifest metadata
4. invalid `difficulty` or tag values are rejected
5. metadata survives round trip
6. few-shot prompt examples are excluded from both splits
7. split generation is stable and reproducible

### Evaluator tests

1. wrong attribute value fails even when the attribute key matches
2. swapped laterality fails without matcher bias hiding the error
3. wrong body region fails independently of finding detection
4. wrong `exam_info` fails independently of findings quality
5. diagnostic matcher output, if retained, does not affect primary scores
6. verbatim and non-finding metrics still behave correctly

### Runner/report tests

1. both pipeline variants execute and report correctly
2. validation and pipeline diagnostics are captured in results
3. task failures and threshold failures use different exit codes
4. slice reporting works for modality, body region, difficulty, and tags
5. per-case artifacts include diffs and diagnostics without raw report text
6. `task eval:gate` blocks only after threshold ratification is configured

### Acceptance runs

1. `task eval:gate:report` is cheap enough for routine local and CI use
2. `task eval:benchmark` is the decision-grade run for model and prompt changes
3. current default models are the documented default eval stack unless explicitly
   overridden
4. the benchmark includes at least one known reviewer-lift case from current
   model-selection findings

## Completion Criteria

This plan is complete when:

1. truthful `gate` and `benchmark` datasets exist
2. gold import is the documented source-of-truth ingestion path
3. both pipeline variants are runnable and comparable
4. the scorecard covers output quality and pipeline health
5. eval artifacts support regression root-cause analysis
6. the gate policy and threshold-ratification process are documented
7. active documentation reflects the final workflow
