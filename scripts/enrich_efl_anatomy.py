#!/usr/bin/env python3
"""
Enrich EFL (Exam Finding List) JSON files with anatomic-location codes.

For each EFL file, each finding/observation is adapted into an internal
``Finding`` (with ``location=None``) and run through the production coding
pipeline (``run_coding``). The pipeline's location-coding flow infers the
anatomic location from the finding's report text and exam context, searches the
``anatomic-locations`` index, and selects a standardized location. The selected
location's RID id + display name are written back onto each observation as an
``anatomicLocation`` object.

The pass is additive and idempotent: re-running recomputes and overwrites
``anatomicLocation``. A review CSV of every location decision (including
candidates and unresolved reasons) is written for human spot-checking.

Usage:
    uv run python scripts/enrich_efl_anatomy.py <efl_directory> [--model MODEL]
        [--reasoning LEVEL] [--review-csv PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any

from finding_extractor.coding.runtime import run_coding
from finding_extractor.models import (
    ExamInfo,
    ExtractedReportFindings,
    Finding,
    Modality,
)

# Study-description prefix -> Modality literal. The example2 study descriptions
# start with the modality token (e.g. "CT Abdomen and Pelvis WO contrast").
_MODALITY_PREFIXES: dict[str, Modality] = {
    "CT": "CT",
    "MR": "MR",
    "US": "US",
    "XR": "XR",
    "NM": "NM",
    "PET": "PET",
    "MG": "MG",
    "DXA": "DXA",
}

_VALID_PRESENCE = {"present", "absent", "indeterminate", "possible"}


def _derive_modality(study_description: str) -> Modality | None:
    """Best-effort modality from the leading token of the study description."""
    first = study_description.strip().split(" ", 1)[0].upper()
    return _MODALITY_PREFIXES.get(first)


def _presence_of(finding: dict[str, Any]) -> str | None:
    """Pull the presence value from a finding's attributes list."""
    for attr in finding.get("attributes", []):
        if attr.get("attributeDescription") == "presence":
            value = attr.get("attributeValueDescription")
            if value in _VALID_PRESENCE:
                return value
    return None


def _exam_info_from_efl(efl: dict[str, Any]) -> ExamInfo:
    """Build an ExamInfo from an EFL payload's examInfo block."""
    exam_info_raw = efl.get("examInfo", {})
    study_description = exam_info_raw.get("studyDescription", "")
    return ExamInfo(
        study_description=study_description,
        modality=_derive_modality(study_description),
    )


def _finding_from_entry(entry: dict[str, Any], presence: str) -> Finding:
    report_text = entry.get("reportText") or entry.get("findingDescription", "")
    return Finding(
        finding_name=entry.get("findingDescription", ""),
        presence=presence,  # type: ignore[arg-type]
        location=None,
        report_text=report_text,
    )


def _assign_slots(efl_findings: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """Assign each codeable finding to a slot keyed by finding-name multiplicity.

    ``run_coding`` groups location coding by finding name when ``location`` is
    null, so two observations of the same finding at different sites would
    collapse onto a single location. To avoid that, we spread repeated finding
    names across slots: the Nth occurrence of a given finding name goes to slot
    N. Within a slot no finding name repeats, so every observation is coded from
    its own report text. Returns ``(efl_index, slot, presence)`` triples.
    """
    seen: dict[str, int] = {}
    assignments: list[tuple[int, int, str]] = []
    for idx, entry in enumerate(efl_findings):
        presence = _presence_of(entry)
        if presence is None:
            print(f"    Warning: no presence attribute for {entry.get('observationId')}; skipping")
            continue
        name = entry.get("findingDescription", "")
        slot = seen.get(name, 0)
        seen[name] = slot + 1
        assignments.append((idx, slot, presence))
    return assignments


def _primary_location(finding: Finding) -> Any | None:
    """First coded LocationCode for a finding, or None."""
    bundle = finding.coding
    if bundle is None:
        return None
    for code in bundle.location_codes:
        if code.status == "coded" and code.location_id:
            return code
    return None


def _first_location_code(finding: Finding) -> Any | None:
    """First LocationCode of any status (for review reporting)."""
    bundle = finding.coding
    if bundle is None or not bundle.location_codes:
        return None
    return bundle.location_codes[0]


def _insert_anatomic_location(entry: dict[str, Any], location_id: str, location_display: str) -> dict[str, Any]:
    """Return a copy of the finding entry with anatomicLocation inserted before reportText."""
    anatomic = {"locationId": location_id, "locationDisplay": location_display}
    rebuilt: dict[str, Any] = {}
    inserted = False
    for key, value in entry.items():
        if key == "reportText" and not inserted:
            rebuilt["anatomicLocation"] = anatomic
            inserted = True
        rebuilt[key] = value
    if not inserted:
        rebuilt["anatomicLocation"] = anatomic
    return rebuilt


async def enrich_file(
    efl_path: Path,
    *,
    model: str | None,
    reasoning: str | None,
    review_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    """Enrich a single EFL file in place. Returns (localized_count, total_count)."""
    efl = json.loads(efl_path.read_text())
    report_id = efl.get("diagnosticReportId", "")
    exam_info = _exam_info_from_efl(efl)
    findings_list = efl["findings"]

    assignments = _assign_slots(findings_list)
    # Group codeable findings into slots so no finding name repeats within a
    # single run_coding call (see _assign_slots).
    slots: dict[int, list[tuple[int, str]]] = {}
    for efl_idx, slot, presence in assignments:
        slots.setdefault(slot, []).append((efl_idx, presence))

    # efl_index -> coded Finding, harvested across slot calls.
    coded_by_idx: dict[int, Finding] = {}
    for slot in sorted(slots):
        members = slots[slot]
        extraction = ExtractedReportFindings(
            exam_info=exam_info,
            findings=[_finding_from_entry(findings_list[i], p) for i, p in members],
        )
        result = await run_coding(extraction, model=model, reasoning=reasoning)
        for (efl_idx, _presence), coded in zip(members, result.extraction.findings, strict=True):
            coded_by_idx[efl_idx] = coded

    localized = 0
    for efl_idx, _slot, _presence in assignments:
        entry = findings_list[efl_idx]
        # Drop any pre-existing anatomicLocation so the pass is idempotent.
        entry.pop("anatomicLocation", None)
        coded = coded_by_idx[efl_idx]

        primary = _primary_location(coded)
        any_code = _first_location_code(coded)

        if primary is not None:
            findings_list[efl_idx] = _insert_anatomic_location(
                entry, primary.location_id, primary.location_name or ""
            )
            localized += 1

        review_rows.append(
            {
                "efl_file": efl_path.name,
                "diagnosticReportId": report_id,
                "observationId": entry.get("observationId", ""),
                "findingDescription": entry.get("findingDescription", ""),
                "presence": _presence_of(entry) or "",
                "reportText": entry.get("reportText", ""),
                "selected_rid": primary.location_id if primary else "",
                "selected_display": (primary.location_name or "") if primary else "",
                "method": (any_code.method if any_code else "unresolved"),
                "unresolved_reason": (any_code.reason if any_code else "") or "",
                "candidates": "; ".join(
                    f"{c.location_id}:{c.location_name}"
                    for c in (any_code.candidates if any_code else [])
                ),
            }
        )

    efl_path.write_text(json.dumps(efl, indent=2) + "\n")
    return localized, len(assignments)


async def enrich_directory(
    efl_dir: Path,
    *,
    model: str | None,
    reasoning: str | None,
    review_csv: Path,
) -> None:
    efl_files = sorted(efl_dir.glob("*_efl.json"))
    if not efl_files:
        raise ValueError(f"No EFL files found in {efl_dir}")

    print(f"Found {len(efl_files)} EFL files in {efl_dir}")
    review_rows: list[dict[str, Any]] = []
    total_localized = 0
    total_count = 0
    for efl_path in efl_files:
        print(f"  Coding: {efl_path.name}")
        localized, count = await enrich_file(
            efl_path, model=model, reasoning=reasoning, review_rows=review_rows
        )
        print(f"    localized {localized}/{count}")
        total_localized += localized
        total_count += count

    review_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "efl_file",
        "diagnosticReportId",
        "observationId",
        "findingDescription",
        "presence",
        "reportText",
        "selected_rid",
        "selected_display",
        "method",
        "unresolved_reason",
        "candidates",
    ]
    with review_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)

    print()
    print(f"Localized {total_localized}/{total_count} observations across {len(efl_files)} files")
    print(f"Review CSV written to: {review_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich EFL files with anatomic-location codes")
    parser.add_argument("efl_directory", help="Directory containing *_efl.json files")
    parser.add_argument("--model", default=None, help="Coding model override (default: config)")
    parser.add_argument(
        "--reasoning",
        default=None,
        choices=["none", "minimal", "low", "medium", "high"],
        help="Reasoning effort level",
    )
    parser.add_argument(
        "--review-csv",
        default="extracts/anatomy_enrichment_review.csv",
        help="Path for the review CSV (default: extracts/anatomy_enrichment_review.csv)",
    )
    args = parser.parse_args()

    efl_dir = Path(args.efl_directory)
    if not efl_dir.exists():
        print(f"Error: directory not found: {efl_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(
            enrich_directory(
                efl_dir,
                model=args.model,
                reasoning=args.reasoning,
                review_csv=Path(args.review_csv),
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
