# Plan: Add anatomic-location codes to example2 EFLs and an anatomy-aware IPL

> **Status: COMPLETE (2026-06-10).** EFLs in `sample_data/example2` enriched with
> `anatomicLocation` via `scripts/enrich_efl_anatomy.py` (260/275 localized; review CSV at
> `extracts/anatomy_enrichment_review.csv`); `scripts/generate_ipl_from_efls.py` regroups by
> `(findingCode, locationId)` and the example2 IPL was overwritten in place (131 entries);
> tests in `tests/test_generate_ipl.py`; docs updated. **Follow-on:** Step 3b anatomic-compatibility
> reconciliation and the fresh anatomy-aware viewer remain future phases.

## Context

The extracted Observations in `sample_data/example2/` carry a finding code and a presence attribute
but **no anatomic location**. We want each observation to indicate *where* the finding is, encoded
with the standard anatomic-location codes from the `anatomic-locations` package (the RID-based system
backed by `~/Library/Application Support/anatomic-locations/anatomic_locations.duckdb`).

This is the data foundation for a larger goal: an **IPL that groups findings by finding type *and*
anatomy**, and a fresh viewer built to exploit that richer structure. This plan covers the data work
(EFL enrichment + anatomy-aware IPL). The new viewer is a separate later phase.

### Decisions locked in (from user)
- **Indicator shape:** RID id + display name only — `{"locationId": "RID…", "locationDisplay": "…"}`,
  a single location per observation. (The `anatomic-locations` RID *is* the standard code; crosswalk
  codes like SNOMED/ACR live in the DB and can be looked up on demand.)
- **Population method:** LLM-assisted + index lookup.
- **Reach:** Enrich the example2 EFLs and **overwrite** the example2 IPL in place with anatomy-aware
  grouping. No v2 files. Leave `viewer/data/` alone — the current viewer reads its own processed copy,
  and a fresh viewer is coming anyway.

### Reuse the production coding pipeline
The repo **already has the exact location-coding flow we need**, designed to work even when a finding
has no pre-extracted location:
- `run_coding(...)` (public entrypoint, `src/finding_extractor/coding/runtime.py:248`, exported from
  `src/finding_extractor/coding/__init__.py`) runs term-generation → `AnatomicLocationIndex` search →
  candidate selection, then attaches `FindingCodingBundle.location_codes` to each `Finding`.
- `LOCATION_TERM_SYSTEM` (`coding/prompt.py:88`) rule 3 explicitly says: *"If location is null, infer
  from the exam info and report context."* `build_location_term_user_prompt` already prints `(none)`
  for missing location fields and includes `report_text`. The selector prompt
  (`LOCATION_CODE_SELECTOR_SYSTEM`, `coding/prompt.py:173`) likewise infers location from report text
  and exam type, and states presence does not affect coding.

Reusing `run_coding` rather than a one-off prompt resolves the plan-review findings directly:
- **No hand-rolled prompt** — production term + selector prompts unchanged.
- **No `sided_filter`/top-hit shortcut** — selection comes from a candidate set chosen by the selector
  agent and validated against retrieved candidates (the review's biggest concern; e.g.
  `lower lobe of right lung` = `RID1315` is `NONLATERAL`, so a sided filter would wrongly drop it).
- **Absent findings still get anatomy** — presence doesn't gate location ("No hydronephrosis" → kidney,
  "adrenal glands are unremarkable" → adrenal). Only genuine `location_unknown` is skipped.
- **Within-report dedupe** — `run_coding` groups by `_location_group_key`, so repeated observations are
  coded once; cross-report exam context is preserved (each EFL coded separately).

### Grounding facts
- example2 EFLs were produced by `scripts/generate_efl_from_excel.py` from `findings_with_oifm_ids.xlsx`.
  There is **no Pydantic model or committed JSON schema** for the EFL format, so adding a field is
  purely additive. We do **not** modify that generator (out of scope).
- `AnatomicLocationIndex.search` is async; verified resolutions: "right lower pole of kidney" →
  `RID29662` (right kidney); "T9 vertebral body" → `RID7766`; "right lower lobe of lung" → `RID1315`.
- `viewer/data/` holds the current viewer's own processed copies; it is **not** touched by this plan.

## EFL field shape (additive, optional)

Each finding entry gains an optional `anatomicLocation`; non-localizable findings omit it.

```json
{
  "observationId": "renal_calculus_1",
  "findingCode": "OIFM_GMTS_020556",
  "findingDescription": "radiodense urinary calculus",
  "attributes": [ ... ],
  "anatomicLocation": { "locationId": "RID29662", "locationDisplay": "right kidney" },
  "reportText": "Bilateral nonobstructive renal calculi. Largest in right lower pole measures 3 mm."
}
```

If `run_coding` returns multiple `location_codes` for an observation, take the first/primary coded one
to honor the single-location decision (log the rest in the review CSV).

## Step 0 — Write this plan into the repo

Copy this plan to `docs/plans/anatomic-location-efl-ipl.md` so it lives with the code.

## Step 1 — Enrichment script: `scripts/enrich_efl_anatomy.py`

A one-off, idempotent pass over `sample_data/example2/*_efl.json` that reuses the production coding flow.

For each EFL file:
1. Build an `ExtractedReportFindings`:
   - `exam_info`: `ExamInfo(study_description=examInfo.studyDescription, ...)` (map modality/body_part
     where derivable; prompts tolerate `(unknown)`).
   - one `Finding` per EFL entry: `finding_name=findingDescription`, `presence` from the presence
     attribute, `report_text=reportText`, `location=None`.
2. `result = await run_coding(extraction, ...)` with a coding-capable model configured via
   `core/config.py` (`IPL_*`).
3. For each finding, read `finding.coding.location_codes`; take the first `status=="coded"` entry and
   write `anatomicLocation = {"locationId": code.location_id, "locationDisplay": code.location_name}`
   into the matching EFL entry (preserve key order; insert before `reportText`). Skip when unmapped.
4. Write JSON back to the same `sample_data/example2/*_efl.json` file (additive; idempotent).
5. Emit a **review CSV** `extracts/anatomy_enrichment_review.csv`: EFL file, `diagnosticReportId`,
   `observationId`, `findingDescription`, `presence`, `reportText`, selected RID, selected display,
   method, unresolved reason, candidate RID/display list — sourced from the `LocationCode` fields.

Notes: drive with `asyncio`; one `run_coding` call per file; no separate cache (`run_coding` dedupes
per report). Harvest only `location_codes`; optionally assert recomputed finding code matches the EFL's
existing `findingCode` and log to CSV.

## Step 2 — Run + review

`uv run python scripts/enrich_efl_anatomy.py sample_data/example2`. Review the CSV; spot-check anchors:
right-lower-pole calculus → `RID29662`; left-kidney cysts → `RID29663`; T9 fracture → `RID7766`;
RLL nodule/pneumonia → `RID1315`. Confirm `unresolved` rows are genuinely non-localizable
(e.g. generalized osteoporosis) and that **absent** findings still received a location.

## Step 3 — Anatomy-aware IPL (overwrite in place)

Update `scripts/generate_ipl_from_efls.py` so its output groups by finding **and** anatomy, and
regenerate `sample_data/example2/MRN0000001_ipl.json` in place (overwrite — no v2):
- **Group key = `(findingCode, locationId)`** instead of `findingCode` alone
  (`scripts/generate_ipl_from_efls.py:40-44, 87-107`). Entries without `anatomicLocation` group under
  `(findingCode, None)`.
- Each IPL finding gains an `anatomicLocation` object (null when none) and keeps a stable `id`; since
  one finding code can now appear at multiple locations, downstream consumers key on `finding.id`, not
  `finding_type_code`.
- Carry per-observation `anatomicLocation` onto each observation dict (`:94-105`).

Resulting IPL finding entry:
```json
{
  "id": "ipl-finding-044a",
  "finding_type_code": "OIFM_GMTS_020556",
  "finding_type_display": "radiodense urinary calculus",
  "anatomicLocation": { "locationId": "RID29662", "locationDisplay": "right kidney" },
  "observations": [ { ..., "anatomicLocation": { "locationId": "RID29662", "locationDisplay": "right kidney" } } ]
}
```

### Possible Step 3b — anatomic compatibility reconciliation (flag for later)

Grouping by `(findingCode, locationId)` is a first cut, but it doesn't fully answer the clinical
question: for a finding type that recurs across exams, are two observations the **same** problem or
necessarily **distinct** ones? Two cases the naive key gets wrong:
- **False split:** one observation codes to a specific location (`left kidney`, `RID29663`) and another
  to the generic parent (`kidney`, `RID205`) because the report didn't state a side — these *could* be
  the same problem and arguably should merge, but distinct `locationId`s put them in separate groups.
- **Forced merge / under-split:** two observations share a `locationId` but the descriptions imply
  distinct lesions (e.g. two separate renal cysts in the same kidney) — at least two findings.

So we may need a reconciliation pass that, for observations sharing a finding code, judges whether their
locations/descriptions are anatomically **compatible** (could be one finding) or **incompatible** (must
be ≥2): exploit the `anatomic-locations` containment hierarchy (parent/child RIDs are compatible;
left vs. right are not) plus, where ambiguous, an LLM judgment over the descriptions. This is noted as a
**potential follow-on step**, scoped after we see the first-cut grouping output — not committed in this
plan.

## Step 4 — Tests + docs

- Add focused tests: anatomy-aware grouping splits one finding code into per-location entries (e.g.
  lymphadenopathy abdominal vs. hilar) while same-location series stay merged; all generated JSON
  parses; IPL `id`s are unique and observations carry `anatomicLocation`. Follow
  `docs/testing-practices.md` / `pytest-testing-patterns`.
- Document the EFL `anatomicLocation` field and the anatomy-aware IPL grouping (`README.md` /
  `CLAUDE.md` Domain Model and `docs/`); add a `docs/DEV_LOG.md` entry.
- Mark `docs/plans/anatomic-location-efl-ipl.md` complete; note the fresh viewer as the follow-on phase.

## Out of scope (this plan)
- The fresh viewer / extractor-ui display changes (later phase).
- The `generate_efl_from_excel.py` Excel→EFL generator and everything under `viewer/data/`.

## Critical files
- `scripts/enrich_efl_anatomy.py` — **new**; builds `ExtractedReportFindings` from EFLs and calls
  `run_coding`, harvesting `location_codes`.
- Reuse: `run_coding` (`coding/__init__.py`, `coding/runtime.py:248`); `Finding`/`ExtractedReportFindings`/
  `ExamInfo`/`LocationCode` (`src/finding_extractor/models.py`); `core/config.py` model settings.
- `scripts/generate_ipl_from_efls.py` — regroup by `(findingCode, locationId)`; overwrite the IPL.
- Output (overwritten/enriched in place): `sample_data/example2/*_efl.json`,
  `sample_data/example2/MRN0000001_ipl.json`, `extracts/anatomy_enrichment_review.csv`.

## Verification
1. `uv run python scripts/enrich_efl_anatomy.py sample_data/example2` succeeds; review CSV shows a sane
   localized/unresolved split and correct RIDs for the anchor cases; absent findings are localized.
2. All EFL/IPL JSON still parses:
   `uv run python -c "import json,glob; [json.load(open(f)) for f in glob.glob('sample_data/example2/*.json')]"`.
3. `git status` shows changes confined to `sample_data/example2/` + new script/CSV — **no** edits under
   `viewer/data/`.
4. Regenerate the IPL; confirm a multi-location finding type (lymphadenopathy: abdominal vs. hilar)
   splits into separate anatomy groups, while a single-location series (ascending-aorta aneurysm) stays
   merged.
5. Run the test suite (`task --list` → unit target) to confirm nothing reading these sample files regressed.
