"""Hand-crafted few-shot examples for radiology report extraction.

These are MODERATE-sized, broadly representative examples showing the expected output
format. They demonstrate present, absent, possible findings with attributes, locations,
and non-finding text classification.

Examples are derived from:
- ct_abdomen_20210826.md → CT abdomen (mix of present/absent/possible, measurements)
- xr_chest_20210614.md → Chest XR (different modality, acute and healed findings)
"""

import json

from finding_extractor.models import (
    ExamInfo,
    ExtractedFinding,
    FindingAttribute,
    FindingLocation,
    NonFindingText,
    ReportExtraction,
)


def get_ct_abdomen_example() -> tuple[str, ReportExtraction]:
    """Return a trimmed CT abdomen example with representative findings.

    Based on: sample_data/example2/ct_abdomen_20210826.md
    Trimmed to ~10 representative findings covering key patterns.
    """
    report_input = """\
History: flank pain, h/o stones

Technique: CT of the abdomen and pelvis without contrast.

Comparison: 06/04/2024

Comment:
The visualized portions of the lower lungs are clear. The heart is not enlarged, \
and no pericardial fluid is identified. Vascular calcifications are present, \
including at the mitral annulus and within the coronary arteries. \
The abdominal aorta is of normal caliber.

The liver appears diffusely decreased in attenuation, which is suggestive of \
fatty infiltration. The gallbladder is normally distended and shows no wall \
thickening or calcified stones. The biliary ducts are not dilated. The pancreas \
is normal in contour and demonstrates no focal abnormality. The spleen is normal \
in size. The adrenal glands are unremarkable.

Both kidneys demonstrate small nonobstructing calculi. Stable bilateral renal \
stones including right lower pole stone measuring approximately 3 mm and left \
interpolar region, measuring about 4\u20135 mm. There is no hydronephrosis. \
Small parapelvic cysts are present in the left kidney. No ureteral stones are seen. \
The urinary bladder is normal in contour. The prostate and seminal vesicles appear \
within normal limits.

The bowel is nondilated, and no areas of wall thickening or surrounding \
inflammatory change are noted.

There is no ascites. No enlarged abdominal or pelvic lymph nodes are identified.

The bones show advanced degenerative changes throughout the thoracic and lumbar \
spine. Flowing osteophytes are present, raising the possibility of diffuse \
idiopathic skeletal hyperostosis.

Impression:
Bilateral nonobstructing renal calculi, similar in size and number compared to \
prior examinations. No evidence of obstruction."""

    expected_output = ReportExtraction(
        exam_info=ExamInfo(
            study_description="CT Abdomen and Pelvis WO contrast",
            study_date="2021-08-26",
            modality="CT",
            body_part="abdomen",
        ),
        findings=[
            # Present: measurements, laterality, change_from_prior, multiple instances
            ExtractedFinding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="right lower pole",
                    laterality="right",
                ),
                attributes=[
                    FindingAttribute(key="size", value="3 mm"),
                    FindingAttribute(key="change_from_prior", value="stable"),
                    FindingAttribute(key="obstruction", value="nonobstructing"),
                ],
                report_text="Stable bilateral renal stones including right lower pole stone measuring approximately 3 mm and left interpolar region, measuring about 4\u20135 mm.",
            ),
            ExtractedFinding(
                finding_name="renal calculus",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="left interpolar region",
                    laterality="left",
                ),
                attributes=[
                    FindingAttribute(key="size", value="4-5 mm"),
                    FindingAttribute(key="change_from_prior", value="stable"),
                    FindingAttribute(key="obstruction", value="nonobstructing"),
                ],
                report_text="Stable bilateral renal stones including right lower pole stone measuring approximately 3 mm and left interpolar region, measuring about 4\u20135 mm.",
            ),
            # Present: suggestive language but clear enough for "present"
            ExtractedFinding(
                finding_name="hepatic steatosis",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="liver",
                ),
                attributes=[
                    FindingAttribute(key="morphology", value="diffuse"),
                ],
                report_text="The liver appears diffusely decreased in attenuation, which is suggestive of fatty infiltration.",
            ),
            # Present: coronary calcification in an abdominal CT (incidental chest finding)
            ExtractedFinding(
                finding_name="coronary artery calcification",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="coronary arteries",
                ),
                attributes=[],
                report_text="Vascular calcifications are present, including at the mitral annulus and within the coronary arteries.",
            ),
            ExtractedFinding(
                finding_name="mitral annulus calcification",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="mitral annulus",
                ),
                attributes=[],
                report_text="Vascular calcifications are present, including at the mitral annulus and within the coronary arteries.",
            ),
            # Present: severity attribute
            ExtractedFinding(
                finding_name="spinal degenerative change",
                presence="present",
                location=FindingLocation(
                    body_region="musculoskeletal",
                    specific_anatomy="thoracic spine",
                ),
                attributes=[
                    FindingAttribute(key="severity", value="advanced"),
                ],
                report_text="The bones show advanced degenerative changes throughout the thoracic and lumbar spine.",
            ),
            ExtractedFinding(
                finding_name="spinal degenerative change",
                presence="present",
                location=FindingLocation(
                    body_region="musculoskeletal",
                    specific_anatomy="lumbar spine",
                ),
                attributes=[
                    FindingAttribute(key="severity", value="advanced"),
                ],
                report_text="The bones show advanced degenerative changes throughout the thoracic and lumbar spine.",
            ),
            # Possible: hedged language
            ExtractedFinding(
                finding_name="flowing osteophytes",
                presence="present",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="lumbar spine",
                ),
                attributes=[
                    FindingAttribute(key="morphology", value="flowing osteophytes"),
                ],
                report_text="Flowing osteophytes are present, raising the possibility of diffuse idiopathic skeletal hyperostosis.",
            ),
            ExtractedFinding(
                finding_name="diffuse idiopathic skeletal hyperostosis",
                presence="possible",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="lumbar spine",
                ),
                attributes=[
                    FindingAttribute(key="morphology", value="flowing osteophytes"),
                ],
                report_text="Flowing osteophytes are present, raising the possibility of diffuse idiopathic skeletal hyperostosis.",
            ),
            # Absent: normal organ → absent finding
            ExtractedFinding(
                finding_name="aortic aneurysm",
                presence="absent",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="abdominal aorta",
                ),
                attributes=[],
                report_text="The abdominal aorta is of normal caliber.",
            ),
            ExtractedFinding(
                finding_name="hydronephrosis",
                presence="absent",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="kidneys",
                ),
                attributes=[],
                report_text="There is no hydronephrosis.",
            ),
            ExtractedFinding(
                finding_name="ascites",
                presence="absent",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="peritoneal cavity",
                ),
                attributes=[],
                report_text="There is no ascites.",
            ),
            ExtractedFinding(
                finding_name="abdominal lymphadenopathy",
                presence="absent",
                location=FindingLocation(
                    body_region="abdomen",
                    specific_anatomy="abdominal and pelvic lymph nodes",
                ),
                attributes=[],
                report_text="No enlarged abdominal or pelvic lymph nodes are identified.",
            ),
        ],
        non_finding_text=[
            NonFindingText(
                text="History: flank pain, h/o stones",
                category="clinical_history",
            ),
            NonFindingText(
                text="Technique: CT of the abdomen and pelvis without contrast.",
                category="technique",
            ),
            NonFindingText(
                text="Comparison: 06/04/2024",
                category="comparison",
            ),
            NonFindingText(
                text="Impression:\nBilateral nonobstructing renal calculi, similar in size and number compared to prior examinations. No evidence of obstruction.",
                category="impression",
            ),
        ],
    )

    return report_input, expected_output


def get_xr_chest_example() -> tuple[str, ReportExtraction]:
    """Return a trimmed chest XR example with representative findings.

    Based on: sample_data/example2/xr_chest_20210614.md
    Trimmed to ~10 representative findings covering key patterns.
    """
    report_input = """\
Chest Radiograph (PA and Lateral)

Date of Exam: June 14, 2021

Technique: Frontal and lateral views of the chest.

Indication: 60-year-old male with fever, cough, and shortness of breath.

Comparison: Chest radiograph, October 12, 2020.

Findings:

Lungs: There is a focal airspace opacity in the right lower lobe consistent \
with pneumonia. No cavitation. The left lung is clear. No pleural effusion or \
pneumothorax.

Cardiomediastinal Silhouette: The heart size is normal. Mitral annular \
calcification is present. Mild coronary artery calcification. The mediastinal \
contours are unremarkable.

Hila: Normal hilar contours bilaterally.

Pleura: No pleural abnormality.

Bones: An acute-appearing superior endplate compression fracture is present at \
T9. Healed fractures of the left 7th and 8th ribs are noted posterolaterally.

Soft Tissues: Unremarkable.

Impression:
1. Right lower lobe pneumonia.
2. Cardiac calcifications.
3. Acute T9 compression fracture. Healed left rib fractures."""

    expected_output = ReportExtraction(
        exam_info=ExamInfo(
            study_description="Chest Radiograph (PA and Lateral)",
            study_date="2021-06-14",
            modality="XR",
            body_part="chest",
        ),
        findings=[
            # Present: acute finding
            ExtractedFinding(
                finding_name="airspace opacity",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="right lower lobe",
                    laterality="right",
                ),
                attributes=[
                    FindingAttribute(key="morphology", value="focal"),
                ],
                report_text="There is a focal airspace opacity in the right lower lobe consistent with pneumonia.",
            ),
            ExtractedFinding(
                finding_name="pneumonia",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="right lower lobe",
                    laterality="right",
                ),
                attributes=[],
                report_text="There is a focal airspace opacity in the right lower lobe consistent with pneumonia.",
            ),
            ExtractedFinding(
                finding_name="mitral annular calcification",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="mitral annulus",
                ),
                attributes=[],
                report_text="Mitral annular calcification is present.",
            ),
            ExtractedFinding(
                finding_name="coronary artery calcification",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="coronary arteries",
                ),
                attributes=[
                    FindingAttribute(key="severity", value="mild"),
                ],
                report_text="Mild coronary artery calcification.",
            ),
            # Present: acute fracture with specific level
            ExtractedFinding(
                finding_name="vertebral compression fracture",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="T9 vertebral body",
                ),
                attributes=[
                    FindingAttribute(key="acuity", value="acute"),
                    FindingAttribute(key="morphology", value="superior endplate compression"),
                ],
                report_text="An acute-appearing superior endplate compression fracture is present at T9.",
            ),
            # Present: healed fractures with laterality
            ExtractedFinding(
                finding_name="rib fracture",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="left 7th rib",
                    laterality="left",
                ),
                attributes=[
                    FindingAttribute(key="acuity", value="healed"),
                    FindingAttribute(key="location", value="posterolateral"),
                ],
                report_text="Healed fractures of the left 7th and 8th ribs are noted posterolaterally.",
            ),
            ExtractedFinding(
                finding_name="rib fracture",
                presence="present",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="left 8th rib",
                    laterality="left",
                ),
                attributes=[
                    FindingAttribute(key="acuity", value="healed"),
                    FindingAttribute(key="location", value="posterolateral"),
                ],
                report_text="Healed fractures of the left 7th and 8th ribs are noted posterolaterally.",
            ),
            # Absent: explicit negation
            ExtractedFinding(
                finding_name="pleural effusion",
                presence="absent",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="pleura",
                ),
                attributes=[],
                report_text="No pleural effusion or pneumothorax.",
            ),
            ExtractedFinding(
                finding_name="pneumothorax",
                presence="absent",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="pleura",
                ),
                attributes=[],
                report_text="No pleural effusion or pneumothorax.",
            ),
            ExtractedFinding(
                finding_name="cardiomegaly",
                presence="absent",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="heart",
                ),
                attributes=[],
                report_text="The heart size is normal.",
            ),
            # Absent: "normal X" implies absent abnormality
            ExtractedFinding(
                finding_name="hilar contour abnormality",
                presence="absent",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="hila",
                    laterality="bilateral",
                ),
                attributes=[],
                report_text="Normal hilar contours bilaterally.",
            ),
            # Absent: "unremarkable" implies absent abnormality
            ExtractedFinding(
                finding_name="soft tissue abnormality",
                presence="absent",
                location=FindingLocation(
                    body_region="chest",
                    specific_anatomy="thoracic soft tissues",
                ),
                attributes=[],
                report_text="Unremarkable.",
            ),
        ],
        non_finding_text=[
            NonFindingText(
                text="Chest Radiograph (PA and Lateral)",
                category="metadata",
            ),
            NonFindingText(
                text="Date of Exam: June 14, 2021",
                category="metadata",
            ),
            NonFindingText(
                text="Technique: Frontal and lateral views of the chest.",
                category="technique",
            ),
            NonFindingText(
                text="Indication: 60-year-old male with fever, cough, and shortness of breath.",
                category="indication",
            ),
            NonFindingText(
                text="Comparison: Chest radiograph, October 12, 2020.",
                category="comparison",
            ),
            NonFindingText(
                text="Impression:\n1. Right lower lobe pneumonia.\n2. Cardiac calcifications.\n3. Acute T9 compression fracture. Healed left rib fractures.",
                category="impression",
            ),
        ],
    )

    return report_input, expected_output


def get_default_examples() -> list[tuple[str, ReportExtraction]]:
    """Return the default set of few-shot examples."""
    return [
        get_ct_abdomen_example(),
        get_xr_chest_example(),
    ]


def format_example_for_prompt(report_text: str, extraction: ReportExtraction) -> str:
    """Format a single example for inclusion in the LLM prompt.

    Returns a formatted string showing the input report and expected output.
    """
    example = {
        "input_report": report_text,
        "output": extraction.model_dump(),
    }
    return json.dumps(example, indent=2)


def get_formatted_examples() -> str:
    """Get all default examples formatted for the system prompt."""
    examples = get_default_examples()
    formatted = []

    for i, (report_text, extraction) in enumerate(examples, 1):
        formatted.append(f"=== EXAMPLE {i} ===")
        formatted.append(format_example_for_prompt(report_text, extraction))
        formatted.append("")

    return "\n".join(formatted)
