# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Imaging Problem List project is a structured representation system for patient imaging findings. It organizes findings by type along with references to where they appear in patient imaging exams.

### Key Data Structures

1. **Exam Finding List (EFL)**: Individual report findings from a single imaging exam
   - FHIR representation: DiagnosticReport containing Observation objects
   - Each Observation has a finding code and components with attributes (presence/absence, changes)
   - Sample format: `sample_data/sample_efl.json`

2. **Imaging Problem List (IFL)**: Aggregated findings across a patient's entire imaging history
   - FHIR representation: Report containing Condition objects
   - Each Condition references Observations documenting which exams show the finding
   - Includes time course tracking across multiple exams

## Data Standards

- **FHIR**: Primary data format for medical records interchange
- **LOINC codes**: Used for exam type identification
- **Finding codes**: Use OIFM_GMTS_* format (e.g., OIFM_GMTS_016552 for urinary tract calculus)
- **Attribute codes**: Use OIFMA_GMTS_* format for finding attributes
- **Code lookup**: Finding codes and their descriptions can be looked up at https://raw.githubusercontent.com/openimagingdata/findingmodels/refs/heads/main/ids.json

## Sample Data

- `sample_data/sample_efl.json`: Example Exam Finding List structure
- `sample_data/powerscribe-fhir.json`: FHIR DiagnosticReport from PowerScribe radiology reporting system

## Schema Reference

The EFL schema is referenced at: `https://github.com/openimagingdata/imaging-problem-list/schema/exam-problem-list-schema.json`