# Extraction Reviewer

Single-file HTML tool for reviewing extraction JSON output from the finding-extractor
pipeline. The reviewer opens the HTML, loads a folder of extraction JSONs, walks the
findings, approves or flags with comments, optionally logs missed findings, and
exports a zip of per-file review JSONs.

No server, no install, no network access at run time. Runs entirely in the browser.

## Maintainer workflow

### Build just the app

```bash
# From the repo root (or from this directory)
uv run python extraction_reviewer/build.py -o extraction_reviewer/extraction_reviewer.html
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

1. Unzip the bundle.
2. Double-click `extraction_reviewer.html` (or open it in any modern browser).
3. Enter a reviewer identifier (name, email, or GitHub username).
4. Drag and drop the JSON files, or pick the folder. Progress saves automatically
   in this browser.
5. Walk the findings in the sidebar. For each one:
   - Press <kbd>A</kbd> or click **Approve** to accept the extraction as-is.
   - Type notes and press <kbd>Enter</kbd> (or click **Flag**) to record an issue.
6. For each report, use **+ Missing findings** in the sidebar to log anything the
   extractor missed (description + optional supporting quote).
7. When done, click **Download reviews (zip)**. Send the zip back to the maintainer.

### Keyboard shortcuts

- <kbd>A</kbd> — approve the current finding
- <kbd>F</kbd> — focus the comment box; if it already has text, send it as a flag
- <kbd>J</kbd> / <kbd>K</kbd> — previous / next finding (crosses file boundaries)
- <kbd>H</kbd> / <kbd>L</kbd> — previous / next file (lands on first pending)
- <kbd>Enter</kbd> in the comment box — send flag and jump to next pending
- <kbd>Shift+Enter</kbd> — newline in the comment box
- <kbd>Esc</kbd> in the comment box — blur

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

## Output: review zip

The exported zip contains one `<basename>.review.json` per source file the reviewer
touched. Untouched source files are skipped. Each review JSON looks like:

```
{
  "app_version": "1.0",
  "source_file": "us_abdomen_20220208.coded.json",
  "source_sha1": "bd9083980f1b",
  "source_exam": { "study_description", "study_date", "modality" },
  "reviewer": { "identifier": "..." },
  "exported_at": "2026-04-17T13:18:39.120Z",
  "summary": {
    "total_findings": 35,
    "approved": 1,
    "flagged": 1,
    "pending": 33,
    "missing_findings_count": 1
  },
  "responses": [
    {
      "finding_index": 1,
      "finding_name": "hepatic steatosis",
      "presence": "present",
      "status": "approved" | "flagged" | "pending",
      "comment": "...",
      "first_reviewed_at": "...",
      "updated_at": "..."
    },
    ...
  ],
  "report_level_notes": "",
  "missing_findings": [
    { "description": "...", "report_text": "...", "added_at": "..." }
  ]
}
```

`finding_index` matches the position in the source `findings[]` array.

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

Each source file's review state is saved in `localStorage` under
`extraction-reviewer:<sha1-prefix>`, keyed by the SHA-1 of the file contents (first
12 hex chars). Renaming a source file doesn't disturb its progress. The reviewer
identifier is mirrored to `extraction-reviewer:reviewer` so it survives reloads.

`localStorage` is per-browser-profile — if the reviewer wants to continue on a
different machine, they should download the zip first, or we'd need to add an
import step (not implemented).
