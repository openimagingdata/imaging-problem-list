#!/usr/bin/env python3
"""Build the static data bundle for the anatomy-aware viewer_v2 app."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anatomic_locations import AnatomicLocationIndex

SCHEMA_VERSION = "viewer-v2-data.1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_DIR = PROJECT_ROOT / "sample_data" / "example2"
DEFAULT_VIEWER_DIR = PROJECT_ROOT / "viewer_v2"
DEFAULT_OUTPUT_DIR = DEFAULT_VIEWER_DIR / "public" / "data"
DEFAULT_CLUSTER_CONFIG = DEFAULT_VIEWER_DIR / "anatomy_clusters.json"
DEFAULT_DEFINITION_FILE = PROJECT_ROOT / "viewer" / "data" / "finding_display_info.json"
DEFAULT_COMPACT_NAMES_FILE = DEFAULT_VIEWER_DIR / "finding_compact_names.json"

STATUS_ACTIVE = {"current", "always"}
TEXT_FOLD_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)


class DataBuildError(RuntimeError):
    """Raised when the generated viewer_v2 bundle would be invalid."""


@dataclass(frozen=True)
class ExamRecord:
    report_id: str
    efl_file: Path
    report_file: Path
    exam_date: str
    exam_type_display: str
    exam_type_code: str


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def compact_name_entries_for_ipl(
    *,
    ipl: dict[str, Any],
    compact_names_file: Path,
    warnings: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    if not compact_names_file.exists():
        raise DataBuildError(f"Missing compact finding-name input: {compact_names_file}")

    payload = load_json(compact_names_file)
    compact_names = payload.get("compactNames")
    if not isinstance(compact_names, dict):
        raise DataBuildError(f"{compact_names_file} must contain a compactNames object")

    generated: dict[str, dict[str, str]] = {}
    warned_stale_codes: set[str] = set()
    for finding in ipl.get("findings", []):
        code = finding.get("finding_type_code")
        full_name = finding.get("finding_type_display")
        entry = compact_names.get(code)
        if not entry:
            continue
        expected_name = entry.get("name")
        compact = entry.get("compact")
        if not expected_name or not compact:
            raise DataBuildError(f"Compact finding-name entry for {code} requires name and compact")
        if expected_name != full_name:
            if code not in warned_stale_codes:
                warnings.append(
                    {
                        "type": "stale_compact_name",
                        "findingCode": code,
                        "message": (
                            "Compact finding-name entry does not match the IPL display name; "
                            "falling back to the full finding name."
                        ),
                    }
                )
                warned_stale_codes.add(code)
            continue
        generated[code] = {
            "name": expected_name,
            "compact": compact,
        }

    return dict(sorted(generated.items()))


def normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value or "").translate(TEXT_FOLD_TRANSLATION)
    return re.sub(r"\s+", " ", folded).strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def patient_slug(mrn: str) -> str:
    return f"patient-{slugify(mrn).replace('_', '')}"


def compute_status(finding: dict[str, Any]) -> str:
    observations = finding.get("observations") or []
    if not observations:
        return "unknown"

    sorted_obs = sorted(observations, key=lambda obs: obs.get("exam_date") or "", reverse=True)
    latest = sorted_obs[0]
    latest_presence = latest.get("presence")
    has_present = any(obs.get("presence") == "present" for obs in observations)
    all_present = all(obs.get("presence") == "present" for obs in observations)

    if latest_presence == "present":
        return "always" if all_present and len(observations) > 1 else "current"
    if has_present:
        return "resolved"
    return "never_present"


def laterality_bucket(raw: str | None) -> str:
    if raw == "left":
        return "left"
    if raw == "right":
        return "right"
    if raw == "generic":
        return "generic_unspecified"
    return "midline_nonlateral"


def region_id_from_label(label: str | None, display: str | None = None) -> str:
    display_l = (display or "").lower()
    if label == "Head":
        return "head"
    if label == "Neck":
        return "neck"
    if label == "Thorax":
        return "thorax"
    if label == "Abdomen":
        return "abdomen"
    if label == "Pelvis":
        return "pelvis"
    if label == "Upper Extremity":
        return "upper_extremity"
    if label == "Lower Extremity":
        return "lower_extremity"
    if label == "Breast":
        return "breast"
    if label == "Body":
        if "upper extremity" in display_l or "upper limb" in display_l:
            return "upper_extremity"
        if "lower extremity" in display_l or "lower limb" in display_l:
            return "lower_extremity"
        if "abdomen" in display_l:
            return "abdomen"
        if "thorax" in display_l or "chest" in display_l:
            return "thorax"
        if "head" in display_l:
            return "head"
    return "unlocalized"


def region_label_from_id(region_id: str, config: dict[str, Any]) -> str:
    for region in config["regions"]:
        if region["id"] == region_id:
            return region["label"]
    return "Unlocalized"


def find_exam_records(sample_dir: Path) -> dict[str, ExamRecord]:
    records: dict[str, ExamRecord] = {}
    for efl_file in sorted(sample_dir.glob("*_efl.json")):
        efl = load_json(efl_file)
        report_id = efl.get("diagnosticReportId")
        if not report_id:
            raise DataBuildError(f"{efl_file} has no diagnosticReportId")

        report_file = efl_file.with_name(efl_file.name.replace("_efl.json", ".md"))
        if not report_file.exists():
            raise DataBuildError(f"Missing report Markdown for {efl_file.name}: {report_file}")

        exam_info = efl.get("examInfo") or {}
        study_datetime = exam_info.get("studyDateTime") or ""
        exam_date = study_datetime.split("T")[0] if study_datetime else "Unknown"
        records[report_id] = ExamRecord(
            report_id=report_id,
            efl_file=efl_file,
            report_file=report_file,
            exam_date=exam_date,
            exam_type_display=exam_info.get("studyDescription") or "Unknown",
            exam_type_code=exam_info.get("studyLoincCode") or "unknown",
        )
    return records


def refs_from_locations(locations: list[Any]) -> list[dict[str, str]]:
    refs = []
    for loc in locations:
        refs.append({"id": loc.id, "display": loc.description})
    return refs


def safe_get_location(index: AnatomicLocationIndex, location_id: str) -> Any | None:
    try:
        return index.get(location_id)
    except Exception:
        return None


def location_haystack(index: AnatomicLocationIndex, location: Any | None, display: str | None) -> str:
    pieces = [display or ""]
    if location is not None:
        pieces.extend(
            [
                location.description or "",
                location.definition or "",
                " ".join(location.synonyms or []),
            ]
        )
        for getter in (index.get_containment_ancestors, index.get_partof_ancestors):
            try:
                pieces.extend(ancestor.description for ancestor in getter(location.id))
            except Exception:
                continue
    return " ".join(pieces).lower()


def location_primary_haystack(location: Any | None, display: str | None) -> str:
    pieces = [display or ""]
    if location is not None:
        pieces.extend(
            [
                location.description or "",
                location.definition or "",
                " ".join(location.synonyms or []),
            ]
        )
    return " ".join(pieces).lower()


def match_cluster(
    *,
    config: dict[str, Any],
    index: AnatomicLocationIndex,
    location: Any | None,
    region_id: str,
    display: str | None,
) -> dict[str, Any]:
    if region_id == "unlocalized":
        return {
            "clusterId": "unlocalized",
            "clusterLabel": "Unlocalized",
            "displayOrder": 999,
            "matchedBy": "fallback",
        }

    candidates = [
        cluster for cluster in config["clusters"] if cluster.get("regionId") == region_id
    ]
    primary_haystack = location_primary_haystack(location, display)
    for cluster in sorted(candidates, key=lambda item: item.get("displayOrder", 999)):
        for keyword in cluster.get("keywords", []):
            if keyword.lower() in primary_haystack:
                return {
                    "clusterId": cluster["id"],
                    "clusterLabel": cluster["label"],
                    "displayOrder": cluster.get("displayOrder", 999),
                    "matchedBy": f"keyword:{keyword}",
                }

    fallback_haystack = location_haystack(index, location, display)
    for cluster in sorted(candidates, key=lambda item: item.get("displayOrder", 999)):
        for keyword in cluster.get("keywords", []):
            if keyword.lower() in fallback_haystack:
                return {
                    "clusterId": cluster["id"],
                    "clusterLabel": cluster["label"],
                    "displayOrder": cluster.get("displayOrder", 999),
                    "matchedBy": f"ancestor-keyword:{keyword}",
                }

    return {
        "clusterId": f"{region_id}_other",
        "clusterLabel": f"Other {region_label_from_id(region_id, config)}",
        "displayOrder": 900,
        "matchedBy": "region-fallback",
    }


def build_location_payload(
    *,
    index: AnatomicLocationIndex,
    location_id: str,
) -> dict[str, Any] | None:
    location = safe_get_location(index, location_id)
    if location is None:
        return None

    try:
        containment_ancestors = refs_from_locations(index.get_containment_ancestors(location_id))
    except Exception:
        containment_ancestors = []

    try:
        partof_ancestors = refs_from_locations(index.get_partof_ancestors(location_id))
    except Exception:
        partof_ancestors = []

    def ref_payload(ref: Any | None) -> dict[str, str] | None:
        if ref is None:
            return None
        return {"id": ref.id, "display": ref.display}

    region_label = location.region.value if location.region else None
    region_id = region_id_from_label(region_label, location.description)

    return {
        "id": location.id,
        "display": location.description,
        "regionId": region_id,
        "regionLabel": region_label_from_id(region_id, {"regions": DEFAULT_REGIONS}),
        "laterality": laterality_bucket(location.laterality.value if location.laterality else None),
        "sourceLaterality": location.laterality.value if location.laterality else None,
        "bodySystem": location.body_system.value if location.body_system else None,
        "structureType": location.structure_type.value if location.structure_type else None,
        "locationType": location.location_type.value if location.location_type else None,
        "containmentAncestors": containment_ancestors,
        "partOfAncestors": partof_ancestors,
        "genericVariant": ref_payload(location.generic_variant),
        "leftVariant": ref_payload(location.left_variant),
        "rightVariant": ref_payload(location.right_variant),
    }


DEFAULT_REGIONS = [
    {"id": "head", "label": "Head"},
    {"id": "neck", "label": "Neck"},
    {"id": "thorax", "label": "Thorax"},
    {"id": "abdomen", "label": "Abdomen"},
    {"id": "pelvis", "label": "Pelvis"},
    {"id": "upper_extremity", "label": "Upper Extremity"},
    {"id": "lower_extremity", "label": "Lower Extremity"},
    {"id": "breast", "label": "Breast"},
    {"id": "unlocalized", "label": "Unlocalized"},
]


def build_bundle(
    *,
    sample_dir: Path,
    output_dir: Path,
    cluster_config_path: Path,
    definition_file: Path,
    compact_names_file: Path,
) -> None:
    ipl_path = sample_dir / "MRN0000001_ipl.json"
    if not ipl_path.exists():
        raise DataBuildError(f"Missing IPL input: {ipl_path}")
    if not definition_file.exists():
        raise DataBuildError(f"Missing finding definition input: {definition_file}")

    ipl = load_json(ipl_path)
    definitions = load_json(definition_file)
    cluster_config = load_json(cluster_config_path)
    exam_records = find_exam_records(sample_dir)

    patient = ipl.get("patient") or {}
    mrn = patient.get("id")
    if not mrn:
        raise DataBuildError("IPL patient.id is required")
    patient_id = patient_slug(mrn)

    finding_ids = [finding.get("id") for finding in ipl.get("findings", [])]
    missing_ids = [idx for idx, finding_id in enumerate(finding_ids) if not finding_id]
    if missing_ids:
        raise DataBuildError(f"IPL findings missing id at indexes: {missing_ids}")
    duplicates = [item for item, count in Counter(finding_ids).items() if count > 1]
    if duplicates:
        raise DataBuildError(f"Duplicate IPL finding ids: {duplicates}")

    warnings: list[dict[str, Any]] = []
    compact_names = compact_name_entries_for_ipl(
        ipl=ipl,
        compact_names_file=compact_names_file,
        warnings=warnings,
    )
    used_location_ids: set[str] = set()
    statuses: dict[str, str] = {}
    report_text_by_id = {
        report_id: record.report_file.read_text()
        for report_id, record in exam_records.items()
    }

    for finding in ipl.get("findings", []):
        finding_id = finding["id"]
        status = compute_status(finding)
        if status == "unknown":
            raise DataBuildError(f"Finding has no displayable status: {finding_id}")
        statuses[finding_id] = status

        anatomic = finding.get("anatomicLocation")
        has_anatomic_location = bool(anatomic and anatomic.get("locationId"))
        if has_anatomic_location:
            used_location_ids.add(anatomic["locationId"])

        if finding.get("finding_type_code") not in definitions:
            warnings.append(
                {
                    "type": "missing_definition",
                    "findingId": finding_id,
                    "findingCode": finding.get("finding_type_code"),
                    "message": "Finding definition metadata is unavailable.",
                }
            )

        for obs in finding.get("observations") or []:
            report_id = obs.get("report_id")
            if report_id not in exam_records:
                raise DataBuildError(
                    f"Observation {obs.get('observation_id')} references missing report_id {report_id}"
                )
            evidence = obs.get("reportText")
            if evidence:
                normalized_evidence = normalize_text(evidence)
                normalized_report = normalize_text(report_text_by_id[report_id])
                if normalized_evidence not in normalized_report:
                    warnings.append(
                        {
                            "type": "evidence_not_exact",
                            "findingId": finding_id,
                            "observationId": obs.get("observation_id"),
                            "reportId": report_id,
                            "message": "Evidence text is associated with a report but is not an exact normalized substring.",
                        }
                    )
            obs_location = obs.get("anatomicLocation")
            if obs_location and obs_location.get("locationId"):
                has_anatomic_location = True
                used_location_ids.add(obs_location["locationId"])

        if not has_anatomic_location:
            warnings.append(
                {
                    "type": "missing_anatomy",
                    "findingId": finding_id,
                    "message": "Finding has no specific anatomy location and uses the Unlocalized display fallback.",
                }
            )

    try:
        index = AnatomicLocationIndex().open()
    except Exception as exc:
        raise DataBuildError(
            "Unable to open anatomic-locations index. Ensure the DuckDB is installed at "
            "~/Library/Application Support/anatomic-locations/anatomic_locations.duckdb."
        ) from exc
    try:
        location_payloads: dict[str, dict[str, Any]] = {}
        unresolved_locations: list[str] = []
        related_location_ids: set[str] = set()

        for location_id in sorted(used_location_ids):
            payload = build_location_payload(index=index, location_id=location_id)
            if payload is None:
                unresolved_locations.append(location_id)
                continue
            location_payloads[location_id] = payload
            for ancestor in payload["containmentAncestors"] + payload["partOfAncestors"]:
                related_location_ids.add(ancestor["id"])
            for variant_key in ("genericVariant", "leftVariant", "rightVariant"):
                variant = payload.get(variant_key)
                if variant:
                    related_location_ids.add(variant["id"])

        for location_id in sorted(related_location_ids - set(location_payloads)):
            payload = build_location_payload(index=index, location_id=location_id)
            if payload is not None:
                location_payloads[location_id] = payload

        cluster_by_location: dict[str, dict[str, Any]] = {}
        for location_id in sorted(used_location_ids):
            location = safe_get_location(index, location_id)
            anatomic_display = location.description if location is not None else None
            if location is None:
                region_id = "unlocalized"
                laterality = "generic_unspecified"
                warnings.append(
                    {
                        "type": "unresolved_anatomy",
                        "locationId": location_id,
                        "message": "Location ID could not be resolved; assigned to Unlocalized.",
                    }
                )
            else:
                region_label = location.region.value if location.region else None
                region_id = region_id_from_label(region_label, location.description)
                laterality = laterality_bucket(location.laterality.value if location.laterality else None)

            cluster = match_cluster(
                config=cluster_config,
                index=index,
                location=location,
                region_id=region_id,
                display=anatomic_display,
            )
            cluster_by_location[location_id] = {
                "locationId": location_id,
                "locationDisplay": anatomic_display or location_id,
                "regionId": region_id,
                "regionLabel": region_label_from_id(region_id, cluster_config),
                "clusterId": cluster["clusterId"],
                "clusterLabel": cluster["clusterLabel"],
                "laterality": laterality,
                "displayOrder": cluster["displayOrder"],
                "matchedBy": cluster["matchedBy"],
            }
    finally:
        index.close()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    generated_at = datetime.now(UTC).isoformat()
    base_meta = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
    }

    patient_summary = {
        "id": patient_id,
        "displayName": patient.get("name") or mrn,
        "mrn": mrn,
        "dob": patient.get("dob"),
        "examCount": len(exam_records),
        "findingCount": len(ipl.get("findings", [])),
    }

    write_json(
        output_dir / "patients.json",
        {
            **base_meta,
            "patients": [patient_summary],
        },
    )
    write_json(
        output_dir / "manifest.json",
        {
            **base_meta,
            "source": {
                "sampleDir": str(sample_dir.relative_to(PROJECT_ROOT)),
                "ipl": str(ipl_path.relative_to(PROJECT_ROOT)),
                "findingDefinitions": str(definition_file.relative_to(PROJECT_ROOT)),
                "compactFindingNames": str(compact_names_file.relative_to(PROJECT_ROOT)),
            },
            "warnings": warnings,
            "counts": {
                "patients": 1,
                "exams": len(exam_records),
                "findings": len(ipl.get("findings", [])),
                "usedLocations": len(used_location_ids),
                "resolvedLocations": len(used_location_ids) - len(unresolved_locations),
                "compactNames": len(compact_names),
                "warnings": len(warnings),
            },
        },
    )

    patient_dir = output_dir / "patients" / patient_id
    write_json(patient_dir / "patient.json", {**base_meta, **patient_summary})

    ipl_copy = {
        **ipl,
        "schemaVersion": SCHEMA_VERSION,
        "viewerMetadata": {
            "patientId": patient_id,
            "statusByFindingId": statuses,
        },
    }
    write_json(patient_dir / "ipl.json", ipl_copy)

    for report_id, record in sorted(exam_records.items()):
        exam_dir = patient_dir / "exams" / report_id
        efl = load_json(record.efl_file)
        efl["schemaVersion"] = SCHEMA_VERSION
        write_json(exam_dir / "efl.json", efl)
        exam_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(record.report_file, exam_dir / "report.md")

    write_json(
        output_dir / "anatomy_index.json",
        {
            **base_meta,
            "locations": dict(sorted(location_payloads.items())),
            "usedLocationIds": sorted(used_location_ids),
        },
    )
    write_json(
        output_dir / "anatomy_clusters.json",
        {
            **base_meta,
            "regions": cluster_config["regions"],
            "clusters": cluster_config["clusters"],
            "locationClusters": dict(sorted(cluster_by_location.items())),
        },
    )
    write_json(
        output_dir / "finding_display_info.json",
        {
            **base_meta,
            "definitions": definitions,
            "compactNames": compact_names,
        },
    )

    print(f"Generated viewer_v2 data at {output_dir}")
    print(f"Findings: {len(statuses)}")
    print(f"Exams: {len(exam_records)}")
    print(f"Used locations: {len(used_location_ids)}")
    print(f"Warnings: {len(warnings)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static data for viewer_v2")
    parser.add_argument("--sample-dir", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cluster-config", type=Path, default=DEFAULT_CLUSTER_CONFIG)
    parser.add_argument("--definition-file", type=Path, default=DEFAULT_DEFINITION_FILE)
    parser.add_argument("--compact-names-file", type=Path, default=DEFAULT_COMPACT_NAMES_FILE)
    args = parser.parse_args()

    build_bundle(
        sample_dir=args.sample_dir,
        output_dir=args.output_dir,
        cluster_config_path=args.cluster_config,
        definition_file=args.definition_file,
        compact_names_file=args.compact_names_file,
    )


if __name__ == "__main__":
    main()
