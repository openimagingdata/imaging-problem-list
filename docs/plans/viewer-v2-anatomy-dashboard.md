# viewer_v2 Anatomy-Aware IPL Viewer Plan

Status: Body-map redesign implemented; ready for review

## Summary

Build `viewer_v2` as a separate static React/Vite/TypeScript/Tailwind app for Cloudflare Pages. The first slice is a single-patient anatomy-first viewer for `sample_data/example2/MRN0000001`: generated committed data, abstract radiology-oriented anatomy diagram, progressive detail pane, finding timelines, finding-definition metadata, and right-pane exam/report drilldown with exact evidence highlighting.

The viewer trusts the IPL. Each IPL `finding.id` is the canonical clinical problem row. Anatomy grouping is presentation-only and must never merge or split IPL findings.

## Implementation Notes

Implemented in this pass:

- `viewer_v2/` is a separate React/Vite/TypeScript/Tailwind app with its own `package.json`, `package-lock.json`, strict TypeScript config, Vite config, and source under `viewer_v2/src/`.
- `scripts/build_viewer_v2_data.py` generates the committed static data bundle under `viewer_v2/public/data/`.
- `viewer_v2/anatomy_clusters.json` is the editable anatomy/cluster presentation config.
- The app reads only generated files from `viewer_v2/public/data/` at runtime.
- The current first patient bundle covers `patient-mrn0000001`, 123 IPL findings, 10 exams, exact EFL/report drilldown files, finding-definition metadata, anatomy metadata, and generated warning records.
- The UI includes whole-patient, region, cluster, finding, and observation drilldown states.
- The diagram renders as an abstract body-map schematic with lateralized extremities: right extremities on the viewer-left, left extremities on the viewer-right, with generic/unspecified extremity findings kept separate.
- Diagram zones show actual active finding names as clickable chips; the visible primary affordance is not a count-only “N active” badge.
- The viewer uses a dark radiology-workstation theme by default. Light mode is not an acceptable v1 presentation for this tool.
- Conservative evidence highlighting is implemented by whitespace-normalized exact match only; missing or ambiguous highlights are surfaced as warnings.
- Mobile selected states show the selected detail before the anatomy dashboard.
- Root Taskfile targets were added for `viewer:v2:data`, `viewer:v2:dev`, `viewer:v2:build`, and `viewer:v2:deploy`.
- `Body`-region ontology rows are curated into presentation regions by display text, including thorax, abdomen, and extremity fallbacks.
- Evidence matching folds Unicode compatibility forms plus common dash and smart-quote variants before declaring a generated no-match warning.
- `viewer:v2:check` regenerates data and fails if committed generated data drifts.

Generated-data caveats in this pass:

- Two IPL findings have no specific location ID and intentionally use the explicit `unlocalized` display fallback.
- Seven generated warnings are embedded in `manifest.json` for UI surfacing: four exact-evidence misses, two explicit missing-anatomy fallbacks, and one missing finding definition.
- Anatomy clustering is deterministic presentation metadata. It is not clinical reconciliation.

## Scope Boundary

The first slice must support, for MRN0000001:

- anatomy diagram
- progressive detail pane
- region/cluster/location filtering
- strict side filtering
- finding timeline
- finding-definition metadata
- exam/EFL/report drilldown
- exact conservative evidence highlighting

Out of scope for first slice unless explicitly re-added:

- multi-patient polish beyond data-shape compatibility
- clinical anatomy compatibility reconciliation
- fuzzy evidence matching
- formal Playwright tests
- deployment automation beyond documented build/deploy commands
- full URL restoration for every filter
- multi-report comparison

## Implementation Changes

- Create nested `viewer_v2/` app with its own `package.json`, lockfile, Vite config, strict TypeScript config, Tailwind setup, and source under `viewer_v2/src/`.
- Use npm/package-lock, React + Vite + TypeScript + Tailwind, hand-authored components, and no UI component library by default.
- Use a React/Tailwind/SVG-or-CSS-grid diagram component for v1; no canvas and no external bitmap dependency.
- Add `scripts/build_viewer_v2_data.py`.
- Add root/Taskfile convenience targets that delegate into `viewer_v2` for data build, dev, build, and optional deploy.
- Deploy separately to Cloudflare Pages project `ipl-anatomy`, publishing `viewer_v2/dist`.

## Generated Data Contract

The browser must read only generated files under `viewer_v2/public/data/`. It must not read from `sample_data`, `viewer/data`, Python package files, or DuckDB at runtime.

`viewer_v2/public/data/` is generated output. Human edits belong in source inputs such as `sample_data/example2`, `viewer/data/finding_display_info.json`, or editable cluster config:

```text
viewer_v2/anatomy_clusters.json
viewer_v2/finding_compact_names.json
```

The build script reads:

- `sample_data/example2/MRN0000001_ipl.json`
- all relevant `sample_data/example2/*_efl.json`
- matching report Markdown files
- `viewer/data/finding_display_info.json`
- `viewer_v2/finding_compact_names.json`
- `anatomic-locations`

It generates committed static data:

- `patients.json`
- patient metadata
- IPL copy
- EFL/report files by report ID
- `anatomy_index.json`
- generated `anatomy_clusters.json`
- finding definition metadata
- compact finding display metadata

Each generated top-level JSON file must include a schema/version field. The generator must validate and fail on:

- missing or duplicate IPL `finding.id`
- duplicate generated IDs within one namespace
- observation references without resolvable report/EFL metadata
- missing report files for observations that need drilldown
- missing displayable status
- unresolved anatomy without explicit `unlocalized` fallback
- evidence text that cannot be associated with a report record

Generated warnings are allowed for non-fatal display fallbacks, but must be written into the generated data so the UI can surface them when relevant.

## Anatomy Mapping Rules

Anatomy mapping is deterministic and presentation-only.

Location precedence:

1. Use IPL `finding.anatomicLocation.locationId` when present.
2. Resolve metadata through `AnatomicLocationIndex`.
3. Assign region from resolved metadata.
4. Assign cluster from editable cluster config.
5. Use containment/part-of ancestors only as fallback classification aids.
6. If no location can be resolved, assign `unlocalized`.

Laterality buckets are exactly:

- `left`
- `right`
- `midline_nonlateral`
- `generic_unspecified`

Generic/unspecified findings must not be folded into left/right counts.

The diagram hierarchy is:

```text
region -> organ cluster -> exact location -> IPL finding
```

Exact `locationDisplay` remains visible in finding rows/details.

## Status Semantics

Status is computed per IPL finding, not per anatomy group:

- `current`: latest observation says `present`
- `always`: latest observation says `present` and all observations are present
- `resolved`: at least one prior observation says `present` and latest observation says `absent`
- `never_present`: no observation says `present`

Diagram active-burden intensity uses `current + always`.

Resolved findings appear as muted secondary clickable counts. Never-present findings are hidden from diagram counts unless the user enables the never-present toggle.

## UI Behavior

Layout:

```text
TOP BAR
------------------
Diagram | Detail
```

Top bar includes patient identity, patient selector if available, global search, status toggles, and side filters.

Diagram requirements — see **Diagram Layout — Redesign (v2)** below. Invariants that still hold:

- abstract schematic, not a literal atlas
- dark, low-glare interface appropriate for radiology workstation use
- anterior view; patient left appears on viewer right (radiological orientation)
- full figure always visible; empty regions muted, not removed
- active burden (`current + always`) controls visual emphasis; resolved is secondary

## Diagram Layout — Redesign (v2)

The first pass rendered the diagram as a **vertical stack of equal-size count cards** — each region a same-size box with `Patient R / Mid / Gen / Patient L` sub-cells. That reads as a *spreadsheet of regions*, not a person. The data mapping is correct; the spatial metaphor is missing. Replace it with an **abstract body schematic** (the standard interactive-body-map / "manikin" pattern used in pain diagrams and EHR anatomy pickers).

**Goal:** at a glance the diagram reads as a human figure (anterior view), with clinical burden shown as a **heatmap** and laterality shown **spatially** (left/right halves), not as columns of numbers.

**Why the first pass failed (do not repeat):**

- region-as-row with uniform-size cards erases body shape (torso should be large, limbs slender)
- the only spatial cue was vertical order; left/right was reduced to identical tabular sub-cells
- limbs did not flank the torso, so there was no figure to anchor on
- burden was a text badge, not a visual hotspot

**Spatial layout (body geography):**

```text
                  ┌────────┐
                  │  HEAD  │            viewer-RIGHT = patient-LEFT
                  ├────────┤
                  │  neck  │
       ┌─────┐    ╔════════╗    ┌─────┐
       │  R  │    ║ THORAX ║    │  L  │   upper extremities flank the
       │ UE  │    ║ (chest ║    │ UE  │   chest at shoulder height
       │ arm │    ║ /breast)    │ arm │
       └─────┘    ╠════════╣    └─────┘
                  ║ ABDOMEN║
                  ╠════════╣
                  ║ PELVIS ║
                  ╚════════╝
       ┌─────┐                  ┌─────┐
       │  R  │                  │  L  │   lower extremities below the
       │ LE  │                  │ LE  │   pelvis, flanking the midline
       └─────┘                  └─────┘

   Off-figure tray:  [ Unlocalized: N ]   ← never placed on the body
```

- axial column down the center: head → neck → thorax (chest + breast) → abdomen → pelvis
- upper extremities flank the thorax at shoulder height; lower extremities below the pelvis
- patient-right limb on viewer-left (radiological)
- `Unlocalized` is an off-figure tray/chip area, never placed on the body

**Encoding:**

- **Burden = fill intensity** (sequential, colorblind-safe warm ramp keyed to `current + always`). The count is a secondary label/tooltip, not the primary signal. Empty regions are muted outlines.
- **Laterality is spatial when it maps to real anatomy:** split bilateral regions into left/right halves of the shape; midline findings centered when that is anatomically meaningful. `generic_unspecified` remains metadata/detail context and must not create fake body regions such as "Upper Extremity, Unspecified Side."
- **Proportion sells the metaphor:** torso largest, head moderate, limbs slender. Uniform-size tiles were the core failure — do not reuse them.
- **Resolved findings:** a muted secondary marker (ring/dot) on the same zone, not a separate region.

**Implementation (pick one; constraints unchanged: SVG-or-CSS-grid, hand-authored, no bitmap, no canvas, no UI component library):**

- **Preferred — hand-authored SVG silhouette.** One `<path>`/`<g>` per region; `fill` driven by burden; `onClick` → existing detail pane; ARIA label per region. Use open-source body-highlighter SVGs ([react-body-highlighter](https://github.com/giavinh79/react-body-highlighter), [body-muscles](https://vulovix.github.io/body-muscles/), [react-svg-map](https://www.npmjs.com/package/react-svg-map)) as *references* for path shapes and the per-region intensity data model — author an abstract figure rather than adding a muscle-atlas dependency.
- **Acceptable v1 fallback — CSS `grid-template-areas` shaped like a body** (e.g. `". head ."` / `"rua thorax lua"` / `". abdomen ."` / `". pelvis ."` / `"rll . lll"`), each area a region tile with a heatmap background. Much better spatial correspondence than the stack; upgrade to SVG later.
- **Do not ship the stacked-card layout as the diagram.**

**Data-specific notes:**

- `Body`-bucketed fallbacks (osteoporosis → thorax/abdomen, soft tissue → thorax, upper-extremity fracture → left upper extremity) resolve to real regions and belong on the figure; only the two genuinely unlocalized findings (basal cistern, dural sinus) go to the off-figure tray.
- Keep zones **abstract** — locations are coarse (kidney vs left kidney, lung vs lower lobe), so an organ-accurate atlas would over-promise precision.

**Mobile:** scale the figure; if it gets too small, collapse to a simplified single-column body (head → torso → pelvis with limb chips) but keep the silhouette gestalt — do not revert to the card stack.

Detail pane states:

- no selection: whole-patient anatomy summary with region totals, active/resolved burden, highest-burden regions, recent positive observations, and unlocalized/unknown-location findings
- region selected: organ clusters, side breakdown, active findings first, resolved secondary
- cluster selected: exact locations and IPL finding rows
- finding selected: timeline, evidence, definition metadata, and anatomy metadata
- observation selected: exam metadata, EFL summary, report text, and evidence highlighting

Patient demographics stay in the top bar; the default detail pane should not be a generic patient card.

Finding detail must separate:

- instance data: actual location, status, observations, dates, report evidence
- definition data: description, synonyms, typical anatomy, modalities, subspecialties, etiologies, ontology codes
- anatomy data: RID, region, cluster, laterality, containment/part-of path

Missing metadata fallback:

- missing definition: show IPL finding display/code and omit definition sections gracefully
- missing anatomy: show raw location display if present, otherwise `Unlocalized`
- missing report highlight: show evidence text and warning instead of pretending it highlighted

## Evidence Highlighting

Evidence source is observation `reportText`.

Highlighting rule:

- normalize whitespace only
- search in source report Markdown/plain text
- if one match: highlight it
- if multiple matches: highlight all and mark as ambiguous
- if no match: show evidence quote and report drilldown without highlight, with a warning

No fuzzy matching in first slice.

Markdown rendering must be conservative. Do not support arbitrary unsafe HTML from report text.

## URL State

Minimal query-param state:

- `patient` is required in v1 behavior.
- `region`, `cluster`, and `finding` may be supported if cheap.
- No React Router dependency.

Missing/unknown behavior:

- missing patient: default to first generated patient and repair URL
- unknown patient: show clear load error and offer first generated patient
- unknown region/cluster/finding: clear invalid selection and show whole-patient anatomy summary

## Development Process

Use Playwright continuously for visual feedback during UI work.

Do not present the UI as ready for user review unless:

- app has been opened with Playwright
- desktop and mobile screenshots have been captured
- screenshots have been inspected
- a subagent has reviewed screenshots and judged the UI reasonable
- obvious layout, overlap, blank-state, scroll, or readability issues have been fixed

Required screenshot states before final handoff:

- desktop whole-patient state
- desktop region state
- desktop finding/evidence drilldown
- mobile whole-patient state
- mobile finding/evidence drilldown

Final delivery must include screenshot paths and a concise summary of the subagent visual review.

## Verification

Required commands/checks:

- run viewer_v2 data build
- validate generated JSON parses
- run viewer_v2 Vite build
- verify every IPL finding maps to anatomy metadata or explicit `unlocalized`
- manually verify patient load, diagram counts, filters, detail progression, definition/anatomy separation, and evidence drilldown
- use Playwright screenshots throughout development and before final handoff

Run `task test` only if shared scripts, sample assumptions, or existing test-covered behavior are changed.

Formal Playwright tests are future work after the interaction model stabilizes.

Verification performed for this pass:

- `task viewer:v2:data`
- `find viewer_v2/public/data -name '*.json' -print0 | xargs -0 -n1 jq empty`
- `npm --prefix viewer_v2 run build`
- Ad hoc anatomy/status check: all 123 IPL findings map to anatomy metadata or explicit `unlocalized`; two findings use the explicit fallback.
- Spot checks from Watch-outs / Known Data Quirks:
  - `RID1850_RID5824` (`left upper extremity`) resolves to `upper_extremity`.
  - Missing-anatomy findings are emitted as explicit generated warnings.
  - Evidence matching applies NFKC plus dash/quote folding before warning.
- Playwright screenshot pass against local Vite dev server:
  - `/tmp/viewer_v2_screenshots/desktop-whole-patient.png`
  - `/tmp/viewer_v2_screenshots/desktop-region-head.png`
  - `/tmp/viewer_v2_screenshots/desktop-finding-evidence.png`
  - `/tmp/viewer_v2_screenshots/mobile-whole-patient.png`
  - `/tmp/viewer_v2_screenshots/mobile-finding-evidence.png`
- Subagent visual review was requested on the screenshot set; blocking layout findings were fixed and a re-review was requested.

Current redesign verification:

- Replaced stacked region cards with the CSS-grid body-map fallback described above.
- Confirmed diagram zones use named active-finding chips and no longer show count-only active badges.
- Re-captured the required desktop/mobile Playwright screenshot states under `/tmp/viewer_v2_screenshots/`.
- Converted the viewer to a dark radiology-workstation theme and recaptured all required screenshot states for visual review.
- Reworked the mobile anatomy layout after adversarial review so it keeps the three-column radiology-orientation body-map, keeps anatomy before detail, removes explicit "viewer right" instructional text, uses `N more` overflow controls, and keeps active-finding names legible in anatomy sections.
- Final subagent visual review verdict: ready for user review, with no blocking issues. Remaining notes are polish only: mobile anatomy/header density, aggressive wrapping in small regions, and the orange unlocalized warning drawing strong attention as a warning state.
- Follow-up layout adjustments requested after review: pelvis should sit directly under abdomen, lower extremities should sit off to either side below the pelvis, active overflow controls should read as concise `N more` expanders, and the unlocalized tray should be omitted when the current filter state has no unlocalized findings.
- Follow-up interaction corrections requested after review: remove global side filters at this level, keep side as a local anatomy-cell selection only, show the selected lateral cell label in the detail pane, avoid carrying a lateral selection when a non-lateral region is clicked, show more findings before overflow when a zone has a large burden, and rename/detail region cluster lists as "sub-regions" with their findings grouped underneath each sub-region heading.
- Follow-up active-finding correction: collapsed anatomy zones should show more current findings wherever there are many findings, not only in the chest. Always-present findings should be available but collapsed by default.
- Follow-up anatomy correction: remove the fake "Upper Extremity, Unspecified Side" body-map tile. Generic/unspecified laterality should stay in finding metadata/detail rows, not appear as a standalone anatomy region.
- Follow-up density correction: anatomy chips should use color accents to distinguish `current` from `always`, not inline status text. Show current findings by default; keep always-present findings behind an expandable `N always` control. Hidden current findings use an `N more active` expander.
- Follow-up compact-label correction: dense anatomy chips and list rows should use `viewer_v2/finding_compact_names.json` when the entry's authored `name` still matches the IPL full display name for that code. Full finding names remain available in titles, ARIA labels, and detail headers. Stale compact-name entries fall back to the full name and produce generated warnings.

## Future Enhancements

- upstream anatomy compatibility reconciliation in IPL assembler
- more precise organ/region mini-maps
- fuzzy and multi-span evidence matching
- full URL state restoration
- multi-patient support beyond MRN0000001
- multi-exam comparison and longitudinal trajectory views
- optional “ever positive” and “show negatives on diagram” modes
- formal Playwright smoke and screenshot regression tests
- keyboard navigation, focus management, and ARIA polish

## Assumptions

- First complete target is MRN0000001 from `sample_data/example2`.
- Generated `viewer_v2/public/data/` files are committed.
- `viewer_v2` deploys separately from current `viewer/`.
- Existing `viewer/` remains intact.
- No backend/API integration is included in the first slice.

## Watch-outs / Known Data Quirks

Grounded in the corrected `sample_data/example2` data and its current generated 70 distinct location RIDs. The first four come straight from the real data and will not be obvious until they bite.

1. **`region` is `"Body"` for the coarse region-level locations — the diagram will mis-bucket them.** `abdomen` (RID56), `thorax` (RID1243), and `left upper extremity` (RID1850_RID5824) carry `region = "Body"`, not their obvious region. These are exactly the exam-region fallbacks in the data: generalized osteoporosis → thorax/abdomen, soft tissue mass → thorax, upper extremity fracture → left upper extremity. Deriving the diagram region purely from the `region` field drops them into a phantom "Body" bin. Add a curated override (or resolve region from the structure name / containment path), and keep a visible "whole-body / unbucketed" affordance so nothing silently disappears.

   Implemented: `scripts/build_viewer_v2_data.py` maps these `Body` rows into presentation regions from the resolved display name, including upper/lower extremity fallbacks.

2. **Take laterality straight from the ontology `laterality` enum; do not parse display names to assign sides.** Map `generic → generic_unspecified`, `left → left`, `right → right`, `nonlateral → midline_nonlateral`. Note that some structures whose *names* contain "left"/"right" are intentionally **nonlateral** — e.g. `lower lobe of right lung` (RID1315) is its own distinct structure, not the right half of a paired organ, so it is correctly `nonlateral`. Do not coerce such structures into the `left`/`right` buckets. Product consequence: a strict side filter will (correctly) not surface right-lower-lobe findings under "right" — if that UX is undesirable, solve it in filter *semantics* (e.g. an explicit "named-side" option), never by mutating laterality. The 13 `generic`-laterality structures (kidney, adrenal gland, lung, pleural space, pulmonary hilum, …) are genuinely unspecified-side findings and must not fold into left/right counts.

3. **The data deliberately contains generic-vs-specific fragmentation for the same finding code — do not "fix" it.** Anatomic-compatibility reconciliation (Step 3b in `anatomic-location-efl-ipl.md`) is intentionally not done, so one code legitimately appears as multiple `finding.id` rows at different granularities: pneumonia at `lung` *and* `lower lobe of right lung`; hydronephrosis at `kidney`; renal cyst at `left kidney`; generalized osteoporosis at `thorax` / `abdomen` / `thoracic vertebral column` across exams. Use the **cluster layer** to group these visually (e.g. a lung cluster holding both rows) without merging finding rows.

4. **`reportText` is shared across findings and contains unicode — exact-match needs more than whitespace normalization.** One report sentence often maps to several findings (e.g. "Urinary bladder, seminal vesicles, and prostate gland are unremarkable." → bladder + prostate + seminal-vesicle), so expect N-findings-to-1-span, not 1:1. And `reportText` carries unicode (en-dash `–` U+2013 in "4–5 mm"; source `.md` uses `**bold**` section headers). Whitespace-only normalization will silently miss dash/smart-quote mismatches and route them to the "no match → warning" path. Add unicode normalization (NFKC + dash/quote folding) before declaring no-match.

   Implemented: generator warnings and browser highlighting now use NFKC plus dash/quote folding before whitespace normalization. This remains conservative exact matching after normalization, not fuzzy matching.

5. **Key on `finding.id`, never `finding_type_code`.** Now heavily true: aortic aneurysm, abdominal lymphadenopathy, soft tissue mass, and pneumonia each appear 2–4× with different locations. Any accidental group-by-code (generator or UI) collapses distinct problems.

6. **`anatomy_clusters.json` is described as both editable input and generated output — resolve the contradiction.** Decide whether it is a hand-authored seed the generator augments, or a generated default the human edits, and define the merge/precedence so a rebuild never clobbers human cluster edits.

   Resolved: `viewer_v2/anatomy_clusters.json` is the hand-authored editable source. `viewer_v2/public/data/anatomy_clusters.json` is generated output that merges the source config with per-location cluster assignments.

7. **Resolve RIDs with `AnatomicLocationIndex.get(rid)` (sync), not `.search` (async).** The IPL already carries RIDs, so it is pure metadata lookup — do not reintroduce semantic search. Composite/sided RIDs (`RID9557_RID5824`, `RID1850_RID5824`, `RID6383_RID9080`, …) are real ontology rows and resolve via `.get()`. The build also requires the DuckDB at `~/Library/Application Support/anatomic-locations/anatomic_locations.duckdb`; make its presence an explicit preflight check.

8. **The `unlocalized` path is exercised by real data — build it in slice 1, not later.** Two observations (`basal cistern effacement`, `dural sinus thrombosis`) have no `anatomicLocation` and never will (absent from the ontology). The whole-patient "unlocalized findings" affordance must actually exist in the first slice.

   Implemented: these findings are displayed under the Unlocalized fallback and emitted as explicit `missing_anatomy` warnings.

9. **Definition-metadata coverage is ~97/98 codes** — at least one IPL finding has no `finding_display_info.json` entry, so the graceful "omit definition sections" path fires on real data. Confirm the join key format (`finding_display_info.json` is keyed by OIFM code; verify it matches `finding_type_code` exactly).

10. **Generated `viewer_v2/public/data/` is a committed snapshot of `sample_data/example2`** and drifts the moment the EFLs change (as they just did). Add a note — or a cheap `task`/CI check — that the data build must be re-run after any `sample_data` edit so the committed data does not go stale.

   Implemented: `task viewer:v2:check` regenerates the data and runs `git diff --exit-code -- viewer_v2/public/data`.
