# Plan: Radiology Report Finding Extraction Agent

## Goal

Build a Pydantic AI agent that reads radiology report text and produces a structured `ReportExtraction` — a list of `ExtractedFinding` objects capturing what the report says, along with metadata about the exam itself. No tools in v1; pure structured extraction via LLM.

This is the **extraction phase only**. Downstream steps (OIFM code lookup, EFL/IPL generation) are future work.

## Architecture

```
Report text + exam context
        │
        ▼
┌────────────────────────────┐
│  Finding Extraction Agent   │  (Pydantic AI, no tools)
│                            │
│  Input:  report text       │
│  Output: ReportExtraction  │
└────────────────────────────┘
        │
        ▼
ReportExtraction
  ├── exam_info: ExamInfo
  ├── findings: list[ExtractedFinding]
  └── non_finding_text: list[NonFindingText]
```

## Project Structure

```
pyproject.toml
src/
  finding_extractor/
    __init__.py
    models.py              # ReportExtraction, ExtractedFinding, FindingLocation, FindingAttribute, etc.
    agent.py               # Pydantic AI agent definition, system prompt, few-shot examples
    examples.py            # Few-shot example loader (reads from sample_data/example2/)
    cli.py                 # CLI entry point
tests/
  __init__.py
  test_models.py
  test_extraction.py
  conftest.py
```

## pyproject.toml

- **Build system**: `uv`
- **requires-python**: `>=3.13`
- **Dependencies**: `pydantic-ai[openai]`, `pydantic>=2.0`, `click`
- **Dev group**: `pytest`, `pytest-asyncio`, `ruff`, `ty`
- **Entry point**: `finding-extractor = "finding_extractor.cli:main"`

## Data Models (`models.py`)

### `ExamInfo`

Metadata about the imaging exam this extraction came from.

```python
class ExamInfo(BaseModel):
    study_description: str          # "CT Abdomen and Pelvis WO contrast"
    study_date: str | None = None   # ISO date if known
    modality: str | None = None     # "CT", "XR", "MR", "US"
    body_part: str | None = None    # "abdomen", "chest", "brain", "shoulder"
```

### `FindingLocation`

Where the finding is occurring — **separate from other attributes** because location is often implied by the exam type rather than stated explicitly.

```python
class FindingLocation(BaseModel):
    body_region: str              # "chest", "abdomen", "pelvis", "head", "musculoskeletal"
    specific_anatomy: str | None  # "right lower lobe", "left kidney interpolar region", "T9"
    laterality: str | None        # "left", "right", "bilateral", None
```

- `body_region` may be inferred from exam type (CT abdomen → "abdomen")
- `specific_anatomy` captures finer detail from the report text
- `laterality` extracted when stated or implied

### `FindingAttribute`

Any descriptive property of a finding beyond presence and location. Flexible key-value structure.

```python
class FindingAttribute(BaseModel):
    key: str      # "size", "acuity", "change_from_prior", "severity", "count", "morphology"
    value: str    # "3 mm", "acute", "stable", "moderate", "2", "nonobstructing"
```

Standard attribute keys the agent should watch for:

- **size**: `"3 mm"`, `"4-5 mm"`, `"4.2 cm"`
- **acuity**: `"acute"`, `"chronic"`, `"healed"`, `"old"`
- **change_from_prior**: `"stable"`, `"unchanged"`, `"new"`, `"larger"`, `"increased"`, `"decreased"`, `"resolved"`, `"similar in size and number"`
- **severity**: `"mild"`, `"moderate"`, `"advanced"`
- **count**: `"2"`, `"multiple"`, `"bilateral"`
- **morphology**: `"nonobstructing"`, `"calcified"`, `"flowing osteophytes"`, `"focal"`

### `ExtractedFinding`

The core output model for each finding.

```python
class ExtractedFinding(BaseModel):
    finding_name: str                                              # Concise clinical term: "renal calculus", "hepatic steatosis"
    presence: Literal["present", "absent", "indeterminate", "possible"]
    location: FindingLocation | None
    attributes: list[FindingAttribute]
    report_text: str                                               # Verbatim quote from report
```

Key design points:

- `finding_name`: concise, reusable clinical term (not a sentence)
- **present/absent/indeterminate/possible**: "possible" covers hedged language like "raising the possibility of", "suggestive of", "cannot exclude"
- Both present and absent findings extracted ("no ascites" → ascites/absent)
- `report_text` must be a verbatim excerpt — quote, not paraphrase
- Multiple instances of same finding type → separate entries (e.g., right kidney stone and left kidney stone)

### Post-Extraction Validation

After the agent returns a `ReportExtraction`, run a validation pass:

- **Verbatim check**: Verify each `ExtractedFinding.report_text` is a substring of the original report. If not, flag it — the LLM paraphrased instead of quoting. This is the most common extraction failure mode.
- **Coverage check** (informational): Compare the union of all `report_text` + `non_finding_text.text` against the full report to surface any text the agent skipped entirely.

Implement as a `validate_extraction(report_text: str, result: ReportExtraction)` function that returns warnings/errors without blocking — the caller decides whether to retry or accept.

### `NonFindingText`

Segments of report text the agent identifies as not containing findings.

```python
class NonFindingText(BaseModel):
    text: str           # The verbatim text segment
    category: str       # "metadata", "technique", "indication", "comparison", "clinical_history", "other"
```

This lets us account for every piece of text in the report — findings go into `ExtractedFinding.report_text`, everything else goes here.

### `ReportExtraction`

Top-level output.

```python
class ReportExtraction(BaseModel):
    exam_info: ExamInfo
    findings: list[ExtractedFinding]
    non_finding_text: list[NonFindingText]
```

## Agent Definition (`agent.py`)

### Model Configuration

- **Default model**: `openai:gpt-5-mini` (via env var `FINDING_EXTRACTOR_MODEL`)
- **Step-up**: `openai:gpt-5.2` for higher accuracy
- **Step-down**: `openai:gpt-5-nano` for speed/cost
- **Reasoning effort**: Configurable via `FINDING_EXTRACTOR_REASONING` env var and `--reasoning` CLI flag. Passed to Pydantic AI as `openai_reasoning_effort` in `ModelSettings`.

**Reasoning effort values by model:**

| Model                  | Valid values                       | Default  |
| ---------------------- | ---------------------------------- | -------- |
| gpt-5-mini, gpt-5-nano | `minimal`, `low`, `medium`, `high` | `medium` |
| gpt-5.2                | `none`, `low`, `medium`, `high`    | `none`   |

```python
from pydantic_ai import ModelSettings

# Set at agent level (default for all runs)
agent = Agent('openai:gpt-5-mini', model_settings=ModelSettings(openai_reasoning_effort='medium'))

# Override per run
result = await agent.run(prompt, model_settings=ModelSettings(openai_reasoning_effort='high'))
```

Note: `minimal` disables parallel tool calls — not relevant for v1 (no tools), but worth knowing for future.

### Output Mode

Use Pydantic AI's default **Tool Output** mode for structured output. This uses function calling under the hood and is the most reliable across models. No need for `NativeOutput()` wrapping in v1.

### System Prompt

Instructs the agent to:

1. **Read the report systematically** — section by section
2. **Extract every finding** — present, absent, possible, and indeterminate
3. **Use concise clinical names** for `finding_name`
4. **Quote the report text exactly** — verbatim excerpts only
5. **Infer location from context** — exam type provides body_region when text doesn't state it explicitly
6. **Extract all relevant attributes** — especially `change_from_prior` (stable, unchanged, larger, new, resolved, etc.)
7. **Handle multiple instances** — separate findings for each distinct instance
8. **Classify non-finding text** — technique, indication, comparison, clinical history into `non_finding_text`
9. **Use "possible"** for hedged/uncertain language ("raising the possibility of", "suggestive of")

### Few-Shot Examples (`examples.py`)

Load curated input/output pairs from `sample_data/example2/` to include in the prompt:

- Read the `.md` report file as input
- Read the corresponding `_efl.json` as reference for expected findings (adapted to our `ExtractedFinding` format)
- **Exam-type matching** (stretch goal): select examples sharing the same modality as the input report (e.g., CT abdomen examples for a CT abdomen input)
- Fallback: use a default set of 1-2 diverse examples (one CT, one XR)

Curated example pairs to prepare:

1. `ct_abdomen_20210826.md` → hand-crafted `ReportExtraction` JSON (CT abdomen, mix of present/absent)
2. `xr_chest_20210614.md` → hand-crafted `ReportExtraction` JSON (XR chest, different modality)

These are stored as JSON files alongside the code or constructed in `examples.py`.

### Agent Invocation

```python
async def extract_findings(
    report_text: str,
    exam_description: str | None = None,
    model: str | None = None,
) -> ReportExtraction:
    """Run the extraction agent on a radiology report."""
    prompt = build_prompt(report_text, exam_description)
    result = await agent.run(prompt)
    return result.data
```

## CLI (`cli.py`)

```
Usage: finding-extractor <report_file> [OPTIONS]

Options:
  --exam-type TEXT      Exam description for context
  --output PATH         Output JSON file (default: stdout)
  --model TEXT          LLM model override (default: openai:gpt-5-mini)
  --reasoning TEXT      Reasoning effort: "minimal", "low", "medium" (default), "high"
  --format TEXT         Output: "json" (default) or "table" (summary)
```

## Implementation Steps

1. **Project scaffolding** — `uv init`, `pyproject.toml`, directory structure, `uv add` dependencies, configure ruff/pytest/ty
2. **Data models** — `models.py` with all Pydantic models
3. **Few-shot examples** — Hand-craft 2 `ReportExtraction` JSON examples from sample data
4. **Agent** — `agent.py` with system prompt, few-shot examples, structured output
5. **CLI** — `cli.py` with click
6. **Test against sample data** — Run on sample reports, inspect output quality
7. **Iterate on prompt** — Refine based on extraction quality

## Future Work (not in scope)

- **Finding model lookup tool**: `findingmodel.Index.search()` to match `finding_name` → OIFM codes
- **Location lookup tool**: Standardized anatomic location codes (via `anatomic-locations` package)
- **EFL generation**: Convert `ReportExtraction` → EFL JSON format
- **Interactive review**: Per-finding user confirmation/correction loop
- **IPL aggregation**: Feed confirmed EFLs into existing pipeline

## Key Reference Files

- `sample_data/example2/ct_abdomen_20210826.md` — CT abdomen report input
- `sample_data/example2/ct_abdomen_20210826_efl.json` — Reference findings for comparison
- `sample_data/example2/xr_chest_20210614.md` — Chest XR report input
- `sample_data/example2/xr_chest_20210614_efl.json` — Reference findings for comparison

## Verification

1. **Lint**: `uv run ruff check src/ tests/`
2. **Format**: `uv run ruff format src/ tests/`
3. **Type check**: `uv run ty check src/`
4. **Tests**: `uv run pytest tests/`
5. **Manual test**:
   ```bash
   uv run finding-extractor sample_data/example2/ct_abdomen_20210826.md \
     --exam-type "CT Abdomen and Pelvis WO contrast"
   ```
6. **Qualitative check**: Compare extracted findings against EFL JSON — the set of findings should be comparable even though names/codes won't match exactly

---

## Addendum: Review Fixes and 2026 Best-Practice Updates

This addendum captures specific steps to address the issues found in the initial implementation review.

### 1) Make validation enforceable (agent-level output validation)

**Problem:** `validate_extraction()` only runs after the model returns, so verbatim failures do not trigger retries.

**Steps:**

1. Add an `@agent.output_validator` in `src/finding_extractor/agent.py` that checks:
   - Each `finding.report_text` is a substring of the source report
   - Each `non_finding_text.text` is a substring of the source report
2. If any of the above checks fail, raise `ModelRetry` with a concise error message that includes:
   - the first failing snippet (truncated)
   - a reminder to quote verbatim from the report
3. Keep the existing `validate_extraction()` for optional post-run diagnostics and coverage warnings.
4. Add a test in `tests/test_extraction.py` asserting that the output validator raises retry on a paraphrased quote.

### 2) Update reasoning settings for GPT-5 family

**Problem:** The implementation uses `OpenAIChatModelSettings`; GPT-5 family is primarily documented under Responses settings, and `none` is missing from the CLI choices for GPT-5.2.

**Steps:**

1. Switch model settings to `OpenAIResponsesModelSettings` in `src/finding_extractor/agent.py` for GPT-5.\* models.
   - Keep a compatibility path for non-Responses models if needed.
2. Extend the CLI `--reasoning` choices to include `none` and allow per-model validation.
3. Add a validation layer in `_get_model_settings()` that:
   - checks the requested reasoning value against the model's allowed set
   - raises a clear `ValueError` (or CLI error) if an invalid combination is provided
4. Update docstrings and README notes to reflect the default reasoning values per model and supported options.

### 3) Tighten schema with enums and strictness

**Problem:** Many key fields are free-form strings; this weakens schema enforcement and output validation.

**Steps:**

1. Convert the following fields to `Literal` or `StrEnum`:
   - `NonFindingText.category`
   - `FindingLocation.body_region`
   - `FindingLocation.laterality`
   - Optionally `FindingAttribute.key`
2. Add `model_config = ConfigDict(extra="forbid")` to all Pydantic models in `src/finding_extractor/models.py` to reject unknown fields.
3. Add tests in `tests/test_models.py` for:
   - invalid category
   - invalid body region
   - unexpected extra fields
4. Update instructions in `src/finding_extractor/agent.py` to explicitly list valid enum values and note that any other values will fail validation.

### 4) Fix category mismatch (add impression to schema and instructions)

**Problem:** The instructions/examples use `impression`, but the schema doesn't list it.

**Steps:**

1. Add `"impression"` to the allowed `NonFindingText.category` enum.
2. Update the model docstring and system prompt to include `impression` in the category list.
3. Add a test case in `tests/test_models.py` to assert `impression` is accepted.

### 5) Replace embedded examples with file-backed examples

**Problem:** `examples.py` embeds reports and outputs, diverging from the plan and making maintenance harder.

**Steps:**

1. Move the current example JSON outputs into `sample_data/example2/` as dedicated files (e.g., `ct_abdomen_20210826_extraction.json`).
2. Update `src/finding_extractor/examples.py` to:
   - read report `.md` files from `sample_data/example2/`
   - read the corresponding extraction JSON files
   - construct `ReportExtraction` from JSON
3. Add a small loader test that asserts the example files can be loaded and parsed.
4. Keep a fallback to a minimal in-code example only if file reads fail (for development resilience).

### 6) Improve date handling in ExamInfo

**Problem:** `study_date` is a `str`; schema does not enforce ISO formatting.

**Steps:**

1. Change `study_date: date | None` in `ExamInfo`.
2. Ensure JSON serialization uses ISO dates (Pydantic defaults are fine).
3. Update examples and tests to pass `date(YYYY, MM, DD)` or ISO strings (if using `field_serializer`).

### 7) Add explicit model-compatibility notes

**Problem:** Reasoning and output settings differ per model family; the code should document supported models clearly.

**Steps:**

1. Add a short section in `README.md` describing supported model IDs and their reasoning-effort options.
2. Document that Tool Output is the default structured output mode per Pydantic AI (with a link to the docs).
3. Note when to prefer Responses models for GPT-5 family.
