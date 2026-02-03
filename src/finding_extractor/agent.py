"""Pydantic AI agent for extracting structured findings from radiology reports.

This module defines the extraction agent with:
- Instructions with detailed extraction guidance
- Few-shot examples
- Model configuration with reasoning effort support (OpenAI GPT-5 family)
- Structured output via Tool Output mode (default)
- Post-extraction validation
"""

import os

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModelSettings

from finding_extractor.examples import get_formatted_examples
from finding_extractor.models import ReportExtraction, ValidationResult

# Default model configuration
DEFAULT_MODEL = "openai:gpt-5-mini"

# Valid reasoning effort values by model (per OpenAI docs)
# GPT-5/5-mini/5-nano: minimal, low, medium, high (default: medium)
# GPT-5.1/5.2: none, low, medium, high (default: none)
REASONING_EFFORT_VALUES: dict[str, list[str]] = {
    "gpt-5": ["minimal", "low", "medium", "high"],
    "gpt-5-mini": ["minimal", "low", "medium", "high"],
    "gpt-5-nano": ["minimal", "low", "medium", "high"],
    "gpt-5.1": ["none", "low", "medium", "high"],
    "gpt-5.2": ["none", "low", "medium", "high"],
}

DEFAULT_REASONING: dict[str, str] = {
    "gpt-5": "medium",
    "gpt-5-mini": "medium",
    "gpt-5-nano": "medium",
    "gpt-5.1": "none",
    "gpt-5.2": "none",
}

INSTRUCTIONS = """\
You are a medical AI specialized in extracting structured findings from radiology reports.

Your task is to read a radiology report and extract all clinical findings into a structured format.

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
10. **Use "possible" presence** — for hedged/uncertain language like "raising the possibility of", \
"suggestive of", "cannot exclude"

## PRESENCE VALUES

- **present**: The finding is explicitly stated as present
- **absent**: The finding is explicitly stated as absent \
(e.g., "no ascites", "normal hilar contours", "unremarkable")
- **indeterminate**: Cannot be determined from the report
- **possible**: Hedged/uncertain language \
("raising the possibility of", "suggestive of", "cannot exclude")

## ATTRIBUTE KEYS TO WATCH FOR

- **size**: measurements like "3 mm", "4-5 mm", "4.2 cm"
- **acuity**: "acute", "chronic", "healed", "old", "subacute"
- **change_from_prior**: "stable", "unchanged", "new", "larger", "increased", "decreased", \
"resolved", "similar in size and number"
- **severity**: "mild", "moderate", "severe", "advanced"
- **count**: "2", "multiple", "bilateral", "several"
- **morphology**: "nonobstructing", "calcified", "flowing osteophytes", "focal", "diffuse"

## LOCATION GUIDANCE

The body_region should be one of: chest, abdomen, pelvis, head, neck, upper extremity, lower extremity, breast

If you can't be more specific based on the report text, infer location as specifically as you can using exam type:

- CT/MR Abdomen/Pelvis → body_region: "abdomen" or "pelvis"
- Chest XR/CT → body_region: "chest"
- Brain MR/CT → body_region: "head"
- MSK XR/MR shoulder → body_region: "upper extremity"

For specific_anatomy, extract the most specific location mentioned:
- "lower lobe of right lung", "left kidney interpolar region", "T9 vertebral body", "mitral annulus"

For laterality, use when stated or clearly implied:
- "left", "right", "bilateral", or None

## NON-FINDING TEXT CATEGORIES

- **metadata**: Report header, date, exam type
- **technique**: Technical details of how the exam was performed
- **indication**: Clinical indication for the exam
- **comparison**: Prior exams mentioned for comparison
- **clinical_history**: Patient history, symptoms
- **impression**: Impression/conclusion section (findings here are typically restated from above)
- **other**: Section headers, formatting, anything else without findings

## EXAMPLES

{examples}

## OUTPUT FORMAT

Return a ReportExtraction object with:
- exam_info: Exam metadata (study_description, study_date, modality, body_part)
- findings: List of ExtractedFinding objects
- non_finding_text: List of NonFindingText objects

Each ExtractedFinding must have:
- finding_name: Concise clinical term
- presence: One of "present", "absent", "indeterminate", "possible"
- location: FindingLocation with body_region, specific_anatomy, laterality (when applicable)
- attributes: List of FindingAttribute key-value pairs
- report_text: EXACT verbatim quote from the report

Remember: QUOTE MUST BE VERBATIM. Do not paraphrase or summarize the report text.\
"""


def _build_instructions() -> str:
    """Build the agent instructions with embedded few-shot examples."""
    examples = get_formatted_examples()
    return INSTRUCTIONS.format(examples=examples)


def _extract_model_name(model: str) -> str:
    """Extract the model name from a full model identifier.

    E.g., 'openai:gpt-5-mini' -> 'gpt-5-mini'
    """
    return model.split(":")[-1].split("/")[-1]


def _get_reasoning_effort(model: str) -> str | None:
    """Get the appropriate reasoning effort for the model.

    Checks FINDING_EXTRACTOR_REASONING env var first, then falls back to model default.

    Args:
        model: The model identifier (e.g., "openai:gpt-5-mini")

    Returns:
        The reasoning effort string, or None if not a supported reasoning model
    """
    model_name = _extract_model_name(model)

    if model_name not in REASONING_EFFORT_VALUES:
        return None

    valid_values = REASONING_EFFORT_VALUES[model_name]
    default = DEFAULT_REASONING[model_name]

    env_reasoning = os.getenv("FINDING_EXTRACTOR_REASONING")
    if env_reasoning and env_reasoning in valid_values:
        return env_reasoning

    return default


def _get_model_settings(model: str, reasoning: str | None = None) -> OpenAIChatModelSettings | None:
    """Build OpenAIChatModelSettings for the agent.

    Args:
        model: The model identifier
        reasoning: Optional override for reasoning effort

    Returns:
        OpenAIChatModelSettings if reasoning effort applies, None otherwise
    """
    model_name = _extract_model_name(model)

    effort = reasoning or _get_reasoning_effort(model)

    if effort and model_name in REASONING_EFFORT_VALUES:
        return OpenAIChatModelSettings(openai_reasoning_effort=effort)  # type: ignore[typeddict-item]

    return None


def create_agent(model: str | None = None) -> Agent[None, ReportExtraction]:
    """Create and configure the finding extraction agent.

    Args:
        model: Optional model override. Defaults to openai:gpt-5-mini or
               FINDING_EXTRACTOR_MODEL env var.

    Returns:
        Configured Agent instance with ReportExtraction output type
    """
    if model is None:
        model = os.getenv("FINDING_EXTRACTOR_MODEL", DEFAULT_MODEL)

    instructions = _build_instructions()
    model_settings = _get_model_settings(model)

    if model_settings is not None:
        return Agent[None, ReportExtraction](
            model,
            instructions=instructions,
            output_type=ReportExtraction,
            model_settings=model_settings,
        )

    return Agent[None, ReportExtraction](
        model,
        instructions=instructions,
        output_type=ReportExtraction,
    )


def build_prompt(report_text: str, exam_description: str | None = None) -> str:
    """Build the user prompt for the extraction agent.

    Args:
        report_text: The full text of the radiology report
        exam_description: Optional exam description for context (e.g., modality, body part)

    Returns:
        Formatted prompt string
    """
    prompt_parts = []

    if exam_description:
        prompt_parts.append(f"Exam Description: {exam_description}")
        prompt_parts.append("")

    prompt_parts.append("RADIOLOGY REPORT:")
    prompt_parts.append("-" * 40)
    prompt_parts.append(report_text)
    prompt_parts.append("-" * 40)
    prompt_parts.append("")
    prompt_parts.append(
        "Extract all findings from this report into the structured format described above."
    )

    return "\n".join(prompt_parts)


async def extract_findings(
    report_text: str,
    exam_description: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
) -> ReportExtraction:
    """Run the extraction agent on a radiology report.

    Args:
        report_text: The full text of the radiology report
        exam_description: Optional exam description for context
        model: Optional model override
        reasoning: Optional reasoning effort override

    Returns:
        ReportExtraction containing all extracted findings
    """
    agent = create_agent(model)

    run_settings = None
    if reasoning:
        model_id = model or os.getenv("FINDING_EXTRACTOR_MODEL", DEFAULT_MODEL)
        run_settings = _get_model_settings(model_id, reasoning)

    prompt = build_prompt(report_text, exam_description)

    if run_settings:
        result = await agent.run(prompt, model_settings=run_settings)
    else:
        result = await agent.run(prompt)

    return result.output


def validate_extraction(
    report_text: str,
    extraction: ReportExtraction,
) -> ValidationResult:
    """Validate a ReportExtraction against the original report text.

    Performs:
    - Verbatim check: Verify each report_text is a substring of the original report
    - Coverage check: Identify any text segments that may have been skipped

    Args:
        report_text: The original report text
        extraction: The extracted findings to validate

    Returns:
        ValidationResult with errors and warnings
    """
    verbatim_errors = []
    coverage_warnings = []

    # Check verbatim quotes in findings
    for i, finding in enumerate(extraction.findings):
        if finding.report_text not in report_text:
            verbatim_errors.append(
                f"Finding {i} ({finding.finding_name}): report_text not found verbatim in report. "
                f"Quote: '{finding.report_text[:100]}...'"
            )

    # Check non-finding text verbatim
    for i, non_finding in enumerate(extraction.non_finding_text):
        if non_finding.text not in report_text:
            verbatim_errors.append(
                f"Non-finding {i} ({non_finding.category}): text not found verbatim in report. "
                f"Text: '{non_finding.text[:100]}...'"
            )

    # Coverage check (informational)
    extracted_texts = [f.report_text for f in extraction.findings]
    extracted_texts.extend(nf.text for nf in extraction.non_finding_text)

    report_lines = report_text.split("\n")
    unaccounted_lines = []

    for line in report_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        found = any(line_stripped in extracted for extracted in extracted_texts)
        if not found:
            unaccounted_lines.append(line_stripped)

    if unaccounted_lines:
        coverage_warnings.append(
            f"Some report lines may not be fully accounted for: {len(unaccounted_lines)} lines. "
            f"Example: '{unaccounted_lines[0][:80]}...'"
        )

    return ValidationResult(
        is_valid=len(verbatim_errors) == 0,
        verbatim_errors=verbatim_errors,
        coverage_warnings=coverage_warnings,
    )
