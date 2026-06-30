# Evaluation Harness — Developer Guide

## Architecture

```
finding-extractor-eval run --dataset smoke
         │
         ▼
    cli/eval_cmd.py      CLI entry point (Click)
         │
         ▼
    eval/runner.py       Run engine (load dataset, run, persist, check thresholds)
         │
    ┌────┼────────────────────────┐
    │    ▼                        │
    │  eval/datasets.py           │  Dataset loading (YAML → pydantic-evals Dataset)
    │    │                        │
    │    ▼                        │
    │  eval/evaluators.py         │  6 custom Evaluator subclasses
    │    │                        │
    │    ▼                        │
    │  eval/matching.py           │  Jaccard-based finding matcher
    │    │                        │
    │    ▼                        │
    │  eval/task.py               │  Task adapter (EvalInput → ExtractedReportFindings)
    │    │                        │
    │    ▼                        │
    │  extraction_runtime.run_extraction_runtime() │  Shared orchestrated extraction runtime
    └─────────────────────────────┘
```

## Module Map

| Module | Purpose |
|--------|---------|
| `eval/__init__.py` | Re-exports public names |
| `eval/models.py` | `EvalInput`, `EvalMetadata`, `EvalRunConfig` |
| `eval/matching.py` | Greedy best-match finding alignment |
| `eval/evaluators.py` | 6 scoring evaluators |
| `eval/task.py` | `make_eval_task()` — wraps `run_extraction_runtime()` for pydantic-evals |
| `eval/datasets.py` | `load_dataset()`, `build_smoke_dataset()`, `import_baseline_cases()`, `save_dataset()` |
| `eval/runner.py` | `run_eval()` — orchestrates load → evaluate → persist → threshold check |
| `eval/reporting.py` | `load_report()`, `load_run_results()`, `find_latest_run()`, `display_report()`, `display_comparison()`, `display_case_detail()`, `print_legacy_summary()` |
| `cli/eval_cmd.py` | Click CLI entry point (`run`, `import-baseline`, `report` subcommands) |

## Finding Matching Algorithm (`matching.py`)

The matching algorithm aligns expected findings (ground truth) to actual findings (extractor output) before evaluators score individual dimensions.

### Steps

1. **Tokenize** each finding: regex word extraction (`\w+`) on `finding_name` + `report_text` → `set[str]`. Strips punctuation (`"kidney."` → `"kidney"`, `"4–5 mm"` → `{"4", "5", "mm"}`).
2. **Compute pairwise Jaccard similarity** between all expected × actual token sets.
3. **Apply bonuses** (tiebreakers for same-name findings):
   - **Presence bonus** (+0.1): when `expected.presence == actual.presence`.
   - **Location bonus** (up to +0.15): +0.05 matching `body_region`, +0.05 matching `laterality`, +0.05 × anatomy token overlap for `specific_anatomy`.
   - **Attribute bonus** (up to +0.03): scaled by key-value pair overlap ratio between expected and actual attributes.
4. **Greedy best-match**: sort all pairs by similarity descending, greedily assign pairs (each finding matched at most once).
5. **Threshold filter**: only pairs with similarity ≥ threshold (default 0.3) are considered.

### Bonus Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `_PRESENCE_BONUS` | 0.10 | Same presence status |
| `_BODY_REGION_BONUS` | 0.05 | Same body region |
| `_LATERALITY_BONUS` | 0.05 | Same laterality (when both specify) |
| `_ANATOMY_BONUS` | 0.05 | Specific anatomy token overlap (scaled) |
| `_ATTRIBUTE_BONUS` | 0.03 | Attribute key-value pair overlap (scaled) |

Max total bonus: 0.28 (presence + location + attributes). The default threshold (0.3) is unchanged — bonuses are tiebreakers that disambiguate findings with identical text similarity.

### Output

`MatchResult` contains:
- `matches` — aligned `(expected, actual, similarity)` triples
- `unmatched_expected` — false negatives (ground truth not matched)
- `unmatched_actual` — false positives (extractor output not matched)

### Design Decisions

- **No external NLP dependencies**: tokenization uses regex word extraction, keeping the eval fast and deterministic.
- **0.3 threshold**: tuned to allow fuzzy matches (e.g., "renal calculus" vs "renal stone") while rejecting unrelated findings.
- **Presence bonus**: prevents matching a "present" finding against an "absent" finding with the same name when a better option exists.
- **Location + attribute bonuses**: disambiguate duplicate-name findings that share identical `report_text` (e.g., bilateral renal calculi, multi-level spinal changes). Without these bonuses, Jaccard scores are identical and pairing is random, cascading errors into Location, Attribute, and Presence evaluators.

### Known Limitation: Circular Scoring

The matcher uses location and attribute fields to bias pairing, then the `LocationEvaluator` and `AttributeEvaluator` score those same fields on the paired findings. This creates a feedback loop: the matcher prefers right↔right pairing, and the evaluator then rewards matching laterality — because we biased the match.

This is the **correct trade-off**. Without the bonuses, random pairing causes artificial *under*-scoring: the extractor produces correct laterality for both stones, but the matcher pairs right↔left, and the evaluator reports wrong laterality. The bonuses eliminate this false-negative noise.

The blind spot: if the extractor *swaps* lateralities on both findings in a complementary way (right stone labeled left, left stone labeled right), the matcher would still pair them "correctly" by laterality and the evaluator wouldn't catch the swap. In practice this is extremely unlikely — it requires two independent errors that happen to cancel each other out. If this becomes a concern, a future cross-validation evaluator could detect it by checking whether matched pairs' locations are internally consistent with each other.

The same circular dynamic applies to attributes (the matcher uses attribute overlap for pairing, then the `AttributeEvaluator` scores attribute keys on the paired findings). The reasoning is identical: correct pairing on matching attributes eliminates far more false-negative noise than false-positive noise it could mask.

## Evaluator Design (`evaluators.py`)

All evaluators are `@dataclass` classes inheriting from `pydantic_evals.evaluators.Evaluator[EvalInput, ExtractedReportFindings]`. They implement `evaluate(ctx) -> dict[str, ...]` returning scores (float), assertions (bool), or `EvaluationReason` (value + diagnostic reason).

### Evaluator Summary

| Evaluator | Metrics | Notes |
|-----------|---------|-------|
| `FindingDetectionEvaluator` | `finding_precision`, `finding_recall`, `finding_f1` | `finding_f1` returns `EvaluationReason` with match/FP/FN counts. |
| `PresenceClassificationEvaluator` | `presence_accuracy` | Returns `EvaluationReason` with "N/M correct". Only scores matched findings. |
| `LocationEvaluator` | `body_region_accuracy`, `laterality_accuracy` | Both return `EvaluationReason` with "N/M correct". Laterality only evaluated when expected has laterality. |
| `AttributeEvaluator` | `attribute_precision`, `attribute_recall` | Both return `EvaluationReason` with "N/M matched". Attribute keys compared (not values). |
| `VerbatimQuoteEvaluator` | `verbatim_pass` (bool assertion), `verbatim_rate` (float score) | `verbatim_pass` is a bool → routes to `case.assertions`. Returns `EvaluationReason` with verbatim counts. |
| `NonFindingClassificationEvaluator` | `nonfinding_category_accuracy` | Uses `tokenize()`/`jaccard_similarity()` from `matching.py`. |

### Shared Utilities

- **`tokenize()` / `jaccard_similarity()`**: Public functions in `matching.py`, reused by `NonFindingClassificationEvaluator` for non-finding text matching (replaces inline Jaccard calculation).

### Inline Pattern

All four finding-based evaluators (`FindingDetection`, `PresenceClassification`, `Location`, `Attribute`) follow a consistent inline pattern:
1. Read `ctx.expected_output` and `ctx.output`
2. Return default zeros if expected is `None`
3. Call `match_findings(expected.findings, actual.findings, threshold=self.threshold)`
4. Score the dimension from the match result

This pattern was kept inline rather than extracted into a shared helper because the per-evaluator default dicts differ, the inline code is clear and type-safe, and the duplication is minimal (3 lines per evaluator).

### Bool Assertions vs Float Scores

pydantic-evals routes evaluator return values by type:
- **`bool`** values → `case.assertions` (pass/fail semantics, shown as checkmarks in reports)
- **`float`/`int`** values → `case.scores` (continuous metrics, averaged in reports)
- **`EvaluationReason`** wraps either type with a diagnostic `reason` string

`verbatim_pass` returns `bool` via `EvaluationReason(value=True/False, reason=...)`, so it appears in assertions. `verbatim_rate` stays as a float score.

The runner's `_extract_averages()` computes per-assertion pass rates from per-case data and merges them into the averages dict alongside scores, so threshold checking works uniformly for both.

### Edge Case Handling

- **No expected output**: all evaluators return 0.0 (except VerbatimQuoteEvaluator, which doesn't need expected output).
- **Both empty**: detection returns 1.0 (nothing to detect, nothing missed). Presence and non-finding return 1.0.
- **No matches but expected non-empty**: presence returns 0.0 (all missed).

## Baseline Import Flow (`datasets.py`)

`import_baseline_cases()` converts batch extraction output into ground truth eval cases:

1. Scan `source_dir` for report files matching the glob pattern.
2. For each report, find the corresponding extraction file (stem + output_suffix).
3. Load the extraction JSON and strip `_validation` and `_storage` keys (added by batch CLI, not part of ExtractedReportFindings schema).
4. Optionally filter by model (check `_storage.model` before stripping).
5. Validate as `ExtractedReportFindings` via `model_validate()`.
6. Infer metadata: `modality` and `body_region` from `exam_info` fields.
7. Generate case name from filename stem.
8. Skip files with missing extraction or parse/validation errors (log warning).

The CLI's `import-baseline` command handles append/overwrite logic and deduplicates by case name (new cases override existing ones with the same name).

## Reporting Module (`reporting.py`)

The reporting module delegates all display to pydantic-evals' native `EvaluationReport.print()` Rich output. Reports are loaded from `report.json` (persisted by the runner).

### Functions

| Function | Purpose |
|----------|---------|
| `load_report(run_dir, run_id)` | Load `report.json` via `EvaluationReportAdapter.validate_python()`. Returns `None` for legacy runs. |
| `display_report(report)` | Single-run table via `report.print(include_reasons=True)`. |
| `display_comparison(primary, compare)` | Diff-mode table showing change from primary to compare. |
| `display_case_detail(primary, case_name, compare?)` | Filters report to matching case, prints with optional comparison. Raises `ClickException` if case not found. |
| `print_legacy_summary(results)` | Minimal averages table for old runs without `report.json`, with note to re-run. |
| `load_run_results(run_dir, run_id)` | Load `results.json` (still used for threshold checking and legacy fallback). |
| `find_latest_run(run_dir)` | Scans for subdirectories containing `report.json` or `results.json`, returns most recent by mtime. |

## Dataset Format

Datasets are YAML files using the pydantic-evals `Dataset.to_file()` format:

```yaml
cases:
- name: ct_abdomen_pelvis
  inputs:
    report_text: "History: flank pain..."
    study_description: null
  metadata:
    source_file: examples.py
    modality: CT
    body_region: abdomen
  expected_output:
    exam_info:
      study_description: CT Abdomen and Pelvis WO contrast
    findings:
    - finding_name: renal calculus
      presence: present
      location:
        body_region: abdomen
        specific_anatomy: right lower pole
        laterality: right
      attributes:
      - key: size
        value: 3 mm
      report_text: "Stable bilateral renal stones..."
    non_finding_text:
    - text: "History: flank pain, h/o stones"
      category: clinical_history
  evaluators: []
evaluators: []
```

Key points:
- `expected_output` uses the native `ExtractedReportFindings` format (same as extraction output).
- `metadata` fields are optional; used for filtering and reporting.
- Per-case `evaluators` can override the dataset-level evaluators (empty = use dataset defaults).
- Two dataset tiers: `smoke` (2 cases, CI gate) and `comprehensive` (10 cases, full diversity).

## Runner Architecture (`runner.py`)

The run engine follows the current batch split: `cli/batch.py` owns the Click entry point, while `cli/batch_engine.py` owns the reusable run engine.

1. **Load dataset** via `load_dataset()`.
2. **Attach evaluators** (all 6) to the dataset.
3. **Create task function** via `make_eval_task(model, reasoning, timeout)`.
4. **Build retry config** via `_build_retry_config(retries)` — returns a `RetryConfig` (tenacity `stop_after_attempt` + `wait_exponential`) or `None` when retries=0.
5. **Execute** via `dataset.evaluate(task_fn, max_concurrency=workers, retry_task=retry_task)`.
6. **Print report** with `include_reasons=True` for richer console output during eval runs.
7. **Persist native report** via `_save_report()` — serializes `EvaluationReport` to `report.json` using `EvaluationReportAdapter.dump_python(mode="json")` with inputs/outputs nulled. Sets `experiment_metadata` (model, dataset, reasoning, duration, thresholds) on the serialized dict, not the live report object.
8. **Extract averages** — `_extract_averages()` reads `report.averages().scores` for float metrics and computes per-assertion pass rates from per-case `case.assertions` data (since `report.averages().assertions` is a single aggregate float, not a per-metric dict).
9. **Persist results** to `{run_dir}/{run_id}/`:
   - `run_config.json` — frozen configuration (includes `retries`)
   - `report.json` — native `EvaluationReport` (Rich display source for `report` command)
   - `results.json` — averages + per-case scores + diagnostic reasons + metadata
   - `results.jsonl` — one line per case (with reasons)
10. **Check thresholds** and return exit code.

### Reason Persistence

`_extract_per_case_results()` captures `EvaluationResult.reason` from each score and assertion into `score_reasons` and `assertion_reasons` dicts. These are only included when non-empty (additive schema change — old results without these keys are handled gracefully). The live console output during `report.print()` also shows reasons via `include_reasons=True`.

Concurrency is handled by pydantic-evals' built-in `max_concurrency` parameter (no custom worker pool needed). Retries use pydantic-evals' native `retry_task` parameter backed by tenacity.

## CLI Architecture (`cli/eval_cmd.py`)

- Click group with three subcommands: `run`, `import-baseline`, `report`.
- `run`: Uses `asyncer.runnify()` to bridge the async `run_eval()` to synchronous Click.
- `import-baseline`: Synchronous — calls `import_baseline_cases()`, handles append/overwrite, saves via `save_dataset()`.
- `report`: Synchronous — loads `report.json` via `load_report()` and routes to `display_report()`, `display_comparison()`, or `display_case_detail()` based on `--case` and `--compare` flags. Falls back to `print_legacy_summary()` for old runs without `report.json`.
- Calls `configure_logfire(runtime="cli")` + `setup_logging()` at startup (run subcommand only).
- Runner uses `structlog.get_logger()` for structured logging output.
- Settings resolution: CLI flags > config settings > defaults.
- Model and reasoning validation happens before the run starts.
- Threshold flags are optional; when set, the CLI exits non-zero if any threshold fails.

## Test Coverage

| Test File | Coverage |
|-----------|----------|
| `tests/test_eval_matching.py` | Tokenization, Jaccard similarity, match_findings edge cases, location/attribute bonus disambiguation, self-match diagnostics against comprehensive dataset, integration with examples |
| `tests/test_eval_evaluators.py` | All 6 evaluators with mock context, integration with CT abdomen example |
| Eval CLI tests | CLI help, run/import-baseline/report with mocked runner, threshold logic, dataset loading |
| `tests/test_eval_datasets.py` | `import_baseline_cases()` edge cases, `save_dataset()`, round-trip load |

Tests use a `FakeEvaluatorContext` dataclass that stands in for pydantic-evals' `EvaluatorContext`, allowing unit testing of evaluator logic without running the full framework.

## Adding a New Evaluator

1. Create a `@dataclass` class in `evaluators.py` inheriting from `Evaluator[EvalInput, ExtractedReportFindings]`.
2. Implement `evaluate(ctx) -> dict[str, float]` returning named metrics.
3. Add the evaluator to the list in `runner.py:run_eval()`.
4. Add tests in `test_eval_evaluators.py`.
5. If threshold support is needed, add a CLI flag in `cli/eval_cmd.py` and wire it into the thresholds dict.

## Adding a New Dataset

1. Create a YAML file in `evals/datasets/` following the format above.
2. Run it: `finding-extractor-eval run --dataset your_dataset_name`
3. Or build programmatically using pydantic-evals' `Dataset` API:

```python
from pydantic_evals import Case, Dataset
from finding_extractor.eval.models import EvalInput, EvalMetadata
from finding_extractor.models import ExtractedReportFindings

dataset = Dataset(cases=[
    Case(
        name="my_case",
        inputs=EvalInput(report_text="..."),
        expected_output=ExtractedReportFindings(...),
        metadata=EvalMetadata(modality="CT", body_region="chest"),
    ),
])
dataset.to_file("evals/datasets/my_dataset.yaml")
```
