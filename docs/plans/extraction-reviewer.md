# Plan: Standalone Extraction Reviewer

**Status:** MVP landed (all phases complete, validated end-to-end in a browser)

## Goal

Ship a single-file HTML tool that a non-developer reviewer can open locally to walk through the JSON output of our extraction pipeline (pre- or post-coding) and approve or flag each finding with free-text comments. The tool is delivered either as a zip containing `extraction_reviewer.html` + a `reports/` directory or as one embedded HTML produced by `pack.py`; the reviewer returns a zip of per-file review JSONs.

The starting point is the single-file review tool at `~/Repos/review_tool` (inbox + approve/flag/comment + localStorage + JSON download). The schema and item shape are finding-model specific; we swap those out for extraction-JSON shape and keep the interaction pattern.

## Non-goals

- No server, no build step for the reviewer, no external deps at runtime.
- No IDE-grade diff or inline editing of findings. Reviewers flag with a comment; we re-extract or hand-correct upstream.
- No coding UI beyond read-only display of the `coding` block when present.

## Workflow

1. Maintainer runs `uv run python extraction_reviewer/pack.py --reports path/to/extractions ...`.
2. `pack.py` rebuilds `extraction_reviewer.html` from `src/`, pairs JSON files with same-basename `.txt` / `.md` source reports when present, and emits either a zip bundle or embedded HTML.
3. Reviewer opens the HTML in a browser, picks the folder (or drag-drops the JSON files onto the landing area).
4. Reviewer walks the inbox, approves or flags with comments, adds missing-finding notes per report, exports a zip of per-file review JSONs.
5. Maintainer unzips and feeds back into eval/prompt improvement.

## Data model

### Input: extraction JSON

Matches `ExtractedReportFindings` in `src/finding_extractor/models.py`. Relevant fields:

- `exam_info` — `study_description`, `study_date`, `modality`, `body_region`, `body_part`, `contrast`, `laterality`
- `findings[]` — each:
  - `finding_name: str`
  - `presence: "present" | "absent" | "indeterminate" | "possible"`
  - `location: {body_region, specific_anatomy, laterality} | null`
  - `attributes: [{key, value}]`
  - `report_text: str` (verbatim quote)
  - `source_section: "findings" | "impression" | "both" | null`
  - `coding: FindingCodingBundle | null` — present after post-coding. Contains `finding_code` (status, oifm_id, oifm_name, method, reason, reasoning, candidates) and `location_codes[]`.
- `non_finding_text[]` — `{text, category}` where category ∈ metadata/technique/indication/comparison/clinical_history/impression/other

Pre-coded input omits `coding`; post-coded includes it. The UI renders the coding block only when present.

### Synthesized identifiers

Stable IDs for localStorage keying and for matching responses to source items.

- `source_id = sha1(file_content_bytes)[:12]` — stable across renames of the same file content
- `finding_id = ${source_id}-${finding_index}` — finding index is position in the `findings[]` array

### Output: per-file review JSON

One `<basename>.review.json` per input file, bundled into `reviews-<reviewer-slug>-<timestamp>.zip`.

```json
{
  "app_version": "1.0",
  "source_file": "chest_ct_001.json",
  "source_sha1": "abcdef123456",
  "source_exam": {
    "study_description": "CT Chest With Contrast",
    "study_date": "2024-07-10",
    "modality": "CT"
  },
  "reviewer": { "identifier": "jane.doe@example.org" },
  "exported_at": "2026-04-17T12:34:56.000Z",
  "summary": {
    "total_findings": 22,
    "approved": 19,
    "flagged": 3,
    "pending": 0,
    "missing_findings_count": 1
  },
  "responses": [
    {
      "finding_index": 0,
      "finding_name": "cardiomegaly",
      "presence": "absent",
      "status": "approved",
      "comment": "",
      "first_reviewed_at": "2026-04-17T12:20:10.000Z",
      "updated_at": "2026-04-17T12:20:10.000Z"
    },
    {
      "finding_index": 5,
      "finding_name": "pulmonary nodule",
      "presence": "absent",
      "status": "flagged",
      "comment": "Report says 'no definite nodule', but there's a 4 mm nodule described two paragraphs later. This finding should be 'present' not 'absent'.",
      "first_reviewed_at": "2026-04-17T12:21:02.000Z",
      "updated_at": "2026-04-17T12:21:30.000Z"
    }
  ],
  "report_level_notes": "",
  "missing_findings": [
    {
      "description": "Pleural effusion, left, small",
      "report_text": "There is a small left pleural effusion.",
      "added_at": "2026-04-17T12:22:00.000Z"
    }
  ]
}
```

`status` is one of `pending` / `approved` / `flagged`. `flagged` requires a non-empty comment (mirrors the review_tool's feedback flow).

## UI structure

### Landing screen (shown when no files loaded)

- Title: "Extraction Review"
- Reviewer identifier input (required to enable export)
- "Load folder" button (`<input type="file" webkitdirectory multiple>`), filtered to `.json`
- "Or drop JSON files here" drag-drop area
- Brief help text about the workflow and shortcuts

### Review screen (after files loaded)

**Sidebar (left column, grouped inbox)**

- Reviewer identifier at top (editable, shown always)
- Batch progress pills: remaining / approved / flagged / total
- Export zip button (disabled until reviewer id + at least one response)
- One group per source file, expandable, with per-file progress: `{filename} (12/22)`. Group header shows exam info (study_description + date).
- Inside each group: list of finding items, same shape as review_tool's list item (status dot, title=finding_name, meta=presence + location summary). A final entry per group: "+ Missing findings (n)" — clicking opens the missing-findings panel on the right.

**Main pane (right column)**

- When a finding is selected:
  - Header: finding_name (big), presence pill (color-coded), source_section badge
  - Quick facts grid: exam info (study_description, study_date, modality, body_part), location (body_region, specific_anatomy, laterality)
  - Verbatim quote block (prominent, quoted styling)
  - Attributes table (key → value)
  - Coding block (conditional): finding code row + location codes rows. Each row shows status chip, OIFM id + name, method, reasoning, and (collapsible) candidates list.
  - Review panel (sticky right side): status chip, comment textarea, Approve / Flag / Clear buttons. Enter sends flag; `A` approves; `F` focuses/sends flag. Same as review_tool.
- When "Missing findings" selected:
  - Panel with a list of existing missing-finding entries for the report (each: description, optional quote, remove button)
  - "Add missing finding" form: description (required), quote (optional paste), Add button
- "Report context" collapsible at the bottom of the finding view, showing `non_finding_text[]` stitched by category. Lets the reviewer scan surrounding text.

### Keyboard shortcuts

- `A` — approve current finding
- `F` — focus comment box; if already has text, send as flag
- `J` / `K` — previous / next finding within the current file
- `H` / `L` — previous / next file (jumps to first pending finding in that file)
- `Enter` in comment — send flag
- `Esc` in comment — blur

### State & persistence

- One localStorage key per source file: `extraction-reviewer:${source_sha1}` storing `{reviewer_id, responses_by_finding_id, missing_findings, report_notes, updated_at}`. Reviewer id is also mirrored to a top-level `extraction-reviewer:reviewer` key.
- Loading a folder merges saved state file-by-file by sha1 — reviewer can swap out unreviewed files without losing progress on reviewed ones.

## File layout

```
extraction_reviewer/
├── README.md                       # reviewer-facing usage + maintainer usage
├── REVIEWER_GUIDE.md               # embedded in the in-app Help dialog
├── build.py                        # emits a self-contained extraction_reviewer.html
├── pack.py                         # creates zip bundles or embedded HTML with report payloads
├── src/
│   ├── shell.html                   # main shell with __APP_VERSION__, __VENDOR_ZIP_JS__ placeholders
│   ├── styles.css
│   ├── landing.html
│   ├── app-shell.html
│   └── app.js
├── vendor/
│   └── fflate.min.js               # ~30KB tiny zip lib, MIT
├── docs/images/
│   ├── guide-overview.png
│   ├── guide-sidebar.png
│   └── guide-missing.png
└── samples/
    ├── xr_chest_20210614.extracted.json
    └── us_abdomen_20220208.coded.json
```

`build.py` reads `src/shell.html`, the source partials, `REVIEWER_GUIDE.md`, guide screenshots, and `vendor/fflate.min.js`, substitutes placeholders, and writes the output HTML. `pack.py` wraps that build step for reviewer handoff, optionally embedding a zip of reports into the HTML.

## Zip export

Use `fflate` (MIT-licensed, ~30KB minified). Stream each `.review.json` as a `Uint8Array` into `fflate.zipSync({...})`, wrap the returned bytes in a `Blob`, trigger a download named `reviews-${reviewer_slug}-${yyyymmdd-hhmm}.zip`.

Source files the reviewer didn't touch (no responses, no missing findings, no notes) are **skipped** in the export so the returned zip only contains genuine review output.

## Phased implementation

All six phases landed in a single pass — the tool is small enough that splitting implementation into discrete phased commits would have been more ceremony than value. Phase-by-phase status:

- **Phase 1** ✅ — Scaffolded `extraction_reviewer/` with `src/`, `vendor/fflate.min.js`, `samples/` (one pre-coded + one post-coded extraction generated from `sample_data/example2/`), and `build.py`.
- **Phase 2** ✅ — Sidebar grouped inbox + per-finding view + approve/flag/comment + per-file-sha1 `localStorage` resume.
- **Phase 3** ✅ — Coding block renderer; pre-coded and post-coded JSON render from the same template.
- **Phase 4** ✅ — Missing-findings panel per report with description + optional quote.
- **Phase 5** ✅ — Zip export via vendored `fflate`. Untouched files are skipped; touched files are emitted as `<basename>.review.json`.
- **Phase 6** ✅ — Shortcuts (A/F/J/K/H/L + Enter/Esc in comments), responsive layout, empty states, help text on landing, README with both maintainer and reviewer workflows.

### Refactor: src/ split at build time

Before the first build, we decided against keeping a single monolithic `template.html`. HTMX-style runtime loading was ruled out because `file://` origins block `fetch()` in every modern browser, which breaks the zero-setup reviewer workflow. Instead, we split the source into `src/shell.html`, `src/styles.css`, `src/landing.html`, `src/app-shell.html`, and `src/app.js`, each of which lives at native file-type so editors/formatters can treat them correctly. `build.py` concatenates via token substitution into one shippable HTML. Reviewer experience unchanged — they still get a single file.

One gotcha fixed during first build: placing `__APP_VERSION__` inside `window.__APP_VERSION__` collided with the placeholder token (both LHS and RHS got replaced, producing invalid JS). The global is now named `window.APP_VERSION` to avoid collision.

## Open risks

1. **`file://` origin quirks.** Some browsers restrict File System Access API on `file://`. Mitigation: don't use FSA; use plain `<input type=file webkitdirectory>` + drag-drop. Both work everywhere.
2. **Directory drag-drop inconsistency.** Dropping a folder requires `DataTransferItem.webkitGetAsEntry()` recursion, which is well-supported but fussy. Mitigation: support both individual-file drag-drop (the reliable path) and folder picker via `<input>`. Folder drag-drop is nice-to-have.
3. **localStorage size.** A folder of 100 reports × 20 findings × ~200 chars state each ≈ 400KB. Well under localStorage limits (5–10MB). Not a concern at normal scale.
4. **Schema drift.** If `ExtractedReportFindings` gains new fields, the reviewer won't display them until updated. Mitigation: renderer is defensive — unknown fields are ignored, missing fields fall back gracefully. Add a "raw JSON" collapsible per finding for reviewers to see anything the UI misses.

## Validation

Dogfooded end-to-end via a local HTTP server + Playwright:

- Loaded `samples/xr_chest_20210614.extracted.json` (30 pre-coded findings) and `samples/us_abdomen_20220208.coded.json` (35 post-coded findings, with resolved and unmapped `finding_code` entries and populated `location_codes`).
- Exercised approve (A key), flag-with-comment (Enter), missing-finding capture, and zip export.
- Inspected the exported zip: one `us_abdomen_20220208.coded.review.json`, untouched file correctly skipped, payload contained complete `responses[]` for all 35 findings + the missing-finding entry + correct summary counts.

## Documentation touchpoints

Per project convention:

- This plan doc (`docs/plans/extraction-reviewer.md`) is the source of truth during implementation; marked complete as phases landed.
- `extraction_reviewer/README.md` covers both maintainer (`python build.py`) and reviewer (open HTML, load folder, export zip) workflows.
- `extraction_reviewer/REVIEWER_GUIDE.md` is the reviewer-facing quick guide embedded in the Help dialog.
- `docs/DEV_LOG.md` entry added for the MVP land.
- No CHANGELOG entry — this is internal tooling, not a user-visible change.
