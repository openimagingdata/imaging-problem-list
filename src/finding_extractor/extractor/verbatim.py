"""Shared verbatim text matching helpers."""

import re
import unicodedata


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip."""
    return " ".join(text.split())


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy verbatim matching.

    Lowercases, strips markdown formatting (bold/italic markers),
    collapses whitespace, and removes leading/trailing punctuation.
    """
    # Normalize unicode (e.g. curly quotes → straight)
    text = unicodedata.normalize("NFKC", text)
    # Strip markdown bold/italic markers
    text = text.replace("*", "").replace("_", "")
    # Lowercase
    text = text.lower()
    # Collapse whitespace
    text = " ".join(text.split())
    # Strip leading/trailing punctuation and whitespace
    text = re.sub(r"^[\s\W]+|[\s\W]+$", "", text)
    return text


def verbatim_match(span: str, report_text: str) -> bool:
    """Check if *span* appears in *report_text*.

    Tries exact match first, then whitespace-normalized, then a
    case-insensitive / punctuation-stripped / markdown-stripped match.
    """
    snippet = span.strip()
    if not snippet:
        return False
    # Exact
    if snippet in report_text:
        return True
    # Whitespace-normalized
    if normalize_whitespace(snippet) in normalize_whitespace(report_text):
        return True
    # Fuzzy: case-insensitive, strip markdown/punctuation
    return _normalize_for_match(snippet) in _normalize_for_match(report_text)
