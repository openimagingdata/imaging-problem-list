# Extraction Reviewer: UX Evaluation and Workspace Improvement Plan

Created: 2026-07-20
Status: Active — **Phase 0 complete (2026-07-20); Phases 1–3 remain.**
Functional findings 1–3 (universal autosave, review-view report pane, quote relabel) were pulled
into [windows-csv-review-handoff.md](windows-csv-review-handoff.md) Phase 4c and are complete;
the workspace redesign and triage/polish phases below remain this plan's later scope.
Supersedes: the first draft of this evaluation (2026-07-19), which mistakenly reviewed the backend-connected `extractor-ui/` app instead of this tool.

## Verification update (2026-07-20, post-Phase-4c)

Re-verified end-to-end against a fresh build (commits `792b73f`, `9ff2f91`):

- **Autosave (finding 1) — fixed and verified.** Non-CSV sessions get a batch id hashed from sorted per-file content hashes. Verified: embedded bundle — approve/flag, reload, resume prompt restores position and decisions; a *re-packed* bundle with identical reports resumes the same batch; the landing page lists the saved bundle with counts and Resume/Delete. Guide copy now matches behavior on every load path, including the `file://` eviction caveat and periodic-export advice.
- **Source report in review view (finding 2) — fixed and verified.** A "Source report" section renders the full resolved text with the current finding's quote highlighted and auto-scrolled into view (confirmed via DOM geometry, including on keyboard navigation). Unmatched-quote and reconstructed-warning treatments confirmed. Placement is stacked below the detail rather than the side-by-side sticky pane proposed below — acceptable; the layout question stays open.
- **"Evidence quote" relabel (finding 3) — fixed.**
- **Bonus from the same push:** Unsure verdict + structured "What's in question" flag-target chips (finding name, presence, anatomic site, laterality, size, severity, extent, temporal status, hedged language, lumps-multiple) — a down payment on workflows Phase B structured corrections; consistent shortcut microcopy.
- **Guide images — refreshed in Phase 0.** `extraction_reviewer/docs/images/guide-*.png` now show the final pre-handoff sidebar, identity, export, verdict, and missing-finding states with callouts matching the three-panel quick guide.

## Context

The extraction reviewer (`extraction_reviewer/`) is the standalone, single-file HTML review tool — no server, no install, no network at run time. A reviewer opens the file, loads extraction JSONs (zip folder, CSV wizard, or a `pack.py --embed` bundle), walks findings one at a time, approves/flags/marks unsure with comments, logs missed findings, and exports per-file review JSONs.

This evaluation was performed by building the tool from the current working tree, packing the bundled samples as embedded bundles, and walking the UI with Playwright: landing/CSV wizard, per-finding review, missing-findings view, keyboard flows, narrow viewport, and reload behavior. Note the working tree contains in-progress CSV-wizard work (see [windows-csv-review-handoff.md](windows-csv-review-handoff.md)); findings below reflect the current state including that work.

Scope relationship: [extraction-reviewer-workflows.md](extraction-reviewer-workflows.md) Phase B covers *structured correction data* (which field is wrong, corrected values, gold conversion). This plan is strictly the *review UI experience* — layout, report context, triage, persistence promises. The two should stay complementary.

Wireframe of the proposed workspace: [../screenshots/extraction-reviewer-workspace.svg](../screenshots/extraction-reviewer-workspace.svg)

## What already works

- Keyboard-first, one-finding-at-a-time review: A/F/U decisions with auto-advance, J/K and arrows to move, H/L between files; drafts save as you type.
- Per-finding status visible in the sidebar list with live global counts and per-file n/m progress.
- Missing-findings logging with the full report and highlight-to-capture supporting quotes — the best report-context experience in the tool.
- Coding display is genuinely reviewer-friendly: coded/unmapped states, candidate disclosures, rationale text.
- CSV wizard with join confirmation and a quote spot-check against the source text.
- Help modal with a screen tour; autosave + resume for CSV-wizard batches (IndexedDB); self-contained bundles for zero-install handoff.

## Findings (by severity)

**Functional**

1. **Autosave does not cover the primary handoff path.** Review decisions persist only for CSV-wizard batches (`scheduleBatchSave` guards on `state.csv?.batchId`, app.js:252). Embedded bundles (`pack.py --embed` — the documented reviewer workflow) and direct file/folder loads keep decisions in memory only; a reload loses all review work. Verified empirically (approve + flag, reload, counts reset) and in code. Worse, the Help modal promises "close the tab and come back, you won't lose anything" — true only for CSV batches.
2. **The source report is absent from the review view.** The section labeled "Report text" renders only the finding's extracted quote (`finding.report_text`, app.js:1436), even when a full paired report is loaded. The full report appears *only* in the Missing-findings view. While reviewing finding N, the reviewer cannot see surrounding sentences — which is exactly what's needed to judge correctness and to notice adjacent missed findings.
3. **Misleading label.** "REPORT TEXT" over a one-sentence snippet implies context that isn't there. It should read "Evidence quote" (or show the real report).

**Layout and information architecture**

4. **The report has no permanent home.** The workspace is sidebar / detail / action-rail; report context is bolted onto a secondary view. The proposed fix (wireframe): a sticky report pane between sidebar and detail, with the selected finding's quote highlighted and auto-scrolled into view, and previously reviewed quotes dimmed.
5. **Missing-findings entry is buried.** It's a "+ Missing findings" row pinned to the *end* of each file's finding list (below the fold at 35 findings) plus an unlabeled "+" icon in the stats row. It should be a persistent button on the file header card.
6. **No sidebar filtering or search.** With 35+ findings per file, there is no way to show only pending/flagged/unsure, and status is conveyed by color-only dots (colorblind-unfriendly).
7. **Narrow viewports stack the entire sidebar above the detail.** Stats, identifier, download, and the full finding list all precede the finding content; the action buttons are even further down. Sidebar should become a drawer with detail first.
8. **No resume affordance outside CSV batches** and no "jump to first pending" within a file.

**Interaction details**

9. **Export is disabled until the reviewer identifier is entered, with no explanation** — add a tooltip/hint stating why.
10. **Shortcut microcopy is inconsistent**: the landing page says "F focus / send flag", the finding view says "F flags". Pick one behavior description.
11. **Three comment types** (reviewer comment, report note, missing-finding description) look identical; copy should distinguish their purposes.
12. **No dark theme.** `viewer_v2` is dark-first for radiology context; a dark option would suit the same audience here.

**Owner feedback (2026-07-20, post-verification hands-on)**

13. **"Delete saved batch" is dangerously misplaced.** The app's most destructive action sits
    prominent-red in the sidebar block the reviewer looks at constantly — and it's redundant:
    the landing's saved-batch list already offers per-batch Resume/Delete.
14. **The export split-button is a mystery control.** The unlabeled dropdown half holds the
    legacy per-report zip; before an identifier is entered, both halves render disabled — an
    unlabeled, disabled, purpose-free button.
15. **Reviewer identity is a passive form field.** An empty "reviewer identifier" input squats
    in the sidebar and silently gates export (finding 9). It should be captured once on first
    open (name, then slugified for filenames), confirmed on reopen, and displayed as a chip.
16. **Loading UI crowds the workspace.** The "+ Add files" flow and the sidebar utility block
    cram batch management into the review surface; mid-session loading belongs in a modal.
17. **The in-app help is a wall.** Five pages of dense text defeats its first-run purpose. It
    should be three panels — ≤4 bullets and one image each — with deeper topics behind links.
18. **Startup dialog pile-up (found in live review, 2026-07-21; fixed same day).** Reopening an
    embedded bundle with a saved batch but no reviewer set stacked three layers: the identity
    modal, a native `window.confirm("Resume the saved review…?")` on top of it, and the CSV
    wizard landing behind both. Root cause: the embedded auto-load path interrupted startup with
    a blocking native prompt, racing the identity flow; the Phase 0 acceptance matrix missed the
    saved-batch + no-reviewer reopen state. **Fix:** saved work now resumes *silently* on all
    content-identity paths (embedded, direct) — nothing to ask, the content hash already proves
    it's the same batch; the CSV wizard's re-pick prompt became a non-blocking inline
    "Saved review found for this CSV — Resume / continue to load a results folder" notice, which
    keeps the drift-replace path reachable. Native `confirm()` remains only for genuinely
    destructive actions (delete batch, drift replace). Verified: the exact failure sequence now
    yields one dialog (identity) over the resumed workspace, and a wizard re-pick after a saved
    verdict shows the notice, resumes on click, and restores the verdict.
19. **Source-report auto-scroll never worked on long reports (found in live review, 2026-07-21;
    fixed same day).** The scroll used `mark.offsetTop`, which is relative to the nearest
    *positioned* ancestor — not the scrolling container (`.missing-report-text` is unpositioned)
    — so `scrollTop` always clamped to maximum and only quotes near the report's end were ever
    visible. Every earlier verification used short fixture/reconstructed reports where the wrong
    math clamps to sane values, so "auto-scroll verified" was trivially true. **Fix:**
    container-relative `getBoundingClientRect()` delta math, centering the quote. Verified
    against the long paired sample reports: four findings at different depths all render with
    the highlight centered (±1px) and distinct scroll offsets. Lesson recorded: scroll-position
    assertions are meaningless unless the fixture content overflows the container.
20. **Wizard step 2 could fail in total silence — and quietly wreck the live session (found in
    live review, 2026-07-21; fixed same day).** If the picked results folder yielded zero
    recognized extraction files with no per-file errors (wrong folder level, JSONs without a
    findings list, text-only contents), the Continue button simply never enabled — no summary,
    no error, nothing. Worse, `loadFileList(replace: true)` wiped the live session state the
    moment the folder was picked, so cancelling the modal left a zombie UI over empty state.
    **Fixes:** (a) step 2 is never silent — a zero-result pick explains what was seen and what
    was expected (file counts, skipped-JSON reasons, `*.extracted.json`/`*.coded.json` hint),
    and the success summary now also reports manifest found/missing; (b) opening the add-files
    modal snapshots the session and closing it without starting a review restores the snapshot —
    the wizard can no longer destroy live work. Verified: bad-folder pick shows the explanation;
    cancel restores a fully interactive session (verdict made post-restore); the happy path
    through the modal still joins 2/1/1 and starts review.
21. **The manifest was required when it should have been preferred (found in live review,
    2026-07-21; fixed same day).** The CSV wizard hard-required `csv_inputs_manifest.json` — an
    artifact only the *unmerged* windows-csv-handoff producer writes — so every results folder a
    user can actually make today (plain `*.extracted.json` named by report id) dead-ended as
    fully unmatched, violating the plan's own "how the JSONs were produced is irrelevant" scope
    principle. All acceptance testing had used fixtures that simulate the unshipped producer.
    **Fix: manifest preferred, filename fallback.** With no manifest, CSV ids are sanitized with
    the producer's exact rules and matched to file stems (exact first, then unambiguous prefix;
    duplicate sanitized ids and ambiguous pairings stay unmatched), case-insensitively. Source
    text picks raw vs. normalized CSV text by which contains the file's first quote (non-pipeline
    extractions quote raw text). Step 2 announces "manifest missing — will match rows by
    filename"; Step 3 carries an explanatory note; exports carry `join_method`
    ("manifest"/"filename") per report. Verified end-to-end on a manifest-less fixture (2 matched
    by filename, unmatched row counted, spot-check passes on raw text, highlight visible, export
    fields correct) with the manifest path regression-clean (2/1/1).

## Proposed design (see wireframe)

Four-zone workspace at wide widths: **sidebar → report pane → finding detail (with actions folded in)**.

- **Report pane (new, sticky):** full paired report; selected finding's quote highlighted (existing whitespace-tolerant exact-match approach, plus a warning chip when unmatched/reconstructed); reviewed quotes dimmed; clicking a highlighted quote selects that finding. Reused by the Missing-findings view, which already has highlight-to-capture.
- **Detail column:** existing blocks (presence, anatomy/region chips, attributes, coding, exam strip), quote block relabeled "Evidence quote", reviewer comment and A/F/U actions folded in from the rail; "+ Add report note" at the bottom.
- **Sidebar upgrades:** filter chips (All / Pending / Flagged / Unsure) + text filter; per-file card with progress, persistent "+ Missing" button, and "Resume ›" (jump to first pending); status dots gain a shape/letter variant for colorblind safety.
- **Persistence fix:** derive a batch id for embedded/direct loads (content hash, same sha256 approach as the CSV path) so every load path autosaves and resumes; align Help copy with actual behavior.
- **Narrow widths:** sidebar becomes an overlay drawer; report pane becomes a collapsible drawer above the detail; detail first.

Out of scope: structured correction editing (workflows Phase B), changes to the review JSON schema, `extractor-ui/`.

## Phases

### Phase 0 — Pre-handoff essentials (added 2026-07-20; gates the colleague handoff)

Resolves owner-feedback findings 13–17. One implementer session; ship before the tool goes out.

1. [x] **Remove "Delete saved batch" from the sidebar.** Deletion lives only on the landing
   saved-batch list (already implemented there). No replacement affordance in the sidebar.
2. [x] **Single export button.** Replace the split control with one primary **Download review JSON**
   button. The per-report zip moves behind a small overflow ("⋯") menu beside it, labeled
   "Per-report zip (legacy)". Export contract unchanged.
3. [x] **Reviewer identity flow.** First open with no stored reviewer: a small modal — "Who's
   reviewing?" — one text input, saves to the existing reviewer preference; slug derivation for
   filenames reuses the existing export-slug logic. Reopen with a stored name: a compact,
   non-blocking "Reviewing as {name} — Change" affordance (opens the same modal). The sidebar
   input field becomes a **name chip** with a Change action. Export is enabled whenever a name
   exists; if the first-run prompt is dismissed without a name, the chip reads "Set reviewer"
   and export's disabled state carries a tooltip saying exactly why (resolves finding 9).
   Keyboard shortcuts are inert while the modal is open.
4. [x] **"+ Add files" becomes a modal.** It opens the existing loading surface (CSV wizard + direct
   files/folder) in a modal dialog, reusing the landing's components — do not fork the loading
   logic. Full-screen on narrow viewports. The first-load landing page itself is unchanged.
5. [x] **Help restructure.** The in-app help becomes **three panels** (next/prev or tabs), each ≤4
   bullets and one image: (1) *Screen tour* — guide-overview.png; (2) *Reviewing & keys* —
   guide-sidebar.png (verdicts, chips, "A/F/U decide · arrows move · ? help" as one bullet);
   (3) *Missing findings & export* — guide-missing.png. Deeper topics (persistence & resuming,
   CSV wizard details, what to write when flagging) sit behind "More…" links as on-demand
   panels sourced from REVIEWER_GUIDE.md, which remains the long-form reference (reorganize it
   to mirror the panel structure). First-run auto-open shows panel 1; the `guideSeen` gate is
   unchanged.
6. [x] **Re-capture the three tour images** after the sidebar/help changes so they match the final
   UI (the sidebar block changes shape in items 1–3), and rebuild.

Acceptance (fresh browser profile, built HTML from `file://`): name prompt appears exactly once
and the export filename uses the slug; reopen shows the "Reviewing as…" confirm; help is three
panels with images; the sidebar block is tally pills + name chip + one export button (no delete,
no split control); "+ Add files" opens the modal and a load through it works end-to-end; the
windows-csv plan's Phase 5 core assertions (wizard counts, verdicts, export fields, resume)
still pass.

#### Phase 0 implementation notes

- First-run modal ordering is identity first, then quick-guide panel 1 after the identity modal closes. This
  preserves the existing `guideSeen` gate without stacking two modal dialogs.
- The Add Files dialog reparents the single landing loading-surface DOM node while open and restores it on
  close. Direct loads retain their existing append behavior; the CSV wizard retains its existing results-set
  replacement behavior.
- Each quick-guide panel owns one deeper topic: Screen tour → CSV wizard details, Reviewing & keys → flagging
  guidance, and Missing findings & export → persistence and resuming.
- Tour screenshots use four numbered callouts per image, matching the four bullets in their corresponding
  quick-guide panel.

### Phase 1 — Correctness and copy (cheap, high value)

1. Autosave + resume for embedded-bundle and direct-load sessions (hash-derived batch id); Help modal copy corrected to match behavior.
2. Relabel "Report text" → "Evidence quote"; export-disabled reason hint; consistent F-key microcopy; distinguish the three comment types in copy.
3. Promote "+ Missing findings" to the file header card.
4. Verify: build, pack sample bundle, manual pass + existing lint (`task lint:web` covers `extraction_reviewer` globs).

### Phase 2 — Report pane

1. Sticky report pane in the review view with quote highlight + auto-scroll; unmatched/reconstructed warning chip; reviewed-quote dimming.
2. Share the pane with the Missing-findings view (single report component).
3. Responsive: drawers for sidebar and report pane on narrow widths.
4. Verify: bundle walkthrough at wide and narrow widths; quote-match and no-match states.

### Phase 3 — Triage and polish

1. Sidebar filters + text search; Resume/first-pending jump; colorblind-safe status markers.
2. Session summary before export (counts per file, flagged-without-comment check).
3. Optional dark theme.
4. Docs: REVIEWER_GUIDE.md and docs/images refreshed per phase; DEV_LOG entries; archive this plan on completion.

## Open questions

- Highlight **all** finding quotes in the report pane (helps spot un-extracted spans) vs. current-finding-only (calmer)? Wireframe shows all-with-dimming; validate with a real reviewer pass.
- Embedded-bundle batch identity: hash of bundle bytes (identical re-opens resume) vs. hash of normalized report contents (re-packed bundles with the same reports also resume)?
- When no paired report exists, keep the stitched-quote reconstruction as the pane content (with a clear "reconstructed" banner), or hide the pane? Current "Source:" line is easy to miss.
- Should Phase 2 land before or after workflows Phase B structured corrections? Both touch the detail column; sequencing should avoid two redesigns of the same blocks.
