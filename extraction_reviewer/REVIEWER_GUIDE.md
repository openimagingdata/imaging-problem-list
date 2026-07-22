# Extraction Review Guide

Use this offline tool to check what the extractor found in each radiology report. Nothing leaves your machine, and review progress saves in this browser as you work.

## Screen tour

![Reviewer workspace with four numbered callouts](docs/images/guide-overview.png)

1. **Worklist and progress.** The sidebar groups findings by report and shows pending, approved, flagged, unsure, and missed totals.
2. **Evidence and extraction.** Compare the evidence quote with the finding name, presence, anatomy, attributes, and coding.
3. **Source report.** Read the full resolved report around the highlighted evidence; warnings identify reconstructed text or an unmatched quote.
4. **Review controls.** Add an optional comment, choose Approve, Flag, or Unsure, and identify questioned attributes when useful.

## Reviewing & keys

![Sidebar states and review controls with four numbered callouts](docs/images/guide-sidebar.png)

1. **Set a verdict.** Approve means correct, Flag means wrong, and Unsure means you cannot confidently decide from the report.
2. **Clarify concerns.** Flag and Unsure reveal optional “What’s in question” chips; comments and chips are helpful but not required.
3. **Use the keyboard.** <kbd>A</kbd>/<kbd>F</kbd>/<kbd>U</kbd> decide · <kbd>↑</kbd>/<kbd>↓</kbd> move · <kbd>?</kbd> opens help; shortcuts pause while typing.
4. **Watch the worklist.** Status styling, per-file progress, drafts, and the tally pills update immediately and save automatically.

## Missing findings & export

![Missing-finding capture and export with four numbered callouts](docs/images/guide-missing.png)

1. **Capture evidence.** Open **+ Missing findings**, then highlight supporting text in the source report.
2. **Describe the omission.** The selection fills the supporting quote; add a plain-language description and save it.
3. **Add report context.** Use **+ Add report note** for comments that apply to the whole report rather than one finding.
4. **Export periodically.** **Download review JSON** includes every report and finding; the overflow contains **Per-report zip (legacy)**.

## More: Persistence & resuming

Your work autosaves in this browser. CSV batches and embedded bundles appear in the saved-batch list and can resume without reselecting their inputs. For a direct files or folder load, re-pick the same input to restore its saved responses.

Saved work is tied to this browser/profile and HTML location. Browsers vary in how they scope `file://` storage, and browser storage can be evicted under disk pressure. Download the combined review JSON periodically and before moving the HTML or switching browsers.

The landing saved-batch list is also where batches are deleted. Deleting a batch removes its IndexedDB payload and saved-batch index entry from this browser.

## More: CSV wizard details

1. Select the original source CSV. A two-column CSV is mapped automatically; wider files ask for the identifier and report-text columns.
2. Select the extraction-results folder containing extraction JSONs, `csv_inputs_manifest.json`, and preferably `_staged_reports/`.
3. Confirm matched, unmatched, and invalid counts. The quote spot-check warns if resolved report text does not contain an extraction quote verbatim.
4. Choose **Start review**. Duplicate source identifiers remain distinct because the manifest row number—not `source_id` alone—is the join key.

Staged report text is preferred because it is the normalized text used during extraction. If staged text is unavailable, the reviewer uses normalized CSV text, then paired/embedded text, then clearly marked reconstructed snippets.

## More: What to write when flagging

Be specific about why the extraction is wrong. A short, concrete reason is usually enough:

- “Presence is wrong—the report says no discrete mass.”
- “Wrong laterality—the report says right kidney, not left.”
- “Location is too broad—use mid pole rather than kidney.”
- “The quote comes from a different paragraph and does not support this finding.”

Use the question chips when they communicate the issue more precisely. A draft comment can be left without setting a verdict if you need to return to it.

## Reference: source text and missing findings

The source report appears while reviewing a finding and while logging a missing one. The current evidence quote is highlighted and scrolled into view. A reconstructed warning means the original report was unavailable and the displayed text may be incomplete.

In the missing-findings panel, highlight report text to capture a supporting quote, describe the omitted finding, then choose **Add missing finding**. Added entries can be removed if you change your mind.

## Reference: finishing a review

Confirm the reviewer name shown in the sidebar, then choose **Download review JSON**. The combined file records all reports and findings—including pending responses—plus report notes, missing findings, unsure verdicts, and question targets. Send that JSON back to the review coordinator.
