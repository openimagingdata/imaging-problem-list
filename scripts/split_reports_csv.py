"""Split a CSV of radiology reports into one .txt file per row.

Usage: uv run python scripts/split_reports_csv.py <input.csv> <output_dir>

The CSV must have columns: ID, Status, Accession, Report.
Each row produces <output_dir>/<ID>.txt containing the stripped Report text,
with boilerplate lines (ATTESTATION, "A clinically significant result...") removed.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

DROP_PREFIXES = ("ATTESTATION", "A clinically significant result")


def clean_report(report: str) -> str:
    kept = [line for line in report.splitlines() if not line.lstrip().startswith(DROP_PREFIXES)]
    return "\n".join(kept).strip()


def safe_target(out_dir: Path, report_id: str) -> Path:
    """Return a path under out_dir for this ID, or raise ValueError if unsafe.

    Rejects empty IDs, IDs containing path separators, drive letters, null
    bytes, or traversal segments, and verifies the resolved target is still
    inside the resolved output directory.
    """
    if not report_id:
        raise ValueError("empty ID")
    if "\x00" in report_id:
        raise ValueError(f"ID contains NUL byte: {report_id!r}")
    if "/" in report_id or "\\" in report_id:
        raise ValueError(f"ID contains path separator: {report_id!r}")
    if report_id in {".", ".."} or report_id.startswith("."):
        raise ValueError(f"ID is a reserved/dot name: {report_id!r}")
    candidate = out_dir / f"{report_id}.txt"
    resolved_out = out_dir.resolve()
    resolved_target = candidate.resolve()
    if resolved_out != resolved_target.parent:
        raise ValueError(f"ID resolves outside output dir: {report_id!r}")
    return candidate


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    csv_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report_id = row["ID"].strip()
            try:
                target = safe_target(out_dir, report_id)
            except ValueError as exc:
                print(f"skipping row: {exc}", file=sys.stderr)
                continue
            report = clean_report(row["Report"])
            target.write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
