# Plan: CSV-Aware Extraction Reviewer

Created: 2026-07-14
Status: In progress (Phase 1 complete; Phase 2 next)

## Goal

Ship **one self-contained HTML file** a non-developer colleague can open in a browser to collect
human feedback on **already-extracted** data:

1. **Input:** the original source CSV + a directory of existing extraction JSON files.
2. **Activity:** human review of the extracted findings (approve / flag / missing / notes).
3. **Output:** one combined review JSON to send back.

A static, offline, browser-only page. This is Phase C item 2 of
[extraction-reviewer-workflows.md](extraction-reviewer-workflows.md).

## Scope boundary (important)

In scope: a standalone review tool that consumes a CSV + existing extraction JSONs and emits one
review JSON. Client-side HTML only — no `fetch()`, no server, no runtime dependency on Python or
any model.

**Out of scope** (do not touch as part of this workstream): running extraction, Windows
extraction packaging (`run.ps1`, `build_windows_csv_handoff.py`), model configuration and
model-selection, evals, gold datasets, and adjudication pipelines. How the extraction JSONs were
produced is irrelevant here — the tool consumes them wherever they came from. Testing uses
**representative fixtures**, not the live extraction tool.

## Decisions (2026-07-14; source-text precedence amended 2026-07-19)

- **Deliverable is the standalone reviewer HTML**, handed over on its own.
- **Primary workflow is a guided 3-step wizard** (CSV → results dir → confirm), replacing the
  ad-hoc drag-a-folder loading for the CSV path. Direct file/paired-text loading is retained as
  **compatibility behavior**.
- **The CSV supplies each report's join identity** (and text-of-last-resort); **the staged report
  text (`_staged_reports/`) is the primary source text**, because extraction quotes are verbatim
  against it, not the raw CSV cell (see "Source text and normalization" below).
- **Batches persist browser-locally, keyed by a SHA-256 of the CSV**, so the reviewer can close
  and reopen the page and resume without reselecting files.
- **Combined JSON export** is authoritative: every loaded report, every loaded finding gets a
  response entry (untouched = `pending`), `report_level_notes` on every report. A per-report zip
  remains as a secondary/compatibility export behind a dropdown.
- **`report_level_notes` gets a minimal, non-obtrusive UI** — a collapsed "＋ Add report note"
  link, not an always-visible textarea.
- **PHI is not a constraint** on the review output.

## Input formats (reference)

The extraction-results directory (produced upstream, out of scope here) contains:

| Artifact | Shape |
|---|---|
| `<safe_id>.extracted.json` (one per row) | `ExtractedReportFindings` + optional `_validation` key |
| `csv_inputs_manifest.json` | JSON **array**: `[{row_number, source_id, safe_id, staged_path}]` |
| `batch_results.jsonl` | one status row per report (ignored by the reviewer) |
| `_staged_reports/<safe_id>.txt` | normalized per-row report text (**primary source text** — extraction quotes are verbatim against this) |

- `safe_id` is a **sanitized** `source_id` (`[^A-Za-z0-9._-]+` → `_`, dedupe suffix `__2`,
  Windows reserved-name guard, 120-char truncation) — so filenames cannot be matched back to CSV
  ids directly.
- `row_number` is the manifest's authoritative CSV record number (data records numbered from 2;
  the header is record 1). Duplicate `source_id` values are allowed and produce distinct
  `safe_id` / `row_number` pairs.

The source CSV has a report-identifier column and a report-text column (multi-line, quoted).

The reviewer (`extraction_reviewer/`) is a single-file offline vanilla-JS SPA built by
`build.py`; it currently loads extraction JSON via drag-drop / `<input webkitdirectory>`, has no
CSV parser, and exports a zip of per-file `*.review.json`. It is presently **untracked** on
`feature/extraction-reviewer`.

## Design

### Guided wizard (primary CSV workflow)

A 3-step flow shown on load when no batch is resumed:

1. **Step 1 — Select source CSV.** Pick/drop the `.csv`. Strip a leading UTF-8 BOM (`\ufeff`)
   before parsing — Excel's "CSV UTF-8" emits one, and a glued BOM silently corrupts the first
   header name (breaking column auto-detect and `source_id` verification); the batch-ID hash is
   still computed over the raw file bytes as-is. Parse with an RFC-4180-aware splitter (quoted,
   multi-line, embedded-comma safe; newlines inside quoted fields stay literal — the producer
   preserves `\r\n` there too). Auto-detect columns when the CSV has exactly two; otherwise show
   a column picker (identifier column + text column). Preserve original record numbering so
   records align with manifest `row_number`.
2. **Step 2 — Select extraction-results directory.** Load `<safe_id>.extracted.json` files and,
   if present, `csv_inputs_manifest.json`. Ignore `batch_results.jsonl`, `extraction_reviewer.html`,
   and non-extraction files. Suffix-aware stem normalization strips a trailing `.extracted` /
   `.coded`.
3. **Step 3 — Confirm.** Show **matched / unmatched / invalid** counts (definitions below). As a
   sanity check, take one matched report and verify its first extraction quote occurs verbatim in
   the resolved source text; warn (non-blocking) on mismatch — this catches a wrong text-column
   choice and normalization drift *before* review starts. Then enable **Start review**.

The user can go **Back** to replace either input. Both inputs must be present to start.

**Compatibility path:** a "load files directly" escape remains for the pre-existing behavior
(extraction JSONs with sibling `.txt`/`.md` or reconstructed text, no CSV). The wizard is the
primary path; this is the fallback.

### Deterministic manifest join

The join is keyed by `safe_id` (from the filename), through the manifest, to a CSV record by
`row_number`. **Never join solely by `source_id`** — duplicate ids are allowed.

For each `<safe_id>.extracted.json` (suffix stripped → `safe_id`):

1. Resolve `safe_id` to its manifest entry (`safe_id` → `{row_number, source_id, ...}`).
2. Use the entry's **`row_number` as the authoritative CSV-row join key**; select that CSV
   record for source text.
3. **Verify** the selected row's identifier cell equals the entry's `source_id`. On mismatch,
   classify the item as **invalid** (do not silently trust it).

Classification for the Step 3 summary:

- **matched** — extraction file → manifest entry → CSV row, with verified `source_id`.
- **unmatched** — extraction file with no manifest entry or no corresponding CSV row; or CSV rows
  with no extraction file.
- **invalid** — malformed extraction JSON, or manifest entry whose CSV row id ≠ `source_id`.

### Source text and normalization

The producer **rewrites report text before extraction**: `_normalize_csv_report_text` (in
`cli/csv_batch.py`) converts inline `FINDINGS`/`IMPRESSION` markers into standalone headers and
adjusts surrounding whitespace. Extraction quotes are therefore verbatim against the **staged**
text (`_staged_reports/<safe_id>.txt`), *not* the raw CSV cell — and the reviewer's persistent
quote highlighting and missing-finding capture rely on exact string matching against the
displayed text. Displaying raw CSV text would silently break highlighting on every report where
normalization fired.

**Source-text resolution precedence** (once matched):

1. **Staged text** `_staged_reports/<safe_id>.txt` (primary — the directory pick already loads it
   via recursion, so this path costs nothing)
2. **CSV record with the producer's normalization ported to JS** (when staged text is absent —
   the JS port must reproduce `_normalize_csv_report_text` so displayed text matches quotes)
3. Sibling `.txt`/`.md` (compatibility path, non-wizard loading)
4. Reconstruction from the JSON itself (last resort, keeps the orange `RECONSTRUCTED` pill)

A small banner states which source is in use.

### Browser-local batch persistence (keyed by CSV)

Persist the whole working state so the reviewer can close the tab/HTML and resume.

- **Batch ID** = SHA-256 hex of the CSV file contents. Retain the CSV filename for display.
- **IndexedDB** holds the payloads and review data per batch: CSV text, selected column mapping,
  manifest, extraction JSONs, review responses, missing findings, report notes, current position,
  and an update timestamp.
- **`localStorage`** holds only a small **batch index** (`[{batchId, csvFilename, updatedAt,
  counts}]`) and **preferences** (reviewer identifier, last column-mapping choice).
- **Resume:** when the same CSV is selected, or the app is reopened, look up the batch index; if
  the batch exists, offer to **resume the saved batch** — loading everything from IndexedDB
  without reselecting files.
- **Extraction-set drift:** if the selected extraction-folder contents differ from the saved set
  (compare filenames + per-file hashes), ask whether to **replace** the saved extraction data
  (review responses keyed by stable finding id are preserved where they still apply).
- **Delete:** provide a way to delete a saved batch (removes the IndexedDB record and its index
  entry).
- **Documented limitations:** persistence is browser-local — tied to the same browser and the same
  HTML file location under `file://`. `file://` origin scoping varies by browser (some share a
  single `file://` origin, some isolate by path), so a moved HTML file or a different
  browser/profile will not see the saved batch. Additionally, `file://` IndexedDB in Chromium is
  **best-effort** storage (no `navigator.storage.persist()` grant): under disk pressure the
  browser may evict a saved batch. The UI therefore encourages periodic export — the combined
  JSON is cheap to download — so review work is never held *only* in browser storage.

### Combined JSON export (authoritative)

Every loaded report is included. Every loaded finding gets a response entry; untouched findings
serialize as `status: "pending"`. `report_level_notes` appears on every report object.

```jsonc
{
  "app_version": "1.1",
  "kind": "extraction-review-batch",
  "batch": { "csv_filename": "reports.csv", "csv_sha256": "…", "batch_id": "…" },
  "reviewer": { "identifier": "jane.doe@example.org" },
  "exported_at": "2026-07-14T12:34:56.000Z",
  "batch_summary": {
    "reports_total": 40, "reports_reviewed": 38,
    "findings_total": 812, "approved": 770, "flagged": 42, "pending": 0,
    "missing_findings_count": 11
  },
  "reports": [
    {
      "source_file": "CHEST001.extracted.json",
      "source_sha1": "abcdef123456",
      "source_id": "CHEST001",          // from manifest entry
      "csv_row_number": 2,              // authoritative join key
      "source_exam": { "study_description": "…", "study_date": "…", "modality": "CT" },
      "summary": { "total_findings": 22, "approved": 19, "flagged": 3, "pending": 0,
                   "missing_findings_count": 1 },
      "responses": [ /* one per finding: finding_index, finding_name, presence,
                        status ("pending" when untouched), comment,
                        first_reviewed_at, updated_at */ ],
      "report_level_notes": "",         // present on every report
      "missing_findings": [ { "description": "…", "report_text": "…", "added_at": "…" } ]
    }
  ]
}
```

`finding_index` remains the join key back into the source `findings[]` array. Download name:
`review-<reviewer-slug>-<yyyymmdd-hhmm>.json`.

**Export button:** a split/dropdown control. Primary click = combined JSON (all reports).
Dropdown = the existing per-report zip (`buildReviewJson()` per touched file), kept for
compatibility. `fflate` stays regardless (needed for embedded-bundle loading).

### Report-level notes (non-obtrusive)

Wire up the currently-dead `report_level_notes`: a collapsed **"＋ Add report note"** link under
the exam-info header in the main pane. Clicking expands a compact textarea; emptying it collapses
back to the link. A small dot on the file's sidebar row indicates a note exists. Nothing
always-on-screen.

### Delivery

The colleague gets the single built `extraction_reviewer.html` (from `extraction_reviewer/build.py`)
— emailed or shared. She opens it, runs the wizard (CSV → results dir → Start review), reviews,
downloads the JSON. Nothing to install.

## Phases

### Phase 0 — Land the reviewer on its branch
1. **Commit `extraction_reviewer/`** on `feature/extraction-reviewer` (untracked today) together
   with its plan docs and the shared-file edits (`.gitignore`, `package.json`, `DEV_LOG.md`).
2. Confirm `uv run pytest` green.

(No cherry-pick of any extraction-tool WIP — out of scope. Fixtures below stand in for real
extraction output.)

### Phase 1 — Results-directory awareness
1. Suffix-aware stem normalization (`.extracted` / `.coded`) in `app.js` and, for the
   compatibility path, `pack.py:find_report_pairs`.
2. Recognize `csv_inputs_manifest.json` by shape (array of `{row_number, source_id, safe_id,
   staged_path}`) and retain it as the join table rather than parsing it as an extraction.
3. Ignore `batch_results.jsonl`, `extraction_reviewer.html`, and other non-extraction files in a
   picked folder.

### Phase 2 — Wizard + CSV loading + deterministic join
1. RFC-4180 CSV parser preserving record numbering and quoted-field newlines; strip a leading
   UTF-8 BOM before parsing (batch-ID hash stays over raw bytes); accept `.csv` in the file input
   and drag-drop.
2. Column auto-detect (2-column) / column picker (wider).
3. 3-step wizard UI (CSV → results dir → confirm) with Back/replace.
4. Manifest join: `safe_id` → entry → authoritative `row_number` → CSV record, with `source_id`
   verification; classify matched / unmatched / invalid; show counts in Step 3.
5. Source-text resolution precedence (staged text primary) + the source banner; port
   `_normalize_csv_report_text` to JS for the CSV-fallback path.
6. Step-3 quote spot-check: one matched report's first extraction quote verified verbatim against
   the resolved source text; non-blocking warning on mismatch.
7. Keep the highlight-to-capture missing-finding flow working against wizard-sourced text.

### Phase 3 — Persistence
1. Batch ID = SHA-256 of CSV contents; batch index + preferences in `localStorage`.
2. IndexedDB store for CSV/manifest/extraction JSONs/review responses/missing findings/report
   notes/position/timestamp.
3. Resume prompt on same-CSV select or app reopen; load fully from IndexedDB.
4. Extraction-set drift detection + replace prompt.
5. Delete-batch control.

### Phase 4 — Export + report notes
1. `buildCombinedReviewJson()` per the contract above (all reports; every finding a response;
   `report_level_notes` on each; `pending` for untouched).
2. Split/dropdown export button (combined JSON primary, per-report zip secondary).
3. Wire up `report_level_notes` with the collapsed "＋ Add report note" UI.
4. Bump `app_version` to `1.1`.

### Phase 5 — Verify end-to-end (fixtures)
1. Build a **representative fixture** results dir by hand: 2–3 `*.extracted.json`, a matching
   `csv_inputs_manifest.json` (including one duplicate-`source_id` pair and one deliberately
   mismatched entry), `_staged_reports/` text files, and the source CSV. The fixture must include
   **one row whose text carries an inline `FINDINGS:` marker** (so staged text ≠ CSV cell —
   exercises the precedence rule and highlight integrity) and a **BOM-prefixed CSV variant**.
2. Build the HTML; open from `file://`.
3. Run the wizard; confirm matched/unmatched/invalid counts are correct, the manifest join uses
   `row_number` (duplicate ids resolve to distinct rows), source text shows from the staged files
   (banner says so), quote highlighting works on the normalized (inline-marker) report, and the
   BOM'd CSV parses with clean headers.
4. Approve / flag / add a missing finding / add a report note; download the combined JSON and
   assert the contract (every report, every finding, `pending` where untouched,
   `report_level_notes` present, `csv_row_number` correct, `finding_index` maps back).
5. **Persistence acceptance:** close and reopen the HTML; confirm the batch resumes from
   IndexedDB **without reselecting files**, at the saved position, with responses intact. Confirm
   delete-batch clears it.

### Phase 6 — Documentation
1. Mark this plan complete; update
   [extraction-reviewer-workflows.md](extraction-reviewer-workflows.md) Phase C item 2 and
   cross-link.
2. `extraction_reviewer/README.md` + `REVIEWER_GUIDE.md`: document the wizard, CSV loading,
   browser-local persistence (and its `file://` limitation), and the combined export.
3. `docs/DEV_LOG.md` entry.
4. Taskfile target `review:build` rides along.
5. No CHANGELOG entry — internal tooling.

## Risks / open questions

1. **`file://` IndexedDB scoping.** Behavior varies by browser — some share one `file://` origin,
   some isolate by path — so resume may not work if the HTML is moved or a different browser is
   used. Documented as a limitation; the batch index degrades gracefully when storage is
   unavailable (falls back to the wizard).
2. **Folder-pick recursion.** `<input webkitdirectory>` recurses, so picking the results dir also
   pulls in `_staged_reports/*.txt`. Required behavior (staged text is the primary source text) but enlarges the file
   list; filter deliberately.
3. **CSV id collisions.** Handled by the deterministic join (authoritative `row_number`, not
   `source_id`); `csv_row_number` is carried into the export so duplicates stay distinguishable.
4. **Extraction-set drift.** If the folder no longer matches the saved batch, the replace prompt
   governs; responses keyed by stable finding id are preserved where they still apply.
5. **Encoding.** Excel "CSV UTF-8" BOMs are stripped (see wizard Step 1). Other encodings
   (e.g. cp1252) are out of scope for v1: the producer reads the CSV as `utf-8-sig`, so the file
   the colleague feeds the reviewer is the very file the producer consumed — a mismatch would
   already have failed upstream, and residual drift surfaces at the Step-3 quote spot-check.

## Completion criteria

- Wizard is the primary CSV workflow (CSV → results dir → confirm → Start review), with
  Back/replace; direct-file/paired-text loading still works as compatibility.
- Manifest join is deterministic: `safe_id` → entry → `row_number` → CSV record, `source_id`
  verified, never joined by `source_id` alone; matched/unmatched/invalid surfaced at Step 3.
- Source-text precedence holds: staged text primary, quote highlighting verified intact on a
  report whose staged text differs from its CSV cell; BOM'd CSVs parse with clean headers.
- Batches persist in IndexedDB keyed by CSV SHA-256 (index + prefs in `localStorage`); resume,
  drift-replace, and delete all work; close/reopen resumes without reselecting files.
- Combined export includes every report, a response per finding (`pending` when untouched), and
  `report_level_notes` on every report.
- Verified against representative fixtures; no extraction-tool code pulled into this workstream.
