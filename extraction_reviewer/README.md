# Extraction Reviewer

Single-file HTML tool for reviewing extraction JSON output from the finding-extractor
pipeline. Its primary workflow joins a source CSV to an extraction-results directory,
then collects approved, flagged, or unsure verdicts, questioned attributes, missed
findings, and report notes in one combined review JSON.

No server, no install, no network access at run time. Runs entirely in the browser.

## Maintainer workflow

### Build just the app

```bash
# From the repo root
task review:build
```

This writes the ignored build artifact `extraction_reviewer/extraction_reviewer.html`.
Building requires Python stdlib only; using `uv run` keeps the command aligned with
the rest of the repo workflow.

### Pack a reviewer bundle

Use `pack.py` when handing work to a reviewer:

```bash
# Zip mode: app + README + reports/ folder
uv run python extraction_reviewer/pack.py --reports path/to/extractions -o /tmp/review-bundle.zip

# Embedded mode: one self-contained HTML with reports baked in
uv run python extraction_reviewer/pack.py --reports path/to/extractions --embed -o /tmp/extraction-review.html

# Extractions and source report text live in separate folders
uv run python extraction_reviewer/pack.py \
  --reports path/to/extractions \
  --report-texts path/to/source-reports \
  --embed \
  -o /tmp/extraction-review.html
```

`--reports` should contain pre- or post-coded extraction JSON from
`finding-extractor` / `finding-extractor-code`. If a sibling `.txt` or `.md` file
has the same basename as a JSON file, it is included as the source report text. If
not, the reviewer reconstructs a limited report view from extracted snippets and
marks it as reconstructed.

Use `--dry-run` before shipping a batch to confirm counts and pairing warnings:

```bash
uv run python extraction_reviewer/pack.py --reports path/to/extractions --embed --dry-run
```

Building requires Python 3.9+ stdlib only — no dependencies.

## Reviewer workflow

1. Double-click `extraction_reviewer.html`. On first open, enter the reviewer name
   that should appear in exports; later opens show **Reviewing as {name} — Change**.
2. Select the original source CSV. Two-column files are mapped automatically; wider
   files show identifier-column and report-text-column selectors.
3. Select the extraction-results directory. It should include the extraction JSONs,
   `csv_inputs_manifest.json`, and preferably `_staged_reports/`.
4. Confirm the matched/unmatched/invalid counts and the quote spot-check, then start.
5. Review each finding as **Approve**, **Flag**, or **Unsure**. Flagged and unsure
   findings can optionally identify what is in question with attribute chips.
6. Use **+ Missing findings** to log omissions, and **+ Add report note** for notes
   that apply to a whole report. The full source report remains visible beside each
   finding, with its evidence quote highlighted.
7. Periodically click **Download review JSON**. The combined JSON includes every
   loaded report and finding, including untouched findings as `pending`. The **⋯**
   menu retains **Per-report zip (legacy)**.

The **Load files directly instead** section remains available for extraction JSONs
with sibling `.txt`/`.md` reports and for embedded bundles made by `pack.py`.
During review, **+ Add files** opens this same loading surface in a modal. In-app
Help is a three-panel quick guide; each panel links to deeper reference topics.

### Keyboard shortcuts

- <kbd>A</kbd> — approve the current finding
- <kbd>F</kbd> — flag the current finding
- <kbd>U</kbd> — mark the current finding unsure
- <kbd>↑</kbd> / <kbd>↓</kbd> — previous / next finding (crosses file boundaries)
- <kbd>Enter</kbd> in the comment box — send flag and jump to next pending
- <kbd>Shift+Enter</kbd> — newline in the comment box
- <kbd>Esc</kbd> in the comment box — blur
- <kbd>?</kbd> — open the reviewer guide

Shortcuts are inactive while typing in any input or textarea.

## Input: extraction JSON

Matches `ExtractedReportFindings` from `src/finding_extractor/models.py`:

```
{
  "exam_info": { "study_description", "study_date", "modality", "body_part", ... },
  "findings": [
    {
      "finding_name": "...",
      "presence": "present" | "absent" | "indeterminate" | "possible",
      "location": { "body_region", "specific_anatomy", "laterality" } | null,
      "attributes": [{"key", "value"}, ...],
      "report_text": "verbatim quote",
      "source_section": "findings" | "impression" | "both" | null,
      "coding": { ... } | null        // present after post-coding
    },
    ...
  ],
  "non_finding_text": [{"text", "category"}, ...]
}
```

The reviewer displays the `coding` block only when present, so pre-coded and
post-coded files both work from the same HTML.

## Output: combined review JSON

The primary export contains every loaded report and every finding. Untouched findings
are explicit `pending` responses, and every report has `report_level_notes`:

```
{
  "app_version": "1.2",
  "kind": "extraction-review-batch",
  "batch": { "csv_filename": "reports.csv", "csv_sha256": "...", "batch_id": "..." },
  "reviewer": { "identifier": "..." },
  "exported_at": "2026-04-17T13:18:39.120Z",
  "batch_summary": { "reports_total": 3, "findings_total": 35, "approved": 1,
    "flagged": 1, "unsure": 1, "pending": 32, "missing_findings_count": 1 },
  "reports": [
    {
      "source_file": "us_abdomen_20220208.coded.json",
      "source_id": "ROW-001",
      "csv_row_number": 2,
      "responses": [{ "finding_index": 0, "status": "unsure",
        "comment": "...", "flag_targets": ["presence"] }],
      "report_level_notes": "",
      "missing_findings": []
    }
  ]
}
```

`finding_index` matches the source `findings[]` position. Stable `flag_targets`
include finding name, presence, anatomy, laterality, size, severity, extent,
temporal status, hedged language, and lumped findings. The dropdown export produces
the legacy per-report zip, updated to the same verdict and response schema.

## Layout

```
extraction_reviewer/
├── README.md            # this file
├── REVIEWER_GUIDE.md    # embedded in the in-app Help dialog
├── build.py             # assembles src/ + vendor/ into one HTML
├── pack.py              # creates zip or embedded-HTML review bundles
├── src/
│   ├── shell.html       # outer HTML with placeholder tokens
│   ├── styles.css
│   ├── landing.html     # landing-screen partial
│   ├── app-shell.html   # review-screen partial
│   └── app.js           # client logic
├── vendor/
│   └── fflate.min.js    # MIT, ~32KB, used for zip export
├── docs/images/         # screenshots used by the in-app reviewer guide
└── samples/             # sample extraction JSONs for dogfooding
```

Build-time substitution: `shell.html` contains `__STYLES__`, `__LANDING_HTML__`,
`__APP_SHELL_HTML__`, `__VENDOR_ZIP_JS__`, `__APP_JS__`, `__APP_VERSION__` — `build.py`
fills them in and writes a single HTML. `window.APP_VERSION` is exposed to `app.js`
so the build version flows into exported review JSONs.

## Local development

The browser treats the built HTML as a regular page. To iterate quickly:

```bash
# Rebuild
uv run python extraction_reviewer/build.py -o extraction_reviewer/extraction_reviewer.html

# Some browsers (notably for testing with Playwright) block file:// URLs.
# Run a trivial local server if needed:
( cd extraction_reviewer && python3 -m http.server 8765 )
# Then open http://localhost:8765/extraction_reviewer.html
```

The `samples/` directory has both a pre-coded (`xr_chest_20210614.extracted.json`)
and a post-coded (`us_abdomen_20220208.coded.json`) extraction to exercise both
renderer paths.

Recommended checks before changing reviewer behavior:

```bash
task lint
task test
uv run python extraction_reviewer/build.py -o /tmp/extraction_reviewer_check.html
uv run python extraction_reviewer/pack.py --reports extraction_reviewer/samples --embed --dry-run
```

The repo web lint/format tasks include `extraction_reviewer/src/`. HTMLHint checks
`src/shell.html`; the other HTML files are partials and are validated through
formatting plus the build command.

## Persistence

Review payloads are stored in IndexedDB; `localStorage` holds only a small saved-batch
index and preferences under the `extraction-reviewer:` prefix. CSV batches are keyed
by the SHA-256 of the raw CSV bytes. Embedded bundles and direct loads use a stable
SHA-256 derived from their extraction-file hashes.

Reopening an embedded bundle offers an immediate resume. A CSV batch can resume
without reselecting files. For a direct folder/files load, re-pick the same input to
restore its saved responses. Saved work is tied to the same browser/profile and HTML
location: `file://` origin rules vary by browser, and Chromium treats file-backed
IndexedDB as best-effort storage that may be evicted under disk pressure. Download
the combined JSON periodically so the browser is never the only copy.
