#!/usr/bin/env python3
"""
Generate finding_display_info.json from enriched_findings.json.

This script processes the enriched findings data and creates a simplified
structure optimized for popover display in the viewer application.

Usage:
    python generate_finding_display_info.py
"""

import json
from pathlib import Path

# Subspecialty code expansions
SUBSPECIALTY_NAMES = {
    "AB": "Abdominal Imaging",
    "BR": "Breast Imaging",
    "CA": "Cardiac Imaging",
    "CH": "Chest Imaging",
    "ER": "Emergency Radiology",
    "GI": "Gastrointestinal",
    "GU": "Genitourinary",
    "HN": "Head & Neck",
    "IR": "Interventional Radiology",
    "MK": "Musculoskeletal",
    "NR": "Neuroradiology",
    "NM": "Nuclear Medicine",
    "OB": "OB/GYN",
    "OI": "Oncologic Imaging",
    "PD": "Pediatric Radiology",
    "VI": "Vascular Imaging",
}


def expand_subspecialty(code: str) -> str:
    """Expand subspecialty code to full name."""
    return SUBSPECIALTY_NAMES.get(code, code)


def format_etiology(etiology: str) -> str:
    """Format etiology string for display (e.g., 'inflammatory:infectious' -> 'Inflammatory (infectious)')."""
    if ":" in etiology:
        main, sub = etiology.split(":", 1)
        return f"{main.replace('-', ' ').title()} ({sub.replace('-', ' ')})"
    return etiology.replace("-", " ").title()


def process_finding(code: str, data: dict) -> dict:
    """Process a single finding entry into display format."""
    result = {
        "code": code,
        "name": data.get("name", ""),
        "description": data.get("description", ""),
    }

    # Synonyms - join as comma-separated string
    synonyms = data.get("synonyms", [])
    if synonyms:
        result["synonyms"] = ", ".join(synonyms)

    # Anatomic location with RadLex ID
    location = data.get("anatomic_location", {})
    if location:
        result["location"] = {
            "text": location.get("text", ""),
            "radlex_id": location.get("id", ""),
        }

    # Body regions - join as comma-separated string
    regions = data.get("body_regions", [])
    if regions:
        result["regions"] = ", ".join(regions)

    # Modalities - join as comma-separated string
    modalities = data.get("modalities", [])
    if modalities:
        result["modalities"] = ", ".join(modalities)

    # Subspecialties - expand codes and join
    subspecialties = data.get("subspecialties", [])
    if subspecialties:
        expanded = [expand_subspecialty(s) for s in subspecialties]
        result["subspecialties"] = ", ".join(expanded)

    # Etiologies - format and join
    etiologies = data.get("etiologies", [])
    if etiologies:
        formatted = [format_etiology(e) for e in etiologies]
        result["etiologies"] = ", ".join(formatted)

    # Ontology codes - keep full structure for display
    ontology_codes = data.get("ontology_codes", [])
    if ontology_codes:
        result["ontology_codes"] = [
            {
                "system": oc.get("system", ""),
                "code": oc.get("code", ""),
                "display": oc.get("display", ""),
            }
            for oc in ontology_codes
        ]

    # Attributes
    attributes = data.get("attributes", [])
    if attributes:
        result["attributes"] = ", ".join(attributes)

    return result


def main():
    # Paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    input_path = project_root / "viewer" / "data" / "enriched_findings.json"
    output_path = project_root / "viewer" / "data" / "finding_display_info.json"

    # Load enriched findings
    print(f"Loading enriched findings from {input_path}")
    with open(input_path, "r") as f:
        enriched = json.load(f)

    print(f"Processing {len(enriched)} findings...")

    # Process each finding
    display_info = {}
    for code, data in enriched.items():
        display_info[code] = process_finding(code, data)

    # Write output
    print(f"Writing display info to {output_path}")
    with open(output_path, "w") as f:
        json.dump(display_info, f, indent=2)

    print(f"Done! Generated display info for {len(display_info)} findings.")


if __name__ == "__main__":
    main()
