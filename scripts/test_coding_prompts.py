#!/usr/bin/env python3
"""Full coding pipeline test against real extraction data.

Runs all 5 phases:
  1. Fast-path resolution (finding + location indexes)
  2. LLM term generation (finding terms + location terms in parallel)
  3. Index search (search_batch for candidates)
  4. LLM code selection (finding + location selectors per finding)
  5. Assembly and output

Usage:
    uv run --env-file .env python scripts/test_coding_prompts.py [--max-findings N]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Literal

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from findingmodel import Index
from anatomic_locations import AnatomicLocationIndex

# ── Logfire setup ─────────────────────────────────────────────────
logfire.configure(send_to_logfire="if-token-present", service_name="coding-prompt-test")
logfire.instrument_pydantic_ai()

MODEL = "google-gla:gemini-3-flash-preview"
SEARCH_LIMIT = 10
MAX_CONCURRENCY = 5

# ══════════════════════════════════════════════════════════════════
# PYDANTIC RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════

# Phase 2: Term generation
class FindingTerms(BaseModel):
    finding_index: int
    search_terms: list[str]

class FindingTermsBatchOutput(BaseModel):
    results: list[FindingTerms]

class LocationTerms(BaseModel):
    finding_index: int
    search_terms: list[str]

class LocationTermsBatchOutput(BaseModel):
    results: list[LocationTerms]

# Phase 4: Code selection
RejectionReason = Literal[
    "too_specific",         # candidate narrows beyond what the report states
    "too_broad",            # candidate is too general to be clinically useful
    "wrong_concept",        # different clinical entity entirely
    "definition_mismatch",  # name matches but desc/synonyms are inconsistent
]

class FindingCodeSelection(BaseModel):
    """LLM output for finding code selector."""
    oifm_id: str | None = Field(
        description="Selected OIFM finding code, or null if no candidate matches."
    )
    reasoning: str = Field(
        description="Brief explanation of why this candidate was selected (or why none matched)."
    )
    # Required when oifm_id is null:
    closest_candidate_id: str | None = Field(
        default=None,
        description="When no match is selected, the candidate that came closest.",
    )
    rejection_reason: RejectionReason | None = Field(
        default=None,
        description="Why the closest candidate was rejected.",
    )

class LocationCodeSelection(BaseModel):
    """LLM output for location code selector."""
    location_ids: list[str] = Field(
        default_factory=list,
        description="Selected location ID(s). May be multiple for bilateral/spanning findings.",
    )
    unresolved_reason: Literal["no_candidate_match", "location_unknown"] | None = Field(
        default=None,
        description="Reason if no locations selected.",
    )
    reasoning: str = Field(
        description="Brief explanation of the selection.",
    )


# ══════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS (from docs/coding-agent-prompts.md)
# ══════════════════════════════════════════════════════════════════

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

## Examples

- "coronary artery calcification" → ["coronary artery calcifications", "coronary calcification", "coronary artery calcium"]
- "moderate hiatal hernia" → ["hiatal hernia", "hiatus hernia", "diaphragmatic hernia"]
- "bibasilar atelectasis" → ["atelectasis", "basilar atelectasis", "lung atelectasis"]
- "liver steatosis" → ["hepatic steatosis", "fatty liver", "liver fat"]
- "hepatomegaly" → ["hepatomegaly", "enlarged liver", "liver enlargement"] — NOT "liver disease" or "hepatic finding"
- "focal splenic hypodensity" → ["splenic lesion", "focal splenic lesion"] — NOT "splenic mass" or "spleen disease"
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
with exam metadata and the report text for context. For each finding, propose
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

## Examples

- "pancreatic head" → ["pancreatic head", "head of pancreas"]
- "right lower lobe posterior basal segment" → ["right lower lobe", "lower lobe of right lung"]
- spine (none), exam: CT Cervical Spine → ["cervical spine", "cervical vertebral column"]
- "left hilum" → ["left pulmonary hilum", "left hilum", "hilum of left lung"]
- "lung bases" (bilateral) → ["left lung base", "right lung base", "left lower lobe", "right lower lobe"]
- "adrenal glands" (bilateral) → ["left adrenal gland", "right adrenal gland"]
- "hepatic segment 4" → ["hepatic segment 4", "liver segment 4", "left lobe of liver"]
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
     concept than the name suggests. This flags ontology entries that need
     cleanup (e.g., a candidate named "renal lesion" whose description says
     "a mass in the kidney" and synonyms include "renal tumor").
6. The finding's `presence` (present, absent, possible, indeterminate) does
   NOT affect code selection. The same code applies whether the finding is
   present or absent — presence is tracked separately.
7. Match based on WHAT the finding is, not WHERE it is. Anatomic location is
   coded separately. Two findings at the same location can have different
   finding codes, and the same finding type can occur in different locations.
8. When the finding is described in modality-specific technical language (e.g.,
   "hypodense lesion", "T2 hyperintense focus"), match based on the underlying
   clinical concept, not the imaging technique. The same finding observed on
   CT, MRI, or ultrasound should receive the same code.
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
   distinct structure (e.g., bilateral findings → left and right separately,
   or a finding spanning two adjacent structures). However, do NOT select
   redundant ancestor/descendant pairs — if you select "left renal pelvis",
   do not also select "left kidney". Always prefer the most specific
   appropriate location.
3. Match the appropriate LEVEL OF SPECIFICITY for clinical grouping. If the
   report says "left kidney", select "left kidney" — not just "kidney" (too
   broad, loses laterality) and not "cortex of left kidney" (too specific
   unless the report explicitly mentions the cortex). When in doubt, prefer
   the level that enables the most useful clinical grouping.
4. LATERALITY MATTERS. If the finding specifies left or right, prefer a
   lateralized candidate that matches. If only a generic (non-lateralized)
   candidate is available (e.g., "kidney" instead of "left kidney"), selecting
   it is acceptable — laterality is already captured in the finding's location
   field. However, NEVER select the WRONG side (e.g., "right kidney" for a
   left-sided finding).
5. If the finding has no explicit location information, try to INFER a
   reasonable location from the exam type, body part, and report context.
   For example, "diffuse osteopenia" on a chest CT should be assigned to the
   chest wall or thorax. Only return an empty list if no location can
   reasonably be determined even with contextual inference.
6. Consider the candidate's region, laterality, and hierarchical position
   (containment path) when choosing between similar candidates. The hierarchy
   shows how structures are nested (e.g., "right kidney" is contained within
   "retroperitoneum"), which helps disambiguate candidates with similar names.

## Unresolved Reasons

When returning an empty location list, you MUST provide an unresolved_reason:
- "no_candidate_match" — you know where the finding is located, but none of
  the candidates adequately represent that structure. (This flags an index
  coverage gap.)
- "location_unknown" — you cannot determine where the finding is located even
  after considering the report context and exam type.
"""


# ══════════════════════════════════════════════════════════════════
# FAST-PATH HELPERS
# ══════════════════════════════════════════════════════════════════

async def finding_fast_path(index: Index, name: str) -> str | None:
    """Try exact match by name/synonym. Returns oifm_id or None."""
    entry = await index.get(name)
    return entry.oifm_id if entry else None


def location_fast_path(loc_index: AnatomicLocationIndex, specific_anatomy: str | None) -> str | None:
    """Try exact match by description/synonym. Returns location id or None."""
    if not specific_anatomy:
        return None
    try:
        loc = loc_index.get(specific_anatomy)
        return loc.id
    except KeyError:
        return None


# ══════════════════════════════════════════════════════════════════
# USER PROMPT BUILDERS
# ══════════════════════════════════════════════════════════════════

def build_finding_term_user_prompt(
    exam_info: dict,
    report_text: str,
    findings: list[tuple[int, dict]],
) -> str:
    lines = [
        "## EXAM INFO",
        f"- Study: {exam_info.get('study_description', '(unknown)')}",
        f"- Modality: {exam_info.get('modality') or '(unknown)'}",
        f"- Body part: {exam_info.get('body_part') or '(unknown)'}",
        "",
        "## REPORT TEXT (reference context)",
        report_text[:3000],
        "",
        "## FINDINGS NEEDING FINDING CODES",
        "",
    ]
    for batch_idx, (_orig_idx, f) in enumerate(findings):
        lines.append(f"### Finding {batch_idx}")
        lines.append(f"- finding_name: {f['finding_name']}")
        lines.append(f"- presence: {f['presence']}")
        lines.append(f'- report_text: "{f["report_text"]}"')
        lines.append("")
    lines.append("Generate 2-3 diverse search terms for each finding above.")
    return "\n".join(lines)


def build_location_term_user_prompt(
    exam_info: dict,
    report_text: str,
    findings: list[tuple[int, dict]],
) -> str:
    lines = [
        "## EXAM INFO",
        f"- Study: {exam_info.get('study_description', '(unknown)')}",
        f"- Modality: {exam_info.get('modality') or '(unknown)'}",
        f"- Body part: {exam_info.get('body_part') or '(unknown)'}",
        "",
        "## REPORT TEXT (reference context)",
        report_text[:3000],
        "",
        "## FINDINGS NEEDING LOCATION CODES",
        "",
    ]
    for batch_idx, (_orig_idx, f) in enumerate(findings):
        loc = f.get("location") or {}
        lines.append(f"### Finding {batch_idx}")
        lines.append(f"- finding_name: {f['finding_name']}")
        lines.append(f"- presence: {f['presence']}")
        lines.append(f"- body_region: {loc.get('body_region') or '(none)'}")
        lines.append(f"- specific_anatomy: {loc.get('specific_anatomy') or '(none)'}")
        lines.append(f"- laterality: {loc.get('laterality') or '(none)'}")
        lines.append(f'- report_text: "{f["report_text"]}"')
        lines.append("")
    lines.append("Generate 1-3 anatomic location search terms for each finding above.")
    return "\n".join(lines)


def build_finding_selector_user_prompt(
    finding: dict,
    exam_info: dict,
    candidates: list,  # list of IndexEntry
) -> str:
    lines = [
        "## FINDING",
        f"- finding_name: {finding['finding_name']}",
        f"- presence: {finding['presence']}",
        f'- report_text: "{finding["report_text"]}"',
        f"- study: {exam_info.get('study_description', '(unknown)')}",
        "",
        "## CANDIDATE FINDING CODES",
        "",
    ]
    for i, c in enumerate(candidates):
        synonyms = ", ".join(c.synonyms) if c.synonyms else "(none)"
        tags = ", ".join(c.tags) if c.tags else "(none)"
        lines.append(f"{i+1}. {c.oifm_id}")
        lines.append(f"   Name: {c.name}")
        lines.append(f"   Description: {c.description or '(none)'}")
        lines.append(f"   Synonyms: {synonyms}")
        lines.append(f"   Tags: {tags}")
        lines.append("")
    lines.append("Select the best matching candidate, or null if none match.")
    return "\n".join(lines)


def build_location_selector_user_prompt(
    finding: dict,
    exam_info: dict,
    candidates: list,  # list of AnatomicLocation
) -> str:
    loc = finding.get("location") or {}
    lines = [
        "## FINDING",
        f"- finding_name: {finding['finding_name']}",
        f"- presence: {finding['presence']}",
        f"- body_region: {loc.get('body_region') or '(none)'}",
        f"- specific_anatomy: {loc.get('specific_anatomy') or '(none)'}",
        f"- laterality: {loc.get('laterality') or '(none)'}",
        f'- report_text: "{finding["report_text"]}"',
        f"- study: {exam_info.get('study_description', '(unknown)')}",
        "",
        "## CANDIDATE LOCATIONS",
        "",
    ]
    for i, c in enumerate(candidates):
        containment = c.containment_parent.display if c.containment_parent else "(root)"
        partof = c.partof_parent.display if c.partof_parent else "(root)"
        lines.append(f"{i+1}. {c.id}")
        lines.append(f"   Description: {c.description}")
        lines.append(f"   Region: {c.region}")
        lines.append(f"   Laterality: {c.laterality or 'none'}")
        lines.append(f"   Containment: {containment}")
        lines.append(f"   Part-of: {partof}")
        lines.append("")
    lines.append(
        "Select the best matching candidate(s), or return an empty list with a reason\n"
        "if no match is possible."
    )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════

async def main() -> None:
    t0 = time.perf_counter()
    max_findings = 20
    if "--max-findings" in sys.argv:
        idx = sys.argv.index("--max-findings")
        max_findings = int(sys.argv[idx + 1])

    output_path = Path("/tmp/coding_pipeline_output.txt")

    # Collect output lines for file
    output_lines: list[str] = []

    def emit(msg: str = "") -> None:
        """Print and collect output."""
        print(msg)
        output_lines.append(msg)

    # ── Load data ────────────────────────────────────────────────
    data_path = Path("/tmp/validator_demo_output_20260225.json")
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        sys.exit(1)

    data = json.loads(data_path.read_text())
    exam_info = data["exam_info"]
    findings = data["findings"]
    report_text = data.get("report_text", "")
    if not report_text:
        report_text = " ".join(f["report_text"] for f in findings[:20])

    emit(f"Loaded {len(findings)} findings from extraction")
    emit(f"Model: {MODEL}")
    emit(f"Max findings for LLM phases: {max_findings}")

    # ── Initialize indexes ───────────────────────────────────────
    finding_index = Index()
    location_index = AnatomicLocationIndex()

    # ── Create named agents once ─────────────────────────────────
    finding_term_agent = Agent(
        MODEL,
        system_prompt=FINDING_TERM_SYSTEM,
        output_type=FindingTermsBatchOutput,
        name="finding_term_generator",
    )
    location_term_agent = Agent(
        MODEL,
        system_prompt=LOCATION_TERM_SYSTEM,
        output_type=LocationTermsBatchOutput,
        name="location_term_generator",
    )
    finding_selector = Agent(
        MODEL,
        system_prompt=FINDING_CODE_SELECTOR_SYSTEM,
        output_type=FindingCodeSelection,
        name="finding_code_selector",
    )
    location_selector = Agent(
        MODEL,
        system_prompt=LOCATION_CODE_SELECTOR_SYSTEM,
        output_type=LocationCodeSelection,
        name="location_code_selector",
    )

    with logfire.span(
        "coding_pipeline",
        model=MODEL,
        total_findings=len(findings),
        max_findings=max_findings,
    ):

        # ══════════════════════════════════════════════════════════
        # PHASE 1: FAST-PATH RESOLUTION
        # ══════════════════════════════════════════════════════════
        emit(f"\n{'=' * 70}")
        emit("PHASE 1: FAST-PATH RESOLUTION")
        emit(f"{'=' * 70}")

        with logfire.span("phase1_fast_path") as fp_span:
            need_finding_terms: list[tuple[int, dict]] = []
            need_location_terms: list[tuple[int, dict]] = []
            finding_resolved: dict[int, str] = {}
            location_resolved: dict[int, str] = {}
            finding_resolved_name: dict[int, str] = {}
            location_resolved_name: dict[int, str] = {}

            seen_finding_names: set[str] = set()
            seen_anatomy: set[str] = set()

            for i, f in enumerate(findings):
                name = f["finding_name"]
                loc = f.get("location") or {}
                specific_anatomy = loc.get("specific_anatomy")

                # Finding fast-path
                entry = await finding_index.get(name)
                if entry:
                    finding_resolved[i] = entry.oifm_id
                    finding_resolved_name[i] = entry.name
                elif name not in seen_finding_names:
                    need_finding_terms.append((i, f))
                    seen_finding_names.add(name)

                # Location fast-path
                if specific_anatomy:
                    try:
                        loc_entry = location_index.get(specific_anatomy)
                        location_resolved[i] = loc_entry.id
                        location_resolved_name[i] = loc_entry.description
                    except KeyError:
                        if specific_anatomy not in seen_anatomy:
                            need_location_terms.append((i, f))
                            seen_anatomy.add(specific_anatomy)
                else:
                    if name not in seen_anatomy:
                        need_location_terms.append((i, f))
                        seen_anatomy.add(name)

            fp_span.set_attribute("findings_resolved", len(finding_resolved))
            fp_span.set_attribute("findings_need_llm", len(need_finding_terms))
            fp_span.set_attribute("locations_resolved", len(location_resolved))
            fp_span.set_attribute("locations_need_llm", len(need_location_terms))

        logfire.info(
            "Fast-path complete: {findings_resolved} findings, {locations_resolved} locations resolved",
            findings_resolved=len(finding_resolved),
            locations_resolved=len(location_resolved),
        )

        emit(f"\nFinding fast-path: {len(finding_resolved)} resolved, "
              f"{len(need_finding_terms)} unique names need LLM terms")
        emit(f"Location fast-path: {len(location_resolved)} resolved, "
              f"{len(need_location_terms)} need LLM terms")

        # Show fast-path results
        emit("\n  Finding fast-path hits:")
        shown_names: set[str] = set()
        for i, oifm_id in sorted(finding_resolved.items()):
            name = findings[i]["finding_name"]
            if name not in shown_names:
                emit(f"    + {name!r} -> {oifm_id} ({finding_resolved_name[i]})")
                shown_names.add(name)

        emit("\n  Finding fast-path misses:")
        for _, f in need_finding_terms:
            emit(f"    - {f['finding_name']!r}")

        emit("\n  Location fast-path hits (sample):")
        shown_locs: set[str] = set()
        for i, loc_id in sorted(location_resolved.items()):
            anat = (findings[i].get("location") or {}).get("specific_anatomy", "?")
            if anat not in shown_locs:
                emit(f"    + {anat!r} -> {loc_id} ({location_resolved_name[i]})")
                shown_locs.add(anat)
                if len(shown_locs) >= 15:
                    emit(f"    ... and {len(location_resolved) - 15} more")
                    break

        emit("\n  Location fast-path misses:")
        for _, f in need_location_terms:
            anat = (f.get("location") or {}).get("specific_anatomy", "(none)")
            emit(f"    - {f['finding_name']!r} at {anat!r}")

        # ══════════════════════════════════════════════════════════
        # PHASE 2: LLM TERM GENERATION
        # ══════════════════════════════════════════════════════════
        test_finding_items = need_finding_terms[:max_findings]
        test_location_items = need_location_terms[:max_findings]

        if not test_finding_items and not test_location_items:
            emit("\nAll findings resolved via fast-path! Nothing to test.")
            output_path.write_text("\n".join(output_lines))
            return

        emit(f"\n{'=' * 70}")
        emit(f"PHASE 2: LLM TERM GENERATION ({MODEL})")
        emit(f"{'=' * 70}")

        with logfire.span(
            "phase2_term_generation",
            finding_count=len(test_finding_items),
            location_count=len(test_location_items),
        ):
            finding_user_prompt = build_finding_term_user_prompt(
                exam_info, report_text, test_finding_items
            )
            location_user_prompt = build_location_term_user_prompt(
                exam_info, report_text, test_location_items
            )

            emit(f"  Sending {len(test_finding_items)} findings to finding term generator...")
            emit(f"  Sending {len(test_location_items)} findings to location term generator...")

            finding_result, location_result = await asyncio.gather(
                finding_term_agent.run(finding_user_prompt),
                location_term_agent.run(location_user_prompt),
            )

        # Build term maps: batch_index -> search_terms
        finding_terms_map: dict[int, list[str]] = {}
        for ft in finding_result.output.results:
            finding_terms_map[ft.finding_index] = ft.search_terms

        location_terms_map: dict[int, list[str]] = {}
        for lt in location_result.output.results:
            location_terms_map[lt.finding_index] = lt.search_terms

        emit("\n  Finding terms generated:")
        for batch_idx, (_orig_idx, f) in enumerate(test_finding_items):
            terms = finding_terms_map.get(batch_idx, [])
            emit(f"    [{batch_idx}] {f['finding_name']!r} -> {terms}")

        emit("\n  Location terms generated:")
        for batch_idx, (_orig_idx, f) in enumerate(test_location_items):
            terms = location_terms_map.get(batch_idx, [])
            anat = (f.get("location") or {}).get("specific_anatomy", "(none)")
            emit(f"    [{batch_idx}] {f['finding_name']!r} at {anat!r} -> {terms}")

        # ══════════════════════════════════════════════════════════
        # PHASE 3: INDEX SEARCH
        # ══════════════════════════════════════════════════════════
        emit(f"\n{'=' * 70}")
        emit("PHASE 3: INDEX SEARCH (search_batch)")
        emit(f"{'=' * 70}")

        with logfire.span("phase3_index_search") as search_span:
            all_finding_queries = list({t for terms in finding_terms_map.values() for t in terms})
            all_location_queries = list({t for terms in location_terms_map.values() for t in terms})

            search_span.set_attribute("finding_queries", len(all_finding_queries))
            search_span.set_attribute("location_queries", len(all_location_queries))

            emit(f"  Searching {len(all_finding_queries)} unique finding queries...")
            emit(f"  Searching {len(all_location_queries)} unique location queries...")

            finding_search_raw, location_search_raw = await asyncio.gather(
                finding_index.search_batch(all_finding_queries, limit=SEARCH_LIMIT),
                location_index.search_batch(all_location_queries, limit=SEARCH_LIMIT),
            )

        # Build per-finding deduplicated candidate lists
        finding_candidates: dict[int, list] = {}
        for batch_idx in finding_terms_map:
            seen_ids: set[str] = set()
            candidates = []
            for term in finding_terms_map[batch_idx]:
                for entry in finding_search_raw.get(term, []):
                    if entry.oifm_id not in seen_ids:
                        candidates.append(entry)
                        seen_ids.add(entry.oifm_id)
            finding_candidates[batch_idx] = candidates

        location_candidates: dict[int, list] = {}
        for batch_idx in location_terms_map:
            seen_ids: set[str] = set()
            candidates = []
            for term in location_terms_map[batch_idx]:
                for loc in location_search_raw.get(term, []):
                    if loc.id not in seen_ids:
                        candidates.append(loc)
                        seen_ids.add(loc.id)
            location_candidates[batch_idx] = candidates

        emit("\n  Finding candidates:")
        for batch_idx, (_orig_idx, f) in enumerate(test_finding_items):
            cands = finding_candidates.get(batch_idx, [])
            names = [f"{c.oifm_id} ({c.name})" for c in cands[:5]]
            more = f" ... +{len(cands)-5}" if len(cands) > 5 else ""
            emit(f"    [{batch_idx}] {f['finding_name']!r}: {len(cands)} candidates")
            for n in names:
                emit(f"          {n}")
            if more:
                emit(f"          {more}")

        emit("\n  Location candidates:")
        for batch_idx, (_orig_idx, f) in enumerate(test_location_items):
            cands = location_candidates.get(batch_idx, [])
            descs = [f"{c.id} ({c.description})" for c in cands[:5]]
            more = f" ... +{len(cands)-5}" if len(cands) > 5 else ""
            emit(f"    [{batch_idx}] {f['finding_name']!r}: {len(cands)} candidates")
            for d in descs:
                emit(f"          {d}")
            if more:
                emit(f"          {more}")

        # ══════════════════════════════════════════════════════════
        # PHASE 4: LLM CODE SELECTION
        # ══════════════════════════════════════════════════════════
        emit(f"\n{'=' * 70}")
        emit(f"PHASE 4: LLM CODE SELECTION ({MODEL})")
        emit(f"{'=' * 70}")

        with logfire.span("phase4_code_selection") as sel_span:
            semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

            finding_selections: dict[int, FindingCodeSelection] = {}
            location_selections: dict[int, LocationCodeSelection] = {}

            async def select_finding_code(batch_idx: int, finding: dict) -> None:
                cands = finding_candidates.get(batch_idx, [])
                if not cands:
                    finding_selections[batch_idx] = FindingCodeSelection(
                        oifm_id=None,
                        reasoning="No candidates from search",
                        rejection_reason="wrong_concept",
                    )
                    return
                async with semaphore:
                    with logfire.span(
                        "select_finding_code {finding_name}",
                        finding_name=finding["finding_name"],
                        batch_idx=batch_idx,
                        num_candidates=len(cands),
                    ) as span:
                        prompt = build_finding_selector_user_prompt(finding, exam_info, cands)
                        result = await finding_selector.run(prompt)
                        sel = result.output
                        # Validate: selected ID must be in candidates
                        if sel.oifm_id:
                            valid_ids = {c.oifm_id for c in cands}
                            if sel.oifm_id not in valid_ids:
                                logfire.warn(
                                    "Invalid selection {oifm_id} not in candidates",
                                    oifm_id=sel.oifm_id,
                                    finding_name=finding["finding_name"],
                                )
                                sel = FindingCodeSelection(
                                    oifm_id=None,
                                    reasoning=f"Invalid selection {sel.oifm_id} not in candidates",
                                )
                        span.set_attribute("selected_oifm_id", sel.oifm_id or "(none)")
                        span.set_attribute("rejection_reason", sel.rejection_reason or "(n/a)")
                        finding_selections[batch_idx] = sel

            async def select_location_code(batch_idx: int, finding: dict) -> None:
                cands = location_candidates.get(batch_idx, [])
                if not cands:
                    location_selections[batch_idx] = LocationCodeSelection(
                        location_ids=[],
                        unresolved_reason="no_candidate_match",
                        reasoning="No candidates from search",
                    )
                    return
                async with semaphore:
                    with logfire.span(
                        "select_location_code {finding_name}",
                        finding_name=finding["finding_name"],
                        batch_idx=batch_idx,
                        num_candidates=len(cands),
                    ) as span:
                        prompt = build_location_selector_user_prompt(finding, exam_info, cands)
                        result = await location_selector.run(prompt)
                        sel = result.output
                        # Validate: all IDs must be in candidates
                        if sel.location_ids:
                            valid_ids = {c.id for c in cands}
                            invalid = [lid for lid in sel.location_ids if lid not in valid_ids]
                            if invalid:
                                logfire.warn(
                                    "Invalid location IDs {invalid} removed",
                                    invalid=invalid,
                                    finding_name=finding["finding_name"],
                                )
                                sel.location_ids = [lid for lid in sel.location_ids if lid in valid_ids]
                        span.set_attribute("selected_location_ids", sel.location_ids or ["(none)"])
                        location_selections[batch_idx] = sel

            # Launch all selections in parallel (bounded by semaphore)
            finding_tasks = [
                select_finding_code(batch_idx, f)
                for batch_idx, (_orig_idx, f) in enumerate(test_finding_items)
            ]
            location_tasks = [
                select_location_code(batch_idx, f)
                for batch_idx, (_orig_idx, f) in enumerate(test_location_items)
            ]

            emit(f"  Running {len(finding_tasks)} finding + {len(location_tasks)} location "
                 f"selections (concurrency={MAX_CONCURRENCY})...")

            await asyncio.gather(*finding_tasks, *location_tasks)

            # Summarize on the phase span
            finding_coded = sum(1 for s in finding_selections.values() if s.oifm_id)
            finding_unresolved = len(finding_selections) - finding_coded
            loc_coded = sum(1 for s in location_selections.values() if s.location_ids)
            loc_unresolved = len(location_selections) - loc_coded
            sel_span.set_attribute("findings_coded", finding_coded)
            sel_span.set_attribute("findings_unresolved", finding_unresolved)
            sel_span.set_attribute("locations_coded", loc_coded)
            sel_span.set_attribute("locations_unresolved", loc_unresolved)

        emit(f"\n  Selection complete. ({len(finding_selections)} finding, "
             f"{len(location_selections)} location)")

        # ══════════════════════════════════════════════════════════
        # PHASE 5: ASSEMBLY AND OUTPUT
        # ══════════════════════════════════════════════════════════
        emit(f"\n{'=' * 70}")
        emit("PHASE 5: ASSEMBLY")
        emit(f"{'=' * 70}")

        with logfire.span("phase5_assembly"):
            # Summary table — findings
            emit("\n  FINDING CODE RESULTS:")
            emit(f"  {'Finding Name':<45} {'Code':<25} {'Name':<30} {'Method'}")
            emit(f"  {'-'*45} {'-'*25} {'-'*30} {'-'*12}")

            # Fast-path resolved
            shown: set[str] = set()
            for i, oifm_id in sorted(finding_resolved.items()):
                name = findings[i]["finding_name"]
                if name not in shown:
                    entry_name = finding_resolved_name.get(i, "?")
                    emit(f"  {name:<45} {oifm_id:<25} {entry_name:<30} fast-path")
                    shown.add(name)

            # LLM-selected
            for batch_idx, (_orig_idx, f) in enumerate(test_finding_items):
                name = f["finding_name"]
                sel = finding_selections.get(batch_idx)
                if sel and sel.oifm_id:
                    cands = finding_candidates.get(batch_idx, [])
                    oifm_name = next(
                        (c.name for c in cands if c.oifm_id == sel.oifm_id), "?"
                    )
                    emit(f"  {name:<45} {sel.oifm_id:<25} {oifm_name:<30} llm")
                else:
                    reason = sel.reasoning[:40] if sel else "no selection"
                    emit(f"  {name:<45} {'(unresolved)':<25} {reason:<30} llm")

            # Rejection analysis for unresolved findings
            rejections = [
                (f["finding_name"], sel)
                for batch_idx, (_orig_idx, f) in enumerate(test_finding_items)
                if (sel := finding_selections.get(batch_idx)) and not sel.oifm_id
            ]
            if rejections:
                emit("\n  UNRESOLVED FINDING ANALYSIS:")
                for finding_name, sel in rejections:
                    emit(f"    {finding_name!r}")
                    emit(f"      closest: {sel.closest_candidate_id or '(none)'}")
                    emit(f"      reason:  {sel.rejection_reason or '(not classified)'}")
                    emit(f"      detail:  {sel.reasoning}")

                # Highlight definition mismatches specifically
                def_mismatches = [
                    (fn, s) for fn, s in rejections
                    if s.rejection_reason == "definition_mismatch"
                ]
                if def_mismatches:
                    emit("\n  DEFINITION MISMATCHES (ontology entries needing cleanup):")
                    for finding_name, sel in def_mismatches:
                        logfire.warn(
                            "Definition mismatch: {finding_name} ~> {candidate_id}",
                            finding_name=finding_name,
                            candidate_id=sel.closest_candidate_id,
                            reasoning=sel.reasoning,
                        )
                        emit(f"    {finding_name!r} ~> {sel.closest_candidate_id}")
                        emit(f"      {sel.reasoning}")

            # Summary table — locations
            emit("\n  LOCATION CODE RESULTS:")
            emit(f"  {'Finding Name':<35} {'Anatomy':<25} {'Location ID(s)':<35} {'Method'}")
            emit(f"  {'-'*35} {'-'*25} {'-'*35} {'-'*12}")

            # Fast-path
            shown_loc: set[str] = set()
            for i, loc_id in sorted(location_resolved.items()):
                anat = (findings[i].get("location") or {}).get("specific_anatomy", "?")
                key = f"{findings[i]['finding_name']}:{anat}"
                if key not in shown_loc:
                    emit(f"  {findings[i]['finding_name']:<35} {anat:<25} "
                         f"{loc_id:<35} fast-path")
                    shown_loc.add(key)

            # LLM-selected
            for batch_idx, (_orig_idx, f) in enumerate(test_location_items):
                sel = location_selections.get(batch_idx)
                anat = (f.get("location") or {}).get("specific_anatomy", "(none)")
                if sel and sel.location_ids:
                    cands = location_candidates.get(batch_idx, [])
                    id_to_desc = {c.id: c.description for c in cands}
                    loc_strs = [f"{lid} ({id_to_desc.get(lid, '?')})" for lid in sel.location_ids]
                    emit(f"  {f['finding_name']:<35} {anat:<25} "
                         f"{', '.join(sel.location_ids):<35} llm")
                    for ls in loc_strs:
                        emit(f"  {'':35} {'':25} -> {ls}")
                else:
                    reason = sel.unresolved_reason if sel else "no selection"
                    emit(f"  {f['finding_name']:<35} {anat:<25} "
                         f"{'(unresolved: ' + str(reason) + ')':<35} llm")

        # ══════════════════════════════════════════════════════════
        # USAGE SUMMARY
        # ══════════════════════════════════════════════════════════
        emit(f"\n{'=' * 70}")
        emit("USAGE SUMMARY")
        emit(f"{'=' * 70}")

        f_usage = finding_result.usage()
        l_usage = location_result.usage()
        emit(f"  Finding term gen:  {f_usage.input_tokens:,} in / {f_usage.output_tokens:,} out")
        emit(f"  Location term gen: {l_usage.input_tokens:,} in / {l_usage.output_tokens:,} out")

        emit(f"\n  Finding codes:  {len(finding_resolved)} fast-path + {finding_coded} llm "
             f"= {len(finding_resolved) + finding_coded} coded, {finding_unresolved} unresolved")
        emit(f"  Location codes: {len(location_resolved)} fast-path + {loc_coded} llm "
             f"= {len(location_resolved) + loc_coded} coded, {loc_unresolved} unresolved")

        elapsed = time.perf_counter() - t0
        emit(f"\n  Wall clock: {elapsed:.1f}s")

    # ── Write output file ────────────────────────────────────────
    output_path.write_text("\n".join(output_lines))
    print(f"\nOutput written to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
