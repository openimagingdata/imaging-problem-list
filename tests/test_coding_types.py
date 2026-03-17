"""Tests for coding LLM output models."""

import pytest
from pydantic import ValidationError

from finding_extractor.coding.types import (
    FindingCodeSelection,
    FindingTerms,
    LocationCodeSelection,
    LocationTerms,
)


def test_finding_terms_require_at_least_one_search_term():
    """Finding-term batches reject empty search-term lists."""
    with pytest.raises(ValidationError, match="at least 1 item"):
        FindingTerms(finding_index=0, search_terms=[])


def test_location_terms_allow_empty_search_terms():
    """Location-term batches can intentionally return no inferred location."""
    terms = LocationTerms(finding_index=0, search_terms=[])

    assert terms.search_terms == []


def test_finding_code_selection_accepts_structured_unresolved_payload():
    """Finding selectors can return a null code with rejection metadata."""
    selection = FindingCodeSelection(
        oifm_id=None,
        reasoning="Closest match narrows beyond the report wording.",
        closest_candidate_id="OIFM:123",
        rejection_reason="too_specific",
    )

    assert selection.oifm_id is None
    assert selection.closest_candidate_id == "OIFM:123"
    assert selection.rejection_reason == "too_specific"


def test_location_code_selection_accepts_multiple_ids():
    """Location selectors can return multiple lateralized locations."""
    selection = LocationCodeSelection(
        location_ids=["left-lung", "right-lung"],
        reasoning="The finding involves both lungs.",
    )

    assert selection.location_ids == ["left-lung", "right-lung"]
    assert selection.unresolved_reason is None
