"""Build a self-contained extraction_reviewer.html from the src/ partials.

Assembles src/shell.html with src/styles.css, src/landing.html, src/app-shell.html,
src/app.js, and vendor/fflate.min.js into a single HTML file that has no external
network dependencies and loads extraction JSON at open time. Ship this HTML plus
a folder of extraction JSONs to a reviewer.

Usage:
    python build.py [-o OUTPUT_PATH]

Default output: ./extraction_reviewer.html (in the current working directory).
"""

from __future__ import annotations

import argparse
import base64
import html as htmllib
import re
from pathlib import Path

APP_VERSION = "1.2"

PLACEHOLDERS = {
    "__APP_VERSION__": "app_version",
    "__STYLES__": "styles",
    "__LANDING_HTML__": "landing",
    "__APP_SHELL_HTML__": "app_shell",
    "__VENDOR_ZIP_JS__": "vendor_zip",
    "__APP_JS__": "app_js",
    "__EMBEDDED_BUNDLE_B64__": "embedded_bundle",
    "__GUIDE_SCREEN_TOUR__": "guide_screen_tour",
    "__GUIDE_REVIEWING__": "guide_reviewing",
    "__GUIDE_MISSING_EXPORT__": "guide_missing_export",
    "__GUIDE_MORE_PERSISTENCE__": "guide_more_persistence",
    "__GUIDE_MORE_CSV__": "guide_more_csv",
    "__GUIDE_MORE_FLAGGING__": "guide_more_flagging",
}


def _render_markdown(md: str) -> str:
    """Tiny markdown renderer covering what REVIEWER_GUIDE.md actually uses.

    Deliberately minimal: H1/H2/H3, paragraphs, lists, tables, blockquotes,
    horizontal rules, inline bold/italic/code/link/image/<kbd>. We control the
    source, so we don't need a full CommonMark implementation.
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0

    def inline(text: str) -> str:
        # Images: ![alt](src)
        text = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            lambda m: f'<img src="{htmllib.escape(m.group(2), quote=True)}" alt="{htmllib.escape(m.group(1))}">',
            text,
        )
        # Links: [label](url)
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f'<a href="{htmllib.escape(m.group(2), quote=True)}" target="_blank" rel="noopener">{htmllib.escape(m.group(1))}</a>',
            text,
        )
        # <kbd> passthrough (already HTML in the source)
        # Bold: **text**
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        # Italic: *text* or _text_
        text = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
        # Inline code: `text`
        text = re.sub(
            r"`([^`]+)`",
            lambda m: f"<code>{htmllib.escape(m.group(1))}</code>",
            text,
        )
        return text

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # Horizontal rule
        if stripped == "---":
            out.append("<hr>")
            i += 1
            continue
        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        # Tables (leading '|')
        if stripped.startswith("|"):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            if i + 1 < len(lines) and re.match(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$", lines[i + 1].strip()):
                i += 2
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                    i += 1
                thead = "".join(f"<th>{inline(c)}</th>" for c in header)
                tbody = "".join(
                    "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                    for row in rows
                )
                out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
                continue
        # Unordered list
        if re.match(r"^\s*-\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\s*-\s+", lines[i]):
                items.append(re.sub(r"^\s*-\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        # Ordered list
        if re.match(r"^\s*\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ol>")
            continue
        # Blockquote
        if stripped.startswith(">"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].lstrip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(block)) + "</blockquote>")
            continue
        # Paragraph: accumulate until blank line
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|-|\d+\.|\||>|---)", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(para)) + "</p>")

    return "\n".join(out)


def _inline_guide_images(html: str, guide_path: Path, docs_root: Path) -> str:
    """Rewrite <img src="docs/images/X.png"> into base64 data URIs."""
    def repl(match: re.Match[str]) -> str:
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        # Resolve relative to the guide file (markdown uses repo-relative paths)
        candidate = (guide_path.parent / src).resolve()
        if not candidate.is_file():
            # Also try under docs_root in case of differently-anchored src
            alt = (docs_root / src).resolve()
            if alt.is_file():
                candidate = alt
            else:
                return match.group(0)
        ext = candidate.suffix.lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        b64 = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f'{prefix}data:{mime};base64,{b64}{suffix}'

    return re.sub(r'(<img\s[^>]*src=")([^"]+)(")', repl, html)


def _extract_markdown_section(md: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, md, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return f"## {heading}\n\nGuide section unavailable."
    return f"## {heading}\n\n{match.group(1).strip()}"


def _build_reviewer_guide_sections(guide_md_path: Path) -> dict[str, str]:
    if not guide_md_path.is_file():
        fallback = "<p>Reviewer guide not available.</p>"
        return dict.fromkeys(
            (
                "guide_screen_tour",
                "guide_reviewing",
                "guide_missing_export",
                "guide_more_persistence",
                "guide_more_csv",
                "guide_more_flagging",
            ),
            fallback,
        )
    md = guide_md_path.read_text(encoding="utf-8")
    headings = {
        "guide_screen_tour": "Screen tour",
        "guide_reviewing": "Reviewing & keys",
        "guide_missing_export": "Missing findings & export",
        "guide_more_persistence": "More: Persistence & resuming",
        "guide_more_csv": "More: CSV wizard details",
        "guide_more_flagging": "More: What to write when flagging",
    }
    return {
        key: _inline_guide_images(
            _render_markdown(_extract_markdown_section(md, heading)),
            guide_md_path,
            guide_md_path.parent,
        )
        for key, heading in headings.items()
    }


def build(
    src_dir: Path,
    vendor_zip_path: Path,
    output_path: Path,
    bundle_zip: Path | None = None,
    guide_path: Path | None = None,
) -> None:
    shell = (src_dir / "shell.html").read_text(encoding="utf-8")
    embedded = ""
    if bundle_zip is not None:
        embedded = base64.b64encode(bundle_zip.read_bytes()).decode("ascii")
    guide_md = guide_path or (src_dir.parent / "REVIEWER_GUIDE.md")
    guide_sections = _build_reviewer_guide_sections(guide_md)
    parts = {
        "app_version": APP_VERSION,
        "styles": (src_dir / "styles.css").read_text(encoding="utf-8"),
        "landing": (src_dir / "landing.html").read_text(encoding="utf-8"),
        "app_shell": (src_dir / "app-shell.html").read_text(encoding="utf-8"),
        "vendor_zip": vendor_zip_path.read_text(encoding="utf-8"),
        "app_js": (src_dir / "app.js").read_text(encoding="utf-8"),
        "embedded_bundle": embedded,
        **guide_sections,
    }

    out = shell
    for token, key in PLACEHOLDERS.items():
        out = out.replace(token, parts[key])

    output_path.write_text(out, encoding="utf-8")


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd() / "extraction_reviewer.html",
        help="Output HTML path (default: ./extraction_reviewer.html)",
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=here / "src",
        help="Source partials directory (default: ./src)",
    )
    parser.add_argument(
        "--vendor-zip",
        type=Path,
        default=here / "vendor" / "fflate.min.js",
        help="Vendored fflate path (default: ./vendor/fflate.min.js)",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=None,
        help="Optional zip to embed in the HTML (base64-injected; app auto-loads it).",
    )
    args = parser.parse_args()

    build(args.src, args.vendor_zip, args.output, bundle_zip=args.bundle)
    size_kb = args.output.stat().st_size / 1024
    print(f"Wrote {args.output} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
