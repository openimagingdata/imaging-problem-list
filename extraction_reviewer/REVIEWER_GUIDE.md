# Extraction Review — Quick Guide

This tool shows you, one finding at a time, what the AI pulled out of a radiology report. For each one you decide: **is this the right finding, said the right way, in the right place?** Approve the good ones, flag the bad ones with a short note, and log anything the extractor missed.

Nothing leaves your machine. Your progress auto-saves as you go — close the tab and come back, you won't lose anything. When you're done, the tool produces one small zip of review files for you to send back.

---

## The screen at a glance

![Overview of the reviewer UI with numbered callouts](docs/images/guide-overview.png)

The middle pane is organised top-down so each section answers the next question a reviewer asks:

1. **Report text.** Verbatim quote from the radiology report — your ground truth. If this doesn't say what the extraction claims, flag it.
2. **Finding + presence.** The extracted finding name in bold next to a colour-coded badge: green `PRESENT`, gray `ABSENT`, amber `POSSIBLE`. The badge is the single most important thing to double-check.
3. **Location.** Compact chips for specific anatomy, body region, and laterality — subordinate to the finding name.
4. **Attributes.** Size, morphology, flow direction, etc. Sanity-check these against the quote above.
5. **Your review panel.** Status chip, comment box (drafts auto-save), **Clear** / **Flag** / **Approve** buttons, and a keyboard hint.
6. **Worklist.** Every finding from every file you loaded, grouped by file, only the active file expanded. Click any row to jump.
7. **Toolbar actions.** **+ Add files** to load more extractions without leaving your progress, and **Help** to reopen this guide.

(Not labeled: below the attributes you'll also see **Coding** — OIFM/RID codes with a confidence status — and a thin **Exam** metadata strip. Expand **Report context** at the bottom if you want surrounding paragraphs.)

---

## Reviewing a finding

The whole loop is designed to be keyboard-first so you can rip through a worklist. The three main actions:

- **Approve** — you agree: the finding exists in the report, the presence is right, the location makes sense. No comment required.
- **Flag** — something is wrong: the finding isn't there, the presence is wrong, the location is wrong, the quote doesn't support the claim, etc. **A comment is required** so the downstream team knows why.
- **Draft comment** — typing in the comment box without flagging leaves a blue draft indicator in the sidebar. Useful if you want to come back and think more.

Both Approve and Flag auto-advance you to the next **pending** finding, skipping over ones you've already touched.

### Keyboard shortcuts

These work any time you're not inside the comment box. They're the fast path.

| Key                         | Action                                                                     |
| --------------------------- | -------------------------------------------------------------------------- |
| <kbd>A</kbd>                | **Approve** current finding, jump to next pending                          |
| <kbd>F</kbd>                | Focus the comment box — type your reason, then <kbd>Enter</kbd> to flag    |
| <kbd>J</kbd> / <kbd>K</kbd> | Previous / next finding (note: J goes **up**, K goes **down** — vim-style) |
| <kbd>H</kbd> / <kbd>L</kbd> | Previous / next file (jumps to first pending finding in that file)         |
| <kbd>?</kbd>                | Open this guide                                                            |

Inside the comment box:

| Key                               | Action                                                    |
| --------------------------------- | --------------------------------------------------------- |
| <kbd>Enter</kbd>                  | Submit the flag (only if there's a comment)               |
| <kbd>Shift</kbd>+<kbd>Enter</kbd> | New line in the comment                                   |
| <kbd>Esc</kbd>                    | Blur the comment box (so you can use the shortcuts above) |

Typical rhythm: **A, A, A, F → type reason → Enter, A, A, …** Approve anything that's obviously right without touching the mouse.

### Status indicators in the sidebar

![Sidebar with callouts for each status state](docs/images/guide-sidebar.png)

A dot on each row tells you its review state at a glance:

1. **Approved** — green dot, row dimmed. Already reviewed, moving on.
2. **Approved and currently selected** — green dot + blue outline. This is what's in the main pane.
3. **Flagged** — amber dot, amber row background. Comment is already written.
4. **Draft comment** — blue dot. You typed something but didn't flag; it's saved and waiting.
5. **Pending** — gray dot. Not yet touched.
6. **Tally pills** at the top, across all loaded files: ○ pending, ✓ approved, ⚑ flagged, + missed (logged by you as extractor misses). Hover any pill for the full label.
7. **Download reviews (zip)** — the primary export button. Enabled once you've entered a reviewer identifier and reviewed at least one finding.

---

## Flagging a finding — what to write

Be specific about **why** the extraction is wrong. A good comment points the extractor team at the fix. A few patterns that help:

- _"Report doesn't actually say this — the quote is from a different paragraph."_
- _"Presence is wrong — report says 'no discrete mass', should be absent not present."_
- _"Wrong laterality — report says right kidney, extraction says left."_
- _"Location is too broad — should be 'mid pole' not just 'kidney'."_
- _"Coded to wrong concept — this is fatty infiltration, not hepatic parenchymal disease generally."_

A one-line reason is usually enough. You can also leave a draft comment (just don't flag) if you want to think about something and come back to it.

---

## Logging a finding the extractor _missed_

Every file has a **+ Missing findings** button at the bottom of its group in the sidebar. Click it and you get a dedicated panel:

![Missing findings panel with numbered callouts](docs/images/guide-missing.png)

### How to use it

1. **Highlight the phrase** in the source report that describes the missing finding. Your selection turns yellow and stays highlighted — so you can see exactly what you captured.
2. **Supporting quote** — the selection auto-populates this read-only card. Re-highlight anywhere in the report to replace; use **Clear** to remove.
3. **Description textarea** — focus jumps here automatically after you highlight. Describe the missing finding however feels natural: _"small left pleural effusion, not mentioned in the impression"_ is fine. <kbd>Enter</kbd> submits; <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line.
4. **Add missing finding** — saves the entry. It shows up in the list below the form, and the sidebar's **+ missed** counter ticks up.

You'll see added entries listed below the form. Each has a **Remove** button if you change your mind.

### About the source report

If the original `.txt` or `.md` report was shipped alongside the extraction JSON, that's what you're seeing — the real radiology report, verbatim. You'll see the filename next to the **SOURCE REPORT** label.

If only the extraction JSON was shipped, the tool **reconstructs** a rough report from the extracted snippets — you'll see an orange **RECONSTRUCTED** pill. It's usable for orientation and highlight-to-quote, but it isn't the full original text, so treat it as a prompt rather than a transcript.

---

## Finishing up

1. Make sure your name or identifier is in the **reviewer identifier** field (top of sidebar). This stamps every output file.
2. Click **Download reviews (zip)**. You get one zip containing a `*.review.json` per file you touched. These record every approve/flag/comment/missing-finding you entered.
3. Send the zip back to whoever asked you to review.

You don't need to finish in one sitting. Progress is saved per-file in your browser automatically — come back and pick up where you left off. The export only includes files you actually touched, so partial reviews are fine.
