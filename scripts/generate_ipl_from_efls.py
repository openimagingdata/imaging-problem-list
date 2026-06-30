#!/usr/bin/env python3
"""
Generate IPL (Imaging Problem List) JSON file from EFL files.

This script reads multiple EFL JSON files and aggregates them into a single
IPL that shows all findings across a patient's imaging history.

Usage:
    python generate_ipl_from_efls.py <efl_directory> <output_file> [--patient-name NAME]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def generate_ipl(efl_dir: str, output_file: str, patient_name: str = "John Doe"):
    """
    Generate IPL JSON from EFL files.

    Args:
        efl_dir: Directory containing EFL JSON files
        output_file: Path to write IPL JSON file
        patient_name: Patient name for the IPL
    """
    efl_path = Path(efl_dir)
    if not efl_path.exists():
        raise ValueError(f"Directory not found: {efl_dir}")

    # Find all EFL JSON files
    efl_files = sorted(efl_path.glob("*_efl.json"))
    if not efl_files:
        raise ValueError(f"No EFL files found in {efl_dir}")

    print(f"Found {len(efl_files)} EFL files")

    # Group findings by finding type (OIFM code) AND anatomic location.
    # A finding code at two distinct anatomic locations (e.g. abdominal vs.
    # hilar lymphadenopathy) becomes two separate IPL entries. Observations
    # without an anatomic location group under locationId = None.
    # Key: (finding_code, location_id)
    # Structure: {key: {finding_code, finding_description, anatomic_location, observations: []}}
    findings_by_type: dict[tuple[str, str | None], dict[str, Any]] = defaultdict(lambda: {
        'finding_code': None,
        'finding_description': None,
        'anatomic_location': None,
        'observations': []
    })

    # Patient info from first EFL
    patient_info = None

    # Process each EFL file (already sorted chronologically by filename)
    for efl_file in efl_files:
        print(f"  Processing: {efl_file.name}")

        with open(efl_file) as f:
            efl = json.load(f)

        # Get patient info from first file
        if patient_info is None:
            patient_info = efl['patientInfo']

        # Extract exam info
        report_id = efl['diagnosticReportId']
        exam_info = efl['examInfo']
        # Extract date only (YYYY-MM-DD) from datetime
        exam_date = exam_info['studyDateTime'].split('T')[0]
        exam_type_code = exam_info['studyLoincCode']
        exam_type_display = exam_info['studyDescription']

        # Process each finding in order (preserving order within exam)
        for finding in efl['findings']:
            finding_code = finding['findingCode']
            finding_description = finding['findingDescription']
            observation_id = finding['observationId']
            text = finding.get('reportText', '')
            anatomic_location = finding.get('anatomicLocation')
            location_id = anatomic_location['locationId'] if anatomic_location else None

            # Get presence value from attributes
            presence = None
            for attr in finding['attributes']:
                if attr['attributeDescription'] == 'presence':
                    presence = attr['attributeValueDescription']
                    break

            if presence is None:
                print(f"    Warning: No presence attribute for {observation_id}")
                continue

            # Group by finding type (OIFM code) AND anatomic location.
            # Multiple instances from same exam are added as separate observations.
            group_key = (finding_code, location_id)
            group = findings_by_type[group_key]
            if group['finding_code'] is None:
                group['finding_code'] = finding_code
                group['finding_description'] = finding_description
                group['anatomic_location'] = anatomic_location

            # Add observation (includes both present and absent)
            observation = {
                'report_id': report_id,
                'observation_id': observation_id,
                'exam_date': exam_date,
                'exam_type_code': exam_type_code,
                'exam_type_display': exam_type_display,
                'presence': presence
            }

            # Carry the observation's own anatomic location, if any
            if anatomic_location:
                observation['anatomicLocation'] = anatomic_location

            # Only add reportText if it exists and is non-empty
            if text:
                observation['reportText'] = text

            group['observations'].append(observation)

    # Build IPL structure
    ipl = {
        "$schema": "http://example.com/schemas/imaging_problem_list.json",
        "patient": {
            "id": patient_info['patientIdentifier'],
            "name": patient_name,
            "dob": patient_info['patientDOB']
        },
        "findings": []
    }

    # Add findings sorted by (finding code, location id). One finding code can
    # now appear under multiple locations, so downstream consumers must key on
    # the IPL finding's `id`, not `finding_type_code`.
    def _sort_key(item):
        (finding_code, location_id), _data = item
        return (finding_code, location_id or "")

    for idx, (_group_key, finding_data) in enumerate(
        sorted(findings_by_type.items(), key=_sort_key), start=1
    ):
        # Sort observations chronologically by exam date
        sorted_observations = sorted(finding_data['observations'], key=lambda x: x['exam_date'])

        ipl_finding = {
            "id": f"ipl-finding-{idx:03d}",
            "finding_type_code": finding_data['finding_code'],
            "finding_type_display": finding_data['finding_description'],
            "anatomicLocation": finding_data['anatomic_location'],
            "observations": sorted_observations
        }
        ipl['findings'].append(ipl_finding)

    # Write IPL file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(ipl, f, indent=2)

    print()
    print(f"Generated IPL with {len(ipl['findings'])} unique finding types")
    total_observations = sum(len(f['observations']) for f in ipl['findings'])
    print(f"Total observations: {total_observations}")
    print(f"Written to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate IPL JSON file from EFL files"
    )
    parser.add_argument(
        "efl_directory",
        help="Directory containing EFL JSON files"
    )
    parser.add_argument(
        "output_file",
        help="Path to write IPL JSON file"
    )
    parser.add_argument(
        "--patient-name",
        default="John Doe",
        help="Patient name for the IPL (default: John Doe)"
    )

    args = parser.parse_args()

    try:
        generate_ipl(args.efl_directory, args.output_file, args.patient_name)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
