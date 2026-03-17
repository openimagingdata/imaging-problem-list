"""Typed structured-output models for the coding LLM pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from finding_extractor.core.base_model import StrictBaseModel

FindingSelectorRejectionReason = Literal[
    "too_specific",
    "too_broad",
    "wrong_concept",
    "definition_mismatch",
]
LocationSelectorUnresolvedReason = Literal["no_candidate_match", "location_unknown"]


class FindingTerms(StrictBaseModel):
    """Search terms generated for one finding in a batched finding-term run."""

    finding_index: int
    search_terms: list[str] = Field(min_length=1, max_length=5)


class FindingTermsBatchOutput(StrictBaseModel):
    """Batched finding-index search terms keyed by batch finding index."""

    results: list[FindingTerms]


class LocationTerms(StrictBaseModel):
    """Search terms generated for one finding in a batched location-term run."""

    finding_index: int
    search_terms: list[str] = Field(max_length=5)


class LocationTermsBatchOutput(StrictBaseModel):
    """Batched location-index search terms keyed by batch finding index."""

    results: list[LocationTerms]


class FindingCodeSelection(StrictBaseModel):
    """Selected OIFM code, or a structured unresolved decision."""

    oifm_id: str | None = Field(
        description="Selected OIFM finding code, or null when no candidate is acceptable.",
    )
    reasoning: str = Field(
        description="Brief explanation of why this candidate was selected or rejected.",
    )
    closest_candidate_id: str | None = Field(
        default=None,
        description="Closest candidate when unresolved.",
    )
    rejection_reason: FindingSelectorRejectionReason | None = Field(
        default=None,
        description="Why the closest candidate was rejected.",
    )


class LocationCodeSelection(StrictBaseModel):
    """Selected location IDs, or a structured unresolved decision."""

    location_ids: list[str] = Field(
        default_factory=list,
        description="Selected location IDs. Multiple entries are allowed for bilateral findings.",
    )
    unresolved_reason: LocationSelectorUnresolvedReason | None = Field(
        default=None,
        description="Why location coding remained unresolved.",
    )
    reasoning: str = Field(
        description="Brief explanation of the location selection or unresolved result.",
    )
