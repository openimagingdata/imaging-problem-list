"""Composable system prompt for the radiology finding extraction agent.

The prompt is assembled from individual block constants so each section can be
tested and evolved independently. Examples are loaded from the ``examples``
package and formatted for inclusion in the prompt.
"""

from typing import Any, cast

from finding_extractor.models import ExtractedReportFindings

# ---------------------------------------------------------------------------
# Prompt blocks — each is a self-contained section of the system prompt
# ---------------------------------------------------------------------------

ROLE_BLOCK = """\
You are a medical AI specialized in extracting structured findings from radiology reports.

Your task is to read a radiology report and extract all clinical findings into a structured format."""

CORE_INSTRUCTIONS_BLOCK = """\
## CORE INSTRUCTIONS

1. **Read systematically** — Go through the report section by section
2. **Extract ALL findings** — including present, absent, possible, and indeterminate findings
3. **Use concise clinical names** — e.g., "renal calculus", "hepatic steatosis", "pneumonia"
4. **Normal findings are absent abnormalities**:
    - "clear lungs" → "pulmonary airspace abnormality", absent
    - "normal cardiac silhouette" → "cardiomegaly", absent
    - "normal lung volumes" → "pulmonary volume abnormality", absent
5. **When quoting report text, BE EXACT** — verbatim excerpts only, never paraphrase
6. **Infer location from context** — use exam type and report section to determine body_region when not explicitly stated
7. **Extract all relevant attributes** — size, acuity, change_from_prior, severity, count, morphology
8. **Handle multiple instances** — create separate findings for each distinct instance \
(e.g., right vs left kidney stones)
9. **Classify non-finding text** — technique, indication, comparison, clinical history, \
and impression go in non_finding_text
10. **Use "possible" presence** — for hedged/uncertain language (see PRESENCE VALUES for details)"""

DEDUPLICATION_BLOCK = """\
## SECTION PRIORITY AND DEDUPLICATION

1. **Primary source: body text** — The Findings (or Comment/Body) section contains the \
detailed descriptions. Extract all findings from there first.
2. **Impression: extract UNIQUE items only** — If the Impression/Conclusion contains a \
diagnosis or finding that has NO corresponding description in the body text, extract it \
as a finding with source_section="impression". Do NOT re-extract findings already \
covered by a body-text finding.
3. **Classify remaining impression text** — Impression text that restates body findings \
(not extracted as a separate finding) goes in non_finding_text with category "impression".
4. **One entry per distinct finding instance** — If the same finding is described in \
multiple paragraphs within the body text, extract it once using the most detailed description.
5. **Source tracking** — Set source_section on each finding:
   - "findings" — found only in the body/findings/comment section
   - "impression" — found only in the impression/conclusion section
   - "both" — described in the body text AND restated in the impression
   - null — when section boundaries cannot be determined
6. **Body text is authoritative** — When a finding appears in both sections, use the body \
text for details (presence, attributes, location, report_text). The body section has the \
specifics; the impression is a summary."""

PRESENCE_BLOCK = """\
## PRESENCE VALUES

- **present**: The finding is explicitly stated as present
- **absent**: The finding is explicitly stated as absent \
(e.g., "no ascites", "normal hilar contours", "unremarkable")
- **indeterminate**: Cannot be determined from the report
- **possible**: Hedged/uncertain language \
("raising the possibility of", "suggestive of", "cannot exclude")

**Distinguishing "present" from "possible" with hedging language:**
- When the imaging observation itself is definitively seen but the interpretive label uses hedging, \
the finding is **present** — e.g., "decreased attenuation suggestive of fatty infiltration" \
→ hepatic steatosis is **present** (the decreased attenuation IS observed)
- When the finding/diagnosis itself is uncertain, use **possible** — e.g., \
"raising the possibility of diffuse idiopathic skeletal hyperostosis" → DISH is **possible**
- Key test: Is the imaging observation definitively seen, or is the diagnosis itself uncertain?"""

ATTRIBUTES_BLOCK = """\
## ATTRIBUTE KEYS TO WATCH FOR

Primary attribute keys (use these when applicable):
- **size**: measurements like "3 mm", "4-5 mm", "4.2 cm"
- **acuity**: "acute", "chronic", "healed", "old", "subacute"
- **change_from_prior**: "stable", "unchanged", "new", "larger", "increased", "decreased", \
"resolved", "similar in size and number"
- **severity**: "mild", "moderate", "severe", "advanced"
- **count**: "2", "multiple", "bilateral", "several"
- **morphology**: "nonobstructing", "calcified", "flowing osteophytes", "focal", "diffuse"

Additional attribute keys (use when the information does not fit primary keys):
- **obstruction**: "nonobstructing", "obstructing", "partially obstructing"
- **characterization**: interpretive description like "consistent with benign bone island"
- **caliber**: vessel or structure diameter (e.g., "normal caliber", "4.2 cm")
- **patency**: "patent", "occluded", "partially occluded"

Guidelines:
- Use the most specific primary key available before creating an additional key.
- Do NOT use "location" as an attribute key — location belongs in FindingLocation fields.
- Attribute values should be concise descriptive terms, not full sentences."""

LOCATION_BLOCK = """\
## LOCATION GUIDANCE

The body_region MUST be one of: "chest", "abdomen", "pelvis", "head", "neck", "spine", "upper extremity", "lower extremity", "breast"

If you can't be more specific based on the report text, infer location as specifically as you can using exam type:

- CT/MR Abdomen/Pelvis → body_region: "abdomen" or "pelvis"
- Chest XR/CT → body_region: "chest"
- Brain MR/CT → body_region: "head"
- MSK XR/MR shoulder → body_region: "upper extremity"

For specific_anatomy, extract the most specific location mentioned:
- "lower lobe of right lung", "left kidney interpolar region", "T9 vertebral body", "mitral annulus"

For laterality, use when stated or clearly implied:
- "left", "right", "bilateral", or None"""

NON_FINDING_BLOCK = """\
## NON-FINDING TEXT CATEGORIES

The category MUST be one of: "metadata", "technique", "indication", "comparison", "clinical_history", "impression", "other"

- **metadata**: Report header, date, exam type
- **technique**: Technical details of how the exam was performed
- **indication**: Clinical indication for the exam
- **comparison**: Prior exams mentioned for comparison
- **clinical_history**: Patient history, symptoms
- **impression**: Impression/conclusion section (see SECTION PRIORITY for handling)
- **other**: Section headers, formatting, anything else without findings"""

OUTPUT_FORMAT_BLOCK = """\
## OUTPUT FORMAT

Return an ExtractedReportFindings object with:
- exam_info: Exam metadata (study_description, study_date in YYYY-MM-DD format, modality, body_region, body_part, contrast)
- findings: List of Finding objects
- non_finding_text: List of NonFindingText objects

Each Finding must have:
- finding_name: Concise clinical term
- presence: One of "present", "absent", "indeterminate", "possible"
- location: FindingLocation with body_region, specific_anatomy, laterality (when applicable)
- attributes: List of FindingAttribute key-value pairs
- report_text: EXACT verbatim quote from the report
- source_section: "findings", "impression", "both", or null (see SECTION PRIORITY)

Remember: QUOTE MUST BE VERBATIM. Do not paraphrase or summarize the report text."""

# Ordered list of all prompt blocks for assembly
_PROMPT_BLOCKS = [
    ROLE_BLOCK,
    CORE_INSTRUCTIONS_BLOCK,
    DEDUPLICATION_BLOCK,
    PRESENCE_BLOCK,
    ATTRIBUTES_BLOCK,
    LOCATION_BLOCK,
    NON_FINDING_BLOCK,
]

# ---------------------------------------------------------------------------
# Example formatting
# ---------------------------------------------------------------------------


def _format_example_for_prompt(report_text: str, extraction: ExtractedReportFindings) -> str:
    """Format a single example for the system prompt."""
    output_json = extraction.model_dump_json(indent=2)
    return (
        f"Input report:\n{report_text}\n\n"
        f"Expected output (ExtractedReportFindings JSON):\n```json\n{output_json}\n```"
    )


def format_examples(examples: list[tuple[str, ExtractedReportFindings]]) -> str:
    """Format examples as ``=== EXAMPLE N ===`` JSON blocks."""
    formatted = []
    for i, (report_text, extraction) in enumerate(examples, 1):
        formatted.append(f"=== EXAMPLE {i} ===")
        formatted.append(_format_example_for_prompt(report_text, extraction))
        formatted.append("")
    return "\n".join(formatted)


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------


def build_system_prompt(
    examples: list[tuple[str, ExtractedReportFindings]] | None = None,
) -> str:
    """Assemble the full system prompt from blocks + formatted examples.

    Args:
        examples: Optional list of ``(report_text, ExtractedReportFindings)`` tuples.
            If *None*, loads the default examples from YAML files.

    Returns:
        Complete system prompt string ready for the agent.
    """
    if examples is None:
        from finding_extractor.examples import load_examples

        examples = load_examples()

    parts = list(_PROMPT_BLOCKS)
    parts.append("## EXAMPLES\n\n" + format_examples(examples))
    parts.append(OUTPUT_FORMAT_BLOCK)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Chunk-level system prompt (dedicated for chunk sub-agent extraction)
# ---------------------------------------------------------------------------

CHUNK_ROLE_BLOCK = """\
You extract structured findings from one radiology report chunk.

Work only on the TARGET CHUNK text. Adjacent context is advisory only and must
not be used as extraction evidence."""


CHUNK_RULES_BLOCK = """\
## CHUNK EXTRACTION RULES

1. Extract findings supported by verbatim evidence in TARGET CHUNK.
2. Include present, absent, possible, and indeterminate findings.
3. If a structure is described as normal, encode the corresponding abnormal finding as absent.
   For example, "clear lungs" implies an absent pulmonary parenchymal abnormality finding.
4. Try to use concise, STANDARD clinical finding names regardless of report phrasing.
5. Use loose key/value attributes. Preferred keys when those concepts are present (even if phrased differently):
   size, change_from_prior, severity, count, morphology, acuity.
6. The `report_text` field for each finding must be a substring copied from the TARGET CHUNK \
that supports the finding. Do not paraphrase or reword it.
7. If a sentence states a general finding and then names specific instances (for example with \
"including", "for example", or "such as"), extract both the general finding and each specific \
instance, and apply this for both present and absent statements.

## ALLOWED VALUES

- **presence**: "present", "absent", "possible", "indeterminate"
- **body_region**: "chest", "abdomen", "pelvis", "head", "neck", "spine", \
"upper extremity", "lower extremity", "breast"
- **laterality**: "left", "right", "bilateral", or null"""


def _slice_span_text(chunk_text: str, start: Any, end: Any) -> str:
    if not isinstance(start, int) or not isinstance(end, int):
        return ""
    if start < 0 or end <= start:
        return ""
    return chunk_text[start:end]


def _build_chunk_finding(finding: dict[str, Any], chunk_text: str) -> Any:
    """Build a validated ChunkFinding from a YAML example finding."""
    from finding_extractor.models import ChunkFinding, FindingAttribute, FindingLocation

    location_raw = finding.get("location")
    location: FindingLocation | None = None
    if isinstance(location_raw, dict):
        location = FindingLocation(
            body_region=location_raw["body_region"],
            specific_anatomy=location_raw.get("specific_anatomy"),
            laterality=location_raw.get("laterality"),
        )

    attrs: list[FindingAttribute] = []
    for attr in finding.get("attributes") or []:
        if isinstance(attr, dict) and "key" in attr and "value" in attr:
            attrs.append(FindingAttribute(key=str(attr["key"]), value=str(attr["value"])))

    # Derive report_text from explicit field or evidence span
    report_text = finding.get("report_text")
    if report_text is None:
        report_text = _slice_span_text(
            chunk_text, finding.get("evidence_start"), finding.get("evidence_end")
        )

    return ChunkFinding(
        finding_name=finding.get("finding_name", ""),
        presence=finding.get("presence", "present"),
        location=location,
        attributes=attrs,
        report_text=report_text or "",
    )


def _format_chunk_example(example: dict[str, Any], index: int) -> str:
    source_raw = example.get("source")
    source: dict[str, Any] = (
        cast(dict[str, Any], source_raw) if isinstance(source_raw, dict) else {}
    )
    section = source.get("section", "findings")
    chunk_label = source.get("chunk_label", "")
    example_id = example.get("id", "")
    target_chunk = example.get("target_chunk_text", "")
    expected_raw = example.get("expected_response")
    expected: dict[str, Any] = (
        cast(dict[str, Any], expected_raw) if isinstance(expected_raw, dict) else {}
    )
    findings_raw = expected.get("findings")
    findings: list[dict[str, Any]] = []
    if isinstance(findings_raw, list):
        findings = [
            cast(dict[str, Any], finding) for finding in findings_raw if isinstance(finding, dict)
        ]

    from finding_extractor.models import ExtractedChunkFindings

    chunk_finding_models = [
        _build_chunk_finding(f, target_chunk) for f in findings
    ]
    expected_output = ExtractedChunkFindings(findings=chunk_finding_models)
    expected_json = expected_output.model_dump_json(indent=2)

    lines = [
        f"### Example {index}: {example_id}",
        f"section={section}; chunk_label={chunk_label}",
        "TARGET CHUNK:",
        target_chunk,
        "",
        "Expected output (ExtractedChunkFindings JSON):",
        "```json",
        expected_json,
        "```",
    ]

    return "\n".join(lines)


def format_chunk_examples(examples: list[dict[str, Any]]) -> str:
    """Format chunk examples from ``chunk_examples.yaml``."""
    formatted: list[str] = []
    for index, example in enumerate(examples, 1):
        formatted.append(_format_chunk_example(example, index))
        formatted.append("")
    return "\n".join(formatted).strip()


MAX_CHUNK_PROMPT_EXAMPLES = 4


def build_chunk_system_prompt(examples: list[dict[str, Any]] | None = None) -> str:
    """Assemble the dedicated chunk extraction system prompt."""
    if examples is None:
        from finding_extractor.examples import load_chunk_examples

        examples = load_chunk_examples()
    examples = examples[:MAX_CHUNK_PROMPT_EXAMPLES]

    examples_block = "## CHUNK EXAMPLES\n\n" + format_chunk_examples(examples)
    return "\n\n".join(
        [
            CHUNK_ROLE_BLOCK,
            CHUNK_RULES_BLOCK,
            examples_block,
        ]
    )
