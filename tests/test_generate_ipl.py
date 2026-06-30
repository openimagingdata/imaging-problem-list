"""Tests for the anatomy-aware IPL generator (scripts/generate_ipl_from_efls.py).

The generator groups EFL observations by (findingCode, anatomic locationId), so a
single finding code at two distinct anatomic locations becomes two IPL entries.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_ipl_from_efls.py"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("generate_ipl_from_efls", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _efl(
    *,
    report_id: str,
    study_date: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "diagnosticReportId": report_id,
        "patientInfo": {"patientIdentifier": "MRN0000001", "patientDOB": "1961-01-01"},
        "examInfo": {
            "studyIdentifier": f"CT_{study_date}",
            "studyDateTime": f"{study_date}T10:00:00Z",
            "studyLoincCode": "36952-0",
            "studyDescription": "CT Abdomen and Pelvis WO contrast",
        },
        "findings": findings,
    }


def _finding(
    *,
    observation_id: str,
    code: str,
    description: str,
    presence: str,
    location: dict[str, str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "observationId": observation_id,
        "findingCode": code,
        "findingDescription": description,
        "attributes": [
            {
                "attributeCode": "OIFMA_X_1",
                "attributeDescription": "presence",
                "attributeValueCode": f"OIFMA_X_1.{'1' if presence == 'present' else '0'}",
                "attributeValueDescription": presence,
            }
        ],
    }
    if location is not None:
        entry["anatomicLocation"] = location
    entry["reportText"] = f"text for {observation_id}"
    return entry


@pytest.fixture
def generated_ipl(tmp_path: Path) -> dict[str, Any]:
    gen = _load_generator()
    efl_dir = tmp_path / "efls"
    efl_dir.mkdir()

    left = {"locationId": "RID29663", "locationDisplay": "left kidney"}
    right = {"locationId": "RID29662", "locationDisplay": "right kidney"}

    # Exam 1: same code at two distinct kidneys -> must become two IPL entries.
    # Plus a code with NO anatomic location.
    (efl_dir / "ct_a_20210101_efl.json").write_text(
        json.dumps(
            _efl(
                report_id="rep-1",
                study_date="2021-01-01",
                findings=[
                    _finding(observation_id="cyst_r", code="OIFM_KID", description="renal cyst",
                             presence="present", location=right),
                    _finding(observation_id="cyst_l", code="OIFM_KID", description="renal cyst",
                             presence="present", location=left),
                    _finding(observation_id="osteo", code="OIFM_OST", description="osteoporosis",
                             presence="present", location=None),
                ],
            )
        )
    )
    # Exam 2 (later): the RIGHT kidney cyst recurs -> merges with exam-1 right entry.
    (efl_dir / "ct_b_20220101_efl.json").write_text(
        json.dumps(
            _efl(
                report_id="rep-2",
                study_date="2022-01-01",
                findings=[
                    _finding(observation_id="cyst_r", code="OIFM_KID", description="renal cyst",
                             presence="present", location=right),
                ],
            )
        )
    )

    out = tmp_path / "ipl.json"
    gen.generate_ipl(str(efl_dir), str(out))
    return json.loads(out.read_text())


def test_same_code_two_locations_splits_into_two_entries(generated_ipl: dict[str, Any]) -> None:
    kid_entries = [f for f in generated_ipl["findings"] if f["finding_type_code"] == "OIFM_KID"]
    assert len(kid_entries) == 2
    locations = {(f["anatomicLocation"] or {})["locationDisplay"] for f in kid_entries}
    assert locations == {"left kidney", "right kidney"}


def test_same_location_across_exams_merges(generated_ipl: dict[str, Any]) -> None:
    right_entry = next(
        f
        for f in generated_ipl["findings"]
        if f["finding_type_code"] == "OIFM_KID"
        and (f["anatomicLocation"] or {}).get("locationId") == "RID29662"
    )
    # Two observations (exam 1 + exam 2), sorted chronologically.
    assert len(right_entry["observations"]) == 2
    assert [o["exam_date"] for o in right_entry["observations"]] == ["2021-01-01", "2022-01-01"]
    assert all(o["anatomicLocation"]["locationId"] == "RID29662" for o in right_entry["observations"])


def test_finding_without_location_has_null_anatomic_location(generated_ipl: dict[str, Any]) -> None:
    osteo = next(f for f in generated_ipl["findings"] if f["finding_type_code"] == "OIFM_OST")
    assert osteo["anatomicLocation"] is None
    assert "anatomicLocation" not in osteo["observations"][0]


def test_ids_unique_and_anatomic_location_key_present(generated_ipl: dict[str, Any]) -> None:
    findings = generated_ipl["findings"]
    ids = [f["id"] for f in findings]
    assert len(ids) == len(set(ids))
    assert all("anatomicLocation" in f for f in findings)
