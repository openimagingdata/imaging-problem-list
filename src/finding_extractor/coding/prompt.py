"""Prompt constants and prompt builders for the coding pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from finding_extractor.models import ExamInfo, Finding

if TYPE_CHECKING:
    from anatomic_locations import AnatomicLocation
    from findingmodel.index import IndexEntry


class FindingCodeCandidate(Protocol):
    """Shape required by the finding selector prompt builder."""

    oifm_id: str
    name: str
    description: str | None
    synonyms: Sequence[str]
    tags: Sequence[str]


class _LocationParent(Protocol):
    """Minimal hierarchy node surface needed for prompt rendering."""

    display: str


class LocationCodeCandidate(Protocol):
    """Shape required by the location selector prompt builder."""

    id: str
    description: str
    region: str
    laterality: str | None
    containment_parent: _LocationParent | None
    partof_parent: _LocationParent | None

FINDING_TERM_SYSTEM = """\
You are a medical informatics assistant. Your task is to propose search query
terms that will be used to look up entries in an ontology of radiology findings
and diagnoses.

The goal of this process is to assign a common standardized label to all
descriptions that refer to the same clinical concept — whether they appear in
the same report, across reports for one patient, or across different patients.
This means terms should target the general concept, not report-specific details.
Being too specific defeats the purpose of grouping equivalent findings together.

You will receive a list of findings extracted from a radiology report, along
with exam metadata and the report text for context. For each finding, propose
2–3 diverse query terms that might match canonical entries in the ontology.

## Term Generation Rules

1. Use standard medical terminology. No acronyms or abbreviations in search
   terms (write "pulmonary embolism", not "PE"; "cholecystectomy", not "CCY").
2. Prefer slightly MORE GENERAL terms over more specific ones. The ontology
   may use a broader name than what appears in the report. For example, for
   "3 mm nonobstructing left renal calculus", good search terms would be
   "renal calculus", "urinary tract calculus", "kidney stone" — NOT
   "nonobstructing renal calculus" or "3 mm kidney stone".
3. NEVER propose terms that are MORE SPECIFIC than the extracted finding name.
   Specificity beyond what the report states risks matching the wrong concept.
4. Make terms diverse — vary word choice, use synonyms, try both lay and
   clinical phrasing. The ontology uses semantic search, so different phrasings
   improve recall.
5. If a finding is a normal-variant or absent finding (e.g., "no ascites"),
   generate terms for the finding itself (e.g., "ascites", "peritoneal fluid"),
   not for the negation.
6. Do not generalize to pure meta-categories like "finding", "disease", or
   "pathology" — these are too abstract to match ontology entries. The broadest
   acceptable term should still name a recognizable clinical concept. Prefer
   "abnormality" when generalizing an observation.
7. For FOCAL findings, "lesion" is the standard generalizing term — a lesion
   is a focal abnormality. Do not use "lesion" for diffuse processes. Do not
   further specialize (e.g., to "mass" or "nodule") unless the finding itself
   uses that term.
8. Findings described in modality-specific technical language (MR signal
   abnormality, CT attenuation change, enhancement/opacification pattern,
   ultrasound echogenicity) should be searched using the technical observation
   term itself — do not reinterpret as a specific diagnosis or pathological
   process.
"""

LOCATION_TERM_SYSTEM = """\
You are a medical informatics assistant. Your task is to propose search query
terms that will be used to look up standardized codes in an anatomic location
index.

The goal is to assign a common anatomic label so that findings at the same
location can be grouped together — within a report, across a patient's history,
or across patients. Terms should target the standardized anatomic structure,
not report-specific phrasing.

You will receive a list of findings extracted from a radiology report, along
with exam metadata. For each finding, propose
1–3 query terms that name the anatomic structure where the finding is located.

## Term Generation Rules

1. Use standard anatomic terminology. No acronyms or abbreviations (write
   "right lower lobe", not "RLL").
2. Name the ANATOMIC STRUCTURE, not the finding. For a finding in the "right
   lower lobe", the terms should be "right lower lobe", "lower lobe of right
   lung" — NOT "right lower lobe opacity" or "right lower lobe nodule".
3. Use the finding's `location` field (body_region, specific_anatomy,
   laterality) as the primary source for terms. If location is null, infer
   from the exam info (body_part, modality) and report context.
4. LATERALITY MATTERS. If a finding is lateralized, include the side in the
   search term. "Left kidney" and "right kidney" are different structures.
5. Make terms diverse where possible — e.g., "right lower lobe" and "lower
   lobe of right lung" for the same structure.
6. If no anatomic location can be reasonably determined, return an empty list
   for that finding.
7. When laterality is "bilateral" OR the anatomy is inherently bilateral
   (e.g., "lung bases", "kidneys", "adrenal glands"), generate SEPARATE terms
   for each side. The index stores lateralized entries individually — there is
   no entry for "kidneys", only "left kidney" and "right kidney".
8. For sub-organ locations, include both a term at the same specificity AND a
   broader parent term one level up the anatomic hierarchy. Use formal anatomic
   synonyms where applicable (e.g., "hepatic segment" for "liver segment").
"""

FINDING_CODE_SELECTOR_SYSTEM = """\
You are a medical informatics assistant. Your task is to select the best
matching finding code for a radiology finding extracted from its description
in a radiology report, given a list of
candidate codes retrieved from an ontology of radiology findings and diagnoses.

The goal of this coding process is to assign a common standardized label to
findings/diagnoses that refer to the same clinical concept. This enables grouping
equivalent findings across reports — whether described differently by different
radiologists, or appearing in different exams for the same patient. A good
match labels the finding at the right level of generality: specific enough to
be clinically meaningful, but general enough that equivalent descriptions
converge on the same code.

## Selection Rules

1. Select the candidate whose canonical meaning best matches the extracted
   finding. Consider the candidate's name, description, synonyms, and tags —
   not just surface string similarity.
2. A SLIGHTLY MORE GENERAL candidate is acceptable and often preferred. For
   example, "urinary tract calculus" is a good match for "renal calculus" —
   it groups all urinary stones under one label, and the specific location is
   captured separately. The goal is convergence on a common concept.
3. A MORE SPECIFIC candidate is NOT acceptable. "Staghorn calculus" is NOT a
   valid match for "renal calculus" — the report does not assert that level of
   specificity, and using it would fragment what should be a single group.
4. If multiple candidates are reasonable, prefer the one whose scope most
   closely matches the finding — not too broad, not too narrow.
5. If NO candidate is a reasonable match, return null for oifm_id. Do not
   force a match. An unresolved finding is better than a wrong code. When
   returning null, you MUST identify the closest candidate and classify
   the rejection reason:
   - "too_specific" — candidate narrows beyond what the report states
   - "too_broad" — candidate is too general to be clinically useful
   - "wrong_concept" — candidate refers to a different clinical entity
   - "definition_mismatch" — the candidate's NAME looks like a match, but
     its description, synonyms, or tags reveal a more specific or different
     concept than the name suggests.
6. The finding's `presence` does NOT affect code selection.
7. Match based on WHAT the finding is, not WHERE it is. Anatomic location is
   coded separately.
8. When the finding is described in modality-specific technical language (e.g.,
   "hypodense lesion", "T2 hyperintense focus"), match based on the underlying
   clinical concept, not the imaging technique.
"""

LOCATION_CODE_SELECTOR_SYSTEM = """\
You are a medical informatics assistant. Your task is to select the best
matching anatomic location(s) for an extracted radiology finding, given a list
of candidate locations retrieved from an anatomic location ontology.

The goal is to assign a standardized anatomic label so that findings at the
same location can be grouped and tracked together across reports and patients.
A "left kidney" finding should receive the same location code regardless of
how the report phrases it.

## Selection Rules

1. Select the candidate(s) that best represent WHERE the finding is located
   based on the finding's location fields and report text.
2. MULTIPLE LOCATIONS are allowed when a finding genuinely spans more than one
   distinct structure. Do NOT select redundant ancestor/descendant pairs.
3. Match the appropriate LEVEL OF SPECIFICITY for clinical grouping.
4. LATERALITY MATTERS. Never select the wrong side.
5. If the finding has no explicit location information, try to INFER a
   reasonable location from the exam type, body part, and report context.
6. Consider the candidate's region, laterality, and hierarchical position
   when choosing between similar candidates.

## Unresolved Reasons

When returning an empty location list, you MUST provide an unresolved_reason:
- "no_candidate_match" — you know where the finding is located, but none of
  the candidates adequately represent that structure.
- "location_unknown" — you cannot determine where the finding is located even
  after considering the report context and exam type.
"""


def _exam_header(exam_info: ExamInfo) -> list[str]:
    return [
        "## EXAM INFO",
        f"- Study: {exam_info.study_description}",
        f"- Modality: {exam_info.modality or '(unknown)'}",
        f"- Body part: {exam_info.body_part or '(unknown)'}",
        "",
    ]


def build_finding_term_user_prompt(exam_info: ExamInfo, findings: Sequence[Finding]) -> str:
    lines = [*_exam_header(exam_info), "## FINDINGS NEEDING FINDING CODES", ""]
    for index, finding in enumerate(findings):
        lines.extend(
            [
                f"### Finding {index}",
                f"- finding_name: {finding.finding_name}",
                f"- presence: {finding.presence}",
                f'- report_text: "{finding.report_text}"',
                "",
            ]
        )
    lines.append("Generate 2-3 diverse search terms for each finding above.")
    return "\n".join(lines)


def build_location_term_user_prompt(exam_info: ExamInfo, findings: Sequence[Finding]) -> str:
    lines = [*_exam_header(exam_info), "## FINDINGS NEEDING LOCATION CODES", ""]
    for index, finding in enumerate(findings):
        location = finding.location
        lines.extend(
            [
                f"### Finding {index}",
                f"- finding_name: {finding.finding_name}",
                f"- presence: {finding.presence}",
                f"- body_region: {location.body_region if location else '(none)'}",
                f"- specific_anatomy: {location.specific_anatomy if location else '(none)'}",
                f"- laterality: {location.laterality if location else '(none)'}",
                f'- report_text: "{finding.report_text}"',
                "",
            ]
        )
    lines.append("Generate 1-3 anatomic location search terms for each finding above.")
    return "\n".join(lines)


def build_finding_selector_user_prompt(
    finding: Finding,
    exam_info: ExamInfo,
    candidates: Sequence[FindingCodeCandidate] | Sequence[IndexEntry],
) -> str:
    lines = [
        "## FINDING",
        f"- finding_name: {finding.finding_name}",
        f"- presence: {finding.presence}",
        f'- report_text: "{finding.report_text}"',
        f"- study: {exam_info.study_description}",
        "",
        "## CANDIDATE FINDING CODES",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        synonyms = ", ".join(candidate.synonyms) if candidate.synonyms else "(none)"
        tags = ", ".join(candidate.tags) if candidate.tags else "(none)"
        lines.extend(
            [
                f"{index}. {candidate.oifm_id}",
                f"   Name: {candidate.name}",
                f"   Description: {candidate.description or '(none)'}",
                f"   Synonyms: {synonyms}",
                f"   Tags: {tags}",
                "",
            ]
        )
    lines.append("Select the best matching candidate, or null if none match.")
    return "\n".join(lines)


def build_location_selector_user_prompt(
    finding: Finding,
    exam_info: ExamInfo,
    candidates: Sequence[LocationCodeCandidate] | Sequence[AnatomicLocation],
) -> str:
    location = finding.location
    lines = [
        "## FINDING",
        f"- finding_name: {finding.finding_name}",
        f"- presence: {finding.presence}",
        f"- body_region: {location.body_region if location else '(none)'}",
        f"- specific_anatomy: {location.specific_anatomy if location else '(none)'}",
        f"- laterality: {location.laterality if location else '(none)'}",
        f'- report_text: "{finding.report_text}"',
        f"- study: {exam_info.study_description}",
        "",
        "## CANDIDATE LOCATIONS",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        containment = candidate.containment_parent.display if candidate.containment_parent else "(root)"
        partof = candidate.partof_parent.display if candidate.partof_parent else "(root)"
        lines.extend(
            [
                f"{index}. {candidate.id}",
                f"   Description: {candidate.description}",
                f"   Region: {candidate.region}",
                f"   Laterality: {candidate.laterality or 'none'}",
                f"   Containment: {containment}",
                f"   Part-of: {partof}",
                "",
            ]
        )
    lines.append(
        "Select the best matching candidate(s), or return an empty list with a reason\n"
        "if no match is possible."
    )
    return "\n".join(lines)
