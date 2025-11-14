# Copilot Instructions for `imaging-problem-list`

These instructions guide AI coding agents working in this repo. Keep answers concrete and tied to this project’s data model and viewer.

## Big Picture

- This project defines and visualizes an **Imaging Problem List (IPL)** built from **Exam Finding Lists (EFLs)**.
- Clinical data lives in JSON under `data/` and `sample_data/`; the browser viewer in `viewer/` renders IPL/EFLs for one or more patients.
- FHIR, LOINC, and custom OIFM/OIFMA codes are central; do not invent new naming schemes.

## Documentation Pointers

- `README.md`: domain overview plus FHIR framing for EFL/IPL.
- `CLAUDE.md`: agent workflow guidance and schema detail (use this when you need structured descriptions of EFL/IPL fields).
- `.github/copilot-instructions.md`: coding conventions, viewer rules, and workflow expectations (you’re here).
- `viewer/README.md`: viewer UX, data loading expectations, and filesystem layout for real/sample patients.

## Core Data Structures

- **Exam Finding List (EFL)**
  - Per-exam list of findings (present/absent, change from prior, etc.).
  - Example: `sample_data/sample_efl.json` and `viewer/data/patients/.../exams/*/efl.json`.
  - Conceptual spec: `README.md` and `CLAUDE.md` (EFL section, DiagnosticReport + Observation model).
- **Imaging Problem List (IPL/IFL)**
  - Per-patient aggregation of findings across all exams with temporal status.
  - Example: `data/patients/patient-mrn0000001/ipl.json`.
  - Conceptual spec: `README.md` (Imaging Problem List section) and `CLAUDE.md`.
- **Patient manifest + metadata**
  - `data/patients.json` lists patients and basic metadata.
  - Each patient folder under `data/patients/` contains `patient.json`, `ipl.json`, and an `exams/` tree with `efl.json` + `report.txt`.

## Viewer Architecture (`viewer/`)

- Single-page static app: `viewer/index.html` + `viewer/app.js` (no build step).
- UI stack:
  - Tailwind CSS + **Flowbite v4.0** via CDN for styling/components.
  - Alpine.js via CDN for state and interactivity. **When adding new UI behavior, implement it as Alpine.js state/methods (e.g., inside `iplApp()` with `x-data`, `x-show`, `x-on`, `x-model`) instead of standalone DOM-manipulating JavaScript.**
- For UI elements, use Flowbite v4 components **exactly as defined in the official documentation** (https://flowbite.com) and minimize custom Tailwind utility classes beyond light layout tweaks.
- The app expects the `data/` directory to be served at the same root as `viewer/` (e.g. repo root via `python3 -m http.server`). When adding features, preserve this relative path assumption.

## Running and Debugging

- **Run viewer locally** (preferred from repo root):
  ```bash
  cd viewer
  python3 -m http.server 8000
  # open http://localhost:8000
  ```
- There is **no bundler, test runner, or backend** in this repo; avoid adding complex tooling unless explicitly requested.
- When changing `app.js`, prefer small, composable functions that operate on the IPL/EFL JSON structures instead of introducing frameworks.

## Domain Conventions

- **Codes and vocabularies**
  - Exam types: LOINC codes.
  - Finding codes: `OIFM_GMTS_*` (e.g., `OIFM_GMTS_016552`).
  - Attribute codes: `OIFMA_GMTS_*`.
  - Code lookup: `https://raw.githubusercontent.com/openimagingdata/findingmodels/refs/heads/main/ids.json` (do not hard-code large copies of this file into the repo).
- **FHIR mapping** (do not re-invent):
  - EFL ↔ FHIR `DiagnosticReport` + `Observation`s.
  - IPL ↔ FHIR `Report` + `Condition`s referencing observations.
- When synthesizing sample data, follow existing examples in `sample_data/` and `data/patients/` for field names and structure.

## Viewer Behavior & Patterns

- The viewer implements a **three-level navigation** pattern: patient IPL → exam EFL → raw report.
- Finding status categories:
  - Currently present, resolved, and never-present/ruled-out (see `viewer/README.md` for definitions). Keep new logic aligned with these categories.
- Body region grouping is heuristic, based on keywords (chest/abdomen/pelvis–GU/musculoskeletal/head–neck). When modifying or extending this logic, mirror the existing keyword-style approach instead of introducing heavy NLP.

## When Modifying or Adding Code

- Keep the project **build-less**: use plain JS/HTML/CSS in `viewer/` and JSON for data.
- Prefer **Alpine.js patterns over custom imperative JS**:
  - Extend the existing `iplApp()` Alpine component in `viewer/app.js` for new state, computed properties, and actions.
  - Bind interactivity in `viewer/index.html` with Alpine directives (`x-data`, `x-init`, `x-on`, `x-model`, `x-show`, `x-for`) rather than adding new script tags or direct DOM querying.
- Favor clarity over abstraction in `app.js`; this repo is a reference implementation, not a framework.
- When adding new example patients or exams, ensure:
  - `data/patients.json` is updated.
  - The on-disk structure matches the pattern documented in `viewer/README.md`.
- If you introduce new utility functions for IPL/EFL processing, put them in `viewer/app.js` and design them around the existing JSON shape from `data/` and `sample_data/`.

## Good Entry Points for Agents

- To understand domain and schema: `README.md`, `CLAUDE.md`, and `sample_data/sample_efl.json`.
- To understand UI behavior and data flow: `viewer/README.md`, `viewer/index.html`, and `viewer/app.js`.
- To see real data layout: `data/patients.json` and `data/patients/patient-mrn0000001/`.
