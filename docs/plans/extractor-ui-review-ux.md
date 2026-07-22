# Extractor UI: Extraction Review UX Evaluation and Redesign Plan

Created: 2026-07-19
Status: Proposed

## Context

The extractor UI (`extractor-ui/`, Alpine.js + Flowbite + Tailwind via CDN) contains the human-in-the-loop surface for reviewing extraction output: Submit → Reports → Report detail → **Extraction Result** (`#/extractions/:id`). This document records a UX evaluation of that review surface (performed in mock mode, `?mock`, via Playwright walkthrough of all five views) and a phased redesign plan.

The review surface matters because it is where a human verifies that extracted findings faithfully represent the source report — yet today the source report text is not even visible on the review page.

Wireframe of the proposed wide-viewport layout: [../screenshots/extraction-review-two-column-layout.svg](../screenshots/extraction-review-two-column-layout.svg)

## Evaluation

### What works today

- Complete happy path exists: submit, poll extraction progress with stage detail, review findings with verbatim quotes, inline per-finding edit, coding summary, validation warnings/errors, corrections with author attribution.
- Light/dark theme with persistence; Flowbite components used consistently.
- Mock mode (`?mock`, `?mock&warnings`, `?mock&runningStage`) makes the whole UI exercisable without a backend — excellent for iteration and tests.
- Playwright e2e coverage (`tests/test_ui.py`) already exercises the main flows.

### Findings (by severity)

**Core review-task gaps**

1. **The source report is absent from the review page.** Verifying quotes and checking for missed findings requires the report text; today it lives on the parent Report page. Reviewers must keep two tabs or rely on memory. This is the single biggest workflow flaw.
2. **No quote↔text linkage.** Quotes are displayed per finding but not highlighted in situ in the report. `viewer_v2` already implements conservative whitespace-normalized exact-match highlighting with no-match warnings — the approach is proven in-repo and reusable.
3. **Missed-finding detection is unsupported.** Reviewers can edit/flag existing findings but there is no affordance to note "the report mentions X, extraction missed it" (the offline `extraction_reviewer` tool has this; the web UI does not).
4. **No review state.** Nothing tracks which findings a human has verified. No accept/flag per finding, no "n of m reviewed", no way to mark an extraction review complete. Corrections (free-text comments) are the only signal, and they live in a card at the bottom of a long page.

**Layout and information architecture**

5. **Single narrow column on wide screens.** At 1440px+ the page is a center column with dead space on both sides; a review of a 20-finding report means extensive scrolling through six stacked sections (study info → findings → coding → non-finding text → validation → model info → corrections).
6. **Metadata fragmentation.** Study info, Model Info (two fields = one full card), and Coding summary each occupy their own card. One compact strip would do.
7. **Validation is divorced from context.** Issues appear as a banner at the top _and_ a section at the bottom, but never on the finding card they concern.
8. **Finding cards are tall.** Six stacked label/value blocks per finding; with many findings this is a wall of scroll. Location chips (`abdomen` / `left kidney` / `left`) render as button-like badges but are inert.

**Interaction details**

9. **Attributes edit is a raw JSON textarea** — error-prone for non-developers; key/value row editing would be safer.
10. **Edit expands inline inside the card**, pushing all content down; a focused panel with the quote pinned would be better for concentration.
11. **No keyboard navigation** — a review pass over many findings is mouse-only.
12. **Reports table is low-information**: truncated ID with no tooltip/copy, no exam description, no extraction status/warnings badges, no search. Finding a report means scanning dates.

**Polish**

13. Favicon 404 in console on every load.
14. Loading states are spinner-only (no skeletons); actions give no toast feedback.
15. Navigation is "Back to X" links only; no breadcrumbs, so position in the Reports → Report → Extraction hierarchy is implicit.

## Proposed design

Wide viewports (≥1280px): two-column review workspace (see wireframe).

- **Header strip (replaces 3 cards):** exam description · modality · body part · study date | model chip | coded n/m chip | warnings chip | review-progress chip | "Mark complete" action.
- **Left pane (sticky):** full report text with quotes highlighted via the viewer_v2-style whitespace-normalized exact-match approach; clicking a finding scrolls to and emphasizes its quote; unmatched/ambiguous quotes get a warning chip.
- **Right pane (findings workspace):** filter bar (presence filter, uncoded-only, text filter) + compact finding cards (one-line summary: index, name, presence badge, coding chip, review state) that expand for detail. Expanded card shows location path, attributes, quote, **inline validation**, and actions (Accept / Flag / Edit).
- **Review state:** per-finding accept/flag persisted (likely as structured corrections so no new backend entity is needed — confirm against the corrections API), rolled up into the header progress chip.
- **Corrections dock:** scoped to the selected finding or the whole extraction.
- **Keyboard:** `j`/`k` prev/next finding, `a` accept, `f` flag, `e` edit, `?` shortcut help.
- **Narrow viewports:** columns stack; report pane becomes a toggleable drawer.

Explicitly out of scope: changing the extraction pipeline, the EFL schema, or the offline `extraction_reviewer` tool. This plan touches `extractor-ui/` and (at most) read-only reuse of existing API endpoints.

## Phases

### Phase 1 — Foundations (no layout change)

1. Breadcrumbs replacing "Back to X" links; favicon (fix 404).
2. Consolidated metadata header strip on the extraction page (study + model + coding chips); retire the separate Model Info and Coding cards.
3. Reports table improvements: full ID on hover + click-to-copy, exam description column, extraction status/warning badges, text search.
4. Toast notifications for save/submit actions; skeleton loading for tables.
5. Verify: `task test:ui` green; update `docs/screenshots/*.png`.

### Phase 2 — Two-column review workspace

1. Report-text pane with quote highlighting (port the whitespace-normalized exact-match + warning approach from `viewer_v2` evidence highlighting into shared JS or duplicate deliberately — decide at implementation time).
2. Findings workspace: filter bar, compact/expandable cards, inline validation on the affected finding (keep the top banner as a summary only).
3. Edit UX: focused edit panel (quote pinned), key/value attribute editing instead of raw JSON (JSON kept as an "advanced" fallback).
4. Responsive: stacked layout + report drawer below the wide breakpoint.
5. Verify: extend `tests/test_ui.py` (quote-highlight behavior, filters, edit flow); mock-mode fixtures already cover warnings; regenerate screenshots.

### Phase 3 — Review workflow

1. Per-finding accept/flag + review-progress tracking (investigate backing this with structured `correction_type` values vs. a new endpoint; the corrections model already carries `correction_type`, so prefer reuse).
2. "Missed finding" affordance (add-note → becomes a correction with structured type; full structured add-finding editing deferred unless adjudication sessions prove it necessary, mirroring the Phase B rationale in [extraction-reviewer-workflows.md](extraction-reviewer-workflows.md)).
3. Keyboard navigation + shortcut help overlay.
4. "Mark complete" state surfaced on the Report page's extractions table.
5. Verify: e2e coverage for the review pass; update `docs/frontend-usage.md` and `docs/human-review-workflow.md` to describe the web-UI review path alongside the offline reviewer.

### Docs (all phases)

- Update this plan as phases land; refresh `docs/screenshots/`; DEV_LOG entries per milestone; archive this plan on completion.

## Open questions

- Persistence for per-finding review state: structured corrections vs. a dedicated `review_state` field/endpoint. Corrections reuse is cheaper but conflates "I verified this" with "something is wrong"; decide with a quick look at how evals consume corrections.
- Quote highlighting: share code with `viewer_v2` (extract to a small ES module both apps import) or accept duplication (both are CDN/static apps with different toolchains — sharing may cost more than it saves at this size).
- Should accept/flag require authentication/user selection the way corrections do, or is an anonymous review pass acceptable for the single-operator deployment?
- Where does "review complete" surface for the evals workflow — is a completed review in the web UI a valid input to gold adjudication, or does gold remain the offline reviewer's domain ([extraction-reviewer-workflows.md](extraction-reviewer-workflows.md) Phase B)?
