# Coding CLI Plan

Last updated: 2026-03-18
Status: Complete

## Goal

Add a first-class production coding CLI that follows the repo's existing CLI
pattern:

- progress/status messages go to stderr
- result payload goes to stdout or an explicit output file
- the CLI wraps `finding_extractor.coding.run_coding` rather than duplicating
  coding logic

## Steps

1. [x] Add `src/finding_extractor/cli/code.py`
- Uses Click like the existing extraction/eval CLIs.
- Accepts an extraction JSON file plus optional `--model`, `--reasoning`, and
  `--output`.
- Emits coding progress to stderr via a progress callback.
- Writes the coded extraction JSON to stdout by default or to `--output`.

2. [x] Wire a console entry point
- Added `finding-extractor-code` to `pyproject.toml`.

3. [x] Add regression tests
- Verify progress is emitted to stderr.
- Verify JSON output goes to stdout.
- Verify `--output` writes the coded extraction to disk instead of stdout.

4. [x] Update active docs
- Updated `README.md` CLI section.
- Updated `CLAUDE.md` CLI/module map.
- Recorded completion in `docs/DEV_LOG.md`.

5. [x] Verification
- Run targeted CLI tests and lint for touched files.
