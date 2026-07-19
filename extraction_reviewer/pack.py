"""Pack a review bundle for distribution to reviewers.

Two shipping modes:

  (default)  Zip bundle: HTML + README + reports/ folder.
             Recipient unzips, opens the HTML, drops the folder on the app.

  --embed    Self-contained HTML: reports baked in as a base64 zip.
             Recipient double-clicks the HTML; data loads automatically.

Both modes pair each extraction .json with a matching .txt / .md report by
basename (e.g. cxr001.json + cxr001.txt).  By default texts are looked up in
--reports alongside the JSONs; pass --report-texts DIR to pull them from a
separate directory instead (e.g. extractions are produced into a different
folder than where you keep the source reports).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import tempfile
import zipfile
from pathlib import Path

from build import build as build_html

REPORT_EXTS = {".txt", ".md"}
EMBED_SIZE_WARN_MB = 25  # warn if embedded HTML is likely this large or bigger

README_TEXT = """\
Extraction Review Bundle
========================

Contents
--------
- extraction_reviewer.html   Single-file review app (no install required).
- reports/                   Extraction JSON files paired with the source reports.

How to review
-------------
1. Unzip this folder anywhere on your machine.
2. Double-click extraction_reviewer.html to open it in your browser
   (Chrome, Edge, or Safari recommended).
3. Enter your name or identifier on the landing screen.
4. Drag the reports/ folder onto the drop zone, or click "Pick folder".
5. For each finding:
     A        approve
     F        focus the comment box / send a flag
     J / K    previous / next finding
     H / L    previous / next file
     Enter    in the comment box, submits the flag
     ?        open the in-app reviewer guide
6. Use "+ Missing findings" in the sidebar to log findings the extractor
   missed. Highlight text in the source report to capture a supporting quote.
7. When you're done, click "Download reviews (zip)" to download a zip of
   review JSON files. Send that zip back.

Notes
-----
- Progress auto-saves in your browser's local storage, keyed per file. You
  can close the tab and come back.
- Nothing leaves your machine; the app makes no network calls once opened.
- Pairing: each report_name.json is matched with a sibling report_name.txt
  (or .md) with the exact same basename.
"""


# ---------- Errors / messaging ----------

def _warn(msg: str) -> None:
    sys.stderr.write(f"pack.py: warning: {msg}\n")


class PackError(Exception):
    """User-facing error (prints cleanly, no traceback)."""


# ---------- File discovery ----------

def find_report_pairs(
    reports_dir: Path,
    texts_dir: Path | None = None,
) -> tuple[list[Path], list[str]]:
    """Return (files_to_include, warnings).

    JSONs always come from ``reports_dir``. If ``texts_dir`` is given,
    matching .txt / .md siblings are looked up there; otherwise they're
    looked up in ``reports_dir``.

    Raises PackError if a directory is invalid.
    """
    if not reports_dir.exists():
        raise PackError(f"--reports path does not exist: {reports_dir}")
    if not reports_dir.is_dir():
        raise PackError(f"--reports must be a directory: {reports_dir}")
    if texts_dir is not None:
        if not texts_dir.exists():
            raise PackError(f"--report-texts path does not exist: {texts_dir}")
        if not texts_dir.is_dir():
            raise PackError(f"--report-texts must be a directory: {texts_dir}")

    entries = list(reports_dir.iterdir())
    jsons = sorted(p for p in entries if p.is_file() and p.suffix.lower() == ".json")

    text_entries = list(texts_dir.iterdir()) if texts_dir is not None else entries
    by_stem: dict[str, Path] = {}
    for p in text_entries:
        if p.is_file() and p.suffix.lower() in REPORT_EXTS:
            by_stem.setdefault(p.stem, p)

    if not jsons:
        raise PackError(
            f"no extraction .json files found in {reports_dir}\n"
            f"  (looked for *.json at top level; expected paired .txt / .md optional)"
        )

    included: list[Path] = []
    warnings: list[str] = []
    for j in jsons:
        included.append(j)
        mate = by_stem.get(j.stem)
        if mate:
            included.append(mate)
        else:
            origin = texts_dir if texts_dir is not None else reports_dir
            warnings.append(
                f"{j.name}: no paired .txt or .md report in {origin} "
                f"(will use reconstruction)"
            )

    used = set(included)
    for mate in by_stem.values():
        if mate not in used:
            included.append(mate)
            warnings.append(f"{mate.name}: no matching .json extraction (orphan report)")

    return included, warnings


def _report_counts(paths: list[Path]) -> tuple[int, int]:
    j = sum(1 for p in paths if p.suffix.lower() == ".json")
    r = sum(1 for p in paths if p.suffix.lower() in REPORT_EXTS)
    return j, r


def _total_bytes(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths)


def build_reports_zip_bytes(included: list[Path]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src in included:
            zf.write(src, arcname=src.name)
    return buf.getvalue()


# ---------- Packing ----------

def pack_bundle(
    html_path: Path,
    reports_dir: Path | None,
    output_zip: Path,
    texts_dir: Path | None = None,
) -> None:
    bundle_stem = output_zip.with_suffix("").name
    included: list[Path] = []
    warnings: list[str] = []
    if reports_dir is not None:
        included, warnings = find_report_pairs(reports_dir, texts_dir)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_path, arcname=f"{bundle_stem}/extraction_reviewer.html")
        zf.writestr(f"{bundle_stem}/README.txt", README_TEXT)
        for src in included:
            zf.write(src, arcname=f"{bundle_stem}/reports/{src.name}")

    size_kb = output_zip.stat().st_size / 1024
    print(f"Wrote {output_zip} ({size_kb:,.1f} KB)")
    if reports_dir is not None:
        j, r = _report_counts(included)
        print(f"  Packed {j} extraction(s) and {r} report(s).")
    else:
        print("  No reports directory supplied: the zip contains only the app and README.")
    for w in warnings:
        print(f"  warn: {w}")


def pack_embedded(
    src_dir: Path,
    vendor_zip: Path,
    reports_dir: Path,
    output_html: Path,
    texts_dir: Path | None = None,
) -> None:
    included, warnings = find_report_pairs(reports_dir, texts_dir)
    raw_bytes = _total_bytes(included)
    estimated_mb = (raw_bytes * 1.33) / (1024 * 1024)
    if estimated_mb >= EMBED_SIZE_WARN_MB:
        _warn(
            f"embedded payload is large (~{estimated_mb:.1f} MB after base64). "
            f"Consider the bundle-zip mode (drop --embed) for large report sets."
        )

    zip_bytes = build_reports_zip_bytes(included)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = Path(tmp.name)
    try:
        build_html(src_dir, vendor_zip, output_html, bundle_zip=tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    size_kb = output_html.stat().st_size / 1024
    print(f"Wrote {output_html} ({size_kb:,.1f} KB, self-contained)")
    j, r = _report_counts(included)
    print(f"  Embedded {j} extraction(s) and {r} report(s).")
    for w in warnings:
        print(f"  warn: {w}")


# ---------- Dry-run summary ----------

def summarize(
    reports_dir: Path | None,
    embed: bool,
    output: Path,
    texts_dir: Path | None = None,
) -> None:
    mode = "embedded HTML" if embed else "bundle zip"
    print(f"Mode:    {mode}")
    print(f"Output:  {output}")
    if reports_dir is None:
        print("Reports: (none)")
        return
    included, warnings = find_report_pairs(reports_dir, texts_dir)
    j, r = _report_counts(included)
    raw_mb = _total_bytes(included) / (1024 * 1024)
    print(f"Reports: {reports_dir}")
    if texts_dir is not None:
        print(f"Texts:   {texts_dir}")
    print(f"         {j} extraction(s), {r} paired report(s), {raw_mb:.2f} MB raw")
    for w in warnings:
        print(f"  warn: {w}")


# ---------- CLI ----------

EPILOG = """\
Examples:
  # Self-contained HTML (best reviewer UX — zero clicks to load)
  python pack.py --reports ./samples --embed

  # Extractions and source report texts live in separate directories
  python pack.py --reports ./extractions --report-texts ./source_reports --embed

  # Zip bundle with HTML + reports/
  python pack.py --reports ./samples -o out/bundle.zip

  # App-only zip (recipient supplies their own reports)
  python pack.py

  # Inspect what would be packed without writing any file
  python pack.py --reports ./samples --embed --dry-run
"""


def _build_parser(default_bundle: Path, default_embed: Path, here: Path) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pack.py",
        description=__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--reports",
        type=Path,
        metavar="DIR",
        default=None,
        help="Directory of extraction .json files (and, by default, their .txt/.md siblings). "
             "Required for --embed; optional for bundle mode (bundles just the app if omitted).",
    )
    p.add_argument(
        "--report-texts",
        type=Path,
        metavar="DIR",
        default=None,
        help="Directory to look up .txt / .md source reports in, matched to each "
             "extraction by basename. Use this when the source reports don't live "
             "next to the extraction JSONs. Defaults to --reports.",
    )
    p.add_argument(
        "--embed",
        action="store_true",
        help="Produce one self-contained HTML with the reports baked in (instead of a zip).",
    )
    p.add_argument(
        "-o", "--output",
        type=Path,
        metavar="PATH",
        default=None,
        help=(
            f"Output file.  Defaults: "
            f"bundle mode -> {default_bundle.name}, "
            f"--embed -> {default_embed.name}."
        ),
    )
    p.add_argument(
        "--html",
        type=Path,
        metavar="PATH",
        default=here / "extraction_reviewer.html",
        help="Bundle mode only: path to the prebuilt reviewer HTML to include "
             "(default: ./extraction_reviewer.html). Ignored when --embed is set.",
    )
    p.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Bundle mode only: reuse the existing --html file instead of rebuilding from src/. "
             "Ignored when --embed is set.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be packed and exit without writing any file.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    stamp = dt.date.today().strftime("%Y%m%d")
    default_bundle = Path.cwd() / f"review-bundle-{stamp}.zip"
    default_embed = Path.cwd() / f"extraction-review-{stamp}.html"

    parser = _build_parser(default_bundle, default_embed, here)
    args = parser.parse_args(argv)

    # ---- Validate required source files ----
    src_dir = here / "src"
    vendor_zip = here / "vendor" / "fflate.min.js"
    if not src_dir.is_dir():
        parser.error(f"src/ directory not found at {src_dir} (is this the extraction_reviewer repo?)")
    if not vendor_zip.is_file():
        parser.error(f"vendor/fflate.min.js not found at {vendor_zip}")

    # ---- Validate mode-specific args ----
    if args.embed and args.reports is None:
        parser.error("--embed requires --reports (embedded HTML needs data to embed)")

    if args.embed and args.no_rebuild:
        _warn("--no-rebuild has no effect with --embed (embed mode always rebuilds)")
    if args.embed and args.html != (here / "extraction_reviewer.html"):
        _warn("--html is ignored with --embed (embed mode builds fresh from src/)")

    # ---- Resolve output path + sanity-check the extension ----
    if args.embed:
        out = args.output or default_embed
        expected_ext = ".html"
    else:
        out = args.output or default_bundle
        expected_ext = ".zip"

    if out.suffix.lower() != expected_ext:
        _warn(
            f"output '{out.name}' has extension '{out.suffix}' but "
            f"{'embed' if args.embed else 'bundle'} mode produces '{expected_ext}' files"
        )

    if out.exists() and out.is_dir():
        parser.error(f"--output points to an existing directory: {out}")

    if args.reports is not None and not args.reports.exists():
        parser.error(f"--reports path does not exist: {args.reports}")
    if args.reports is not None and not args.reports.is_dir():
        parser.error(f"--reports must be a directory: {args.reports}")
    if args.report_texts is not None:
        if args.reports is None:
            parser.error("--report-texts has no effect without --reports")
        if not args.report_texts.exists():
            parser.error(f"--report-texts path does not exist: {args.report_texts}")
        if not args.report_texts.is_dir():
            parser.error(f"--report-texts must be a directory: {args.report_texts}")
        if args.report_texts.resolve() == args.reports.resolve():
            _warn("--report-texts points to the same directory as --reports; the flag is a no-op")

    # ---- Dry run exits here ----
    if args.dry_run:
        try:
            summarize(args.reports, args.embed, out, args.report_texts)
        except PackError as e:
            print(f"pack.py: error: {e}", file=sys.stderr)
            return 1
        return 0

    # ---- Do the work ----
    try:
        if args.embed:
            pack_embedded(src_dir, vendor_zip, args.reports, out, args.report_texts)
            return 0

        if not args.no_rebuild:
            build_html(src_dir, vendor_zip, args.html)
        if not args.html.is_file():
            parser.error(
                f"HTML not found: {args.html}\n"
                f"  (drop --no-rebuild, point --html at an existing file, or run build.py first)"
            )
        pack_bundle(args.html, args.reports, out, args.report_texts)
        return 0
    except PackError as e:
        print(f"pack.py: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
