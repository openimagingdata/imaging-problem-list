# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Imaging Problem List project is a structured representation system for patient imaging findings. It organizes findings by type along with references to where they appear in patient imaging exams.

This is primarily a data specification and documentation project, not a traditional code repository. The focus is on defining JSON structures and providing examples.

## Key Data Structures

### 1. Exam Finding List (EFL)
Individual report findings from a single imaging exam.

**Structure:**
- `diagnosticReportId`: Unique identifier for the report
- `patientInfo`: Patient identifier and DOB
- `examInfo`: Study details including LOINC code for exam type
- `findings`: Array of observations, each with:
  - `observationId`: Unique ID for this finding instance
  - `findingCode`: OIFM code for the finding type
  - `findingDescription`: Human-readable finding name
  - `attributes`: Array of attributes (typically presence/absence)

**FHIR Representation:** DiagnosticReport containing Observation objects. Each Observation has a finding code and components with attributes (presence/absence, changes from prior).

**Key Concept:** The same finding type may appear multiple times in one exam (e.g., multiple kidney stones). Each instance gets a separate entry with its own `observationId`.

### 2. Imaging Problem List (IPL)
Aggregated findings across a patient's entire imaging history.

**Structure:**
- `patient`: Patient demographics
- `findings`: Array of aggregated findings, each with:
  - `finding_type_code`: OIFM code for this type of finding
  - `finding_type_display`: Human-readable name
  - `observations`: Array of all times this finding was documented, each containing:
    - Reference to the source report and observation
    - Exam date and type
    - Presence/absence status

**FHIR Representation:** Report containing Condition objects (labeled with the finding identifier), where each Condition also contains Observation objects documenting which DiagnosticReports the finding appeared in.

**IPL Generation:** The IPL aggregates multiple EFLs. Multiple observations of the same finding type from one EFL (e.g., three kidney stones) are grouped together under one IPL finding entry, preserving references to each individual observation.

## Data Standards

- **FHIR**: Primary data format for medical records interchange
- **LOINC codes**: Used for exam type identification (e.g., "72133-2" = CT Abdomen and Pelvis Without Contrast)
- **Finding codes**: Use OIFM_XXXX_* format
  - Example: OIFM_GMTS_016552 = urinary tract calculus
  - Example: OIFM_MSFT_430810 = coronary artery calcifications
- **Attribute codes**: Use OIFMA_XXXX_* format for finding attributes
  - Typically used for presence (`.1` = present, `.0` = absent)
- **Code lookup**: Finding codes and their descriptions can be looked up at https://raw.githubusercontent.com/openimagingdata/findingmodels/refs/heads/main/ids.json

## Repository Structure

```
sample_data/
  example1/          # Complete example showing EFL-to-IPL transformation
    sample_efl.json         # EFL for abdomen/pelvis CT
    chest_ct_efl.json       # EFL for chest CT
    sample_ipl.json         # IPL aggregating both EFLs
    powerscribe-fhir.json   # Original FHIR DiagnosticReport (abdomen/pelvis)
    chest-ct-fhir.json      # Original FHIR DiagnosticReport (chest)
  example2/
    findings_with_oifm_ids.xlsx  # Working data
```

## IPL Viewer Application

The `viewer/` directory contains a single-page web application for visualizing imaging problem lists.

### Technology Stack
- **HTML5 + Alpine.js**: Reactive UI without build step
- **Tailwind CSS + Flowbite**: Styling and UI components (via CDN)
- **No build required**: Opens directly in browser or via simple HTTP server

### Key Features
1. **Three-Level Navigation**: IPL → EFL → Report
   - IPL view: Shows aggregated findings across all exams
   - EFL view: Shows findings from a single exam
   - Report view: Displays raw report text

2. **Temporal Status Tracking**: Automatically computes finding status based on observation history:
   - **Present** (green): Most recent observation shows finding present
   - **Resolved** (amber): Was present in past, but most recent observation shows absent
   - **Not Present/Ruled Out** (gray): All observations show absent (never present)

3. **Smart Filtering**:
   - By status: All, Currently Present, Resolved, Ever Present, Ruled Out
   - By body region: Chest, Abdomen, Pelvis/GU, Musculoskeletal, Head/Neck

4. **Body Region Inference**: Automatically categorizes findings by matching keywords in finding descriptions (see `BODY_REGION_MAP` in `viewer/app.js:1-8`)

5. **Multi-Patient Support**: Switch between patients via dropdown or URL parameter (`?patient=patient-mrn0000001`)

### Data Directory Structure

The viewer expects data organized as:
```
data/
  patients.json              # Manifest listing all patients
  patients/
    <patient-id>/
      patient.json           # Patient metadata (demographics, exam count)
      ipl.json              # Imaging Problem List for this patient
      exams/
        <report-id>/
          efl.json          # Exam Finding List
          report.txt        # Raw report text
```

### Running the Viewer
```bash
cd viewer
python3 -m http.server 8000
# Then open http://localhost:8000
```

### Important Implementation Details

- **Status computation** (`viewer/app.js:101-124`): Sorts observations by date and checks most recent presence status
- **Body region mapping** (`viewer/app.js:1-8`): Uses keyword matching on finding descriptions
- **Dark mode first**: Designed for radiologists, defaults to dark theme with localStorage persistence
- **Finding aggregation**: When viewing a finding, clicks load the most recent exam containing that finding

## Schema Reference

The EFL schema is referenced in the sample files as: `https://github.com/openimagingdata/imaging-problem-list/schema/exam-problem-list-schema.json`, but it doesn't exist yet.
- We set up a .venv using uv; you should use that rather than using python3 directly.