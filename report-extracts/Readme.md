# Report extraction notes

## First Prompt

```
Extract every finding explicitly stated or implied in the following chest CT report. Each finding must be reduced to its core concept (no descriptors) and labeled with presence or absence only. Follow these rules:
	1.	Extract every positive finding (present) and every explicitly negative finding (absent).
	2.	Treat similarity statements (stable/unchanged/similar) as present.
	3.	Treat statements indicating no change in number (e.g., “no new,” “no additional,” “no increase in number”) as present for the existing finding(s). For example: “5 mm pulmonary nodule. No new pulmonary nodules” → pulmonary nodule present.
	4.	Treat statements denying new, additional, or suspicious lesions (e.g., “no new osseous lesions,” “no new suspicious pulmonary nodules,” “no new suspicious lytic or blastic lesions”) as confirmation of the existing finding(s) being present/stable. Do not mark these as absent.
	5.	Treat normality statements (normal, clear, intact, without abnormality) as the corresponding abnormal finding absent (e.g., “normal heart size” → cardiomegaly absent).
	6.	Treat resolution statements (resolved/no longer present) as absent.
	7.	Do not include any other attributes such as location, size, severity, density, composition, type, laterality, or any other descriptive terms. Reduce to the essential finding (e.g., “RUL bronchial obstruction” → “bronchial obstruction present”).
	8.	For lymph nodes, extract by station, but ignore laterality (e.g., “right supraclavicular lymphadenopathy” = supraclavicular lymphadenopathy).
	9.	For contralateral comparisons, extract as present if mentioned (e.g., “small right pleural effusion. no left pleural effusion” → pleural effusion present).
	10.	Extract from both the findings and impression sections. Collapse duplicates but keep diagnosis statements as separate (e.g., “right lower lobe pulmonary opacity likely pneumonia” = pneumonia present).
	11.	Do not include information from the clinical indication.
	12.	Output two non-overlapping lists: A) Present and B) Absent
```

## JSON Version

```
Extract every finding explicitly stated or implied in the following chest CT report. Each finding must be reduced to its core concept (no descriptors) and labeled with presence or absence only. Follow these rules:
	1.	Extract every positive finding (present) and every explicitly negative finding (absent).
	2.	Treat similarity statements (stable/unchanged/similar) as present.
	3.	Treat statements indicating no change in number (e.g., “no new,” “no additional,” “no increase in number”) as present for the existing finding(s). For example: “5 mm pulmonary nodule. No new pulmonary nodules” → pulmonary nodule present.
	4.	Treat statements denying new, additional, or suspicious lesions (e.g., “no new osseous lesions,” “no new suspicious pulmonary nodules,” “no new suspicious lytic or blastic lesions”) as confirmation of the existing finding(s) being present/stable. Do not mark these as absent.
	5.	Treat normality statements (normal, clear, intact, without abnormality) as the corresponding abnormal finding absent (e.g., “normal heart size” → cardiomegaly absent).
	6.	Treat resolution statements (resolved/no longer present) as absent.
	7.	Do not include any other attributes such as location, size, severity, density, composition, type, laterality, or any other descriptive terms. Reduce to the essential finding (e.g., “RUL bronchial obstruction” → “bronchial obstruction present”).
	8.	For lymph nodes, extract by station, but ignore laterality (e.g., “right supraclavicular lymphadenopathy” = supraclavicular lymphadenopathy).
	9.	For contralateral comparisons, extract as present if mentioned (e.g., “small right pleural effusion. no left pleural effusion” → pleural effusion present).
	10.	Extract from both the findings and impression sections. Collapse duplicates but keep diagnosis statements as separate (e.g., “right lower lobe pulmonary opacity likely pneumonia” = pneumonia present).
	11.	Do not include information from the clinical indication.
	12.	Output a structured JSON object for every finding with this exact structure:

{{
        "findings": [
            {{
                "finding_name": "pneumothorax",
                "attributes": {{ "presence": "absent" }},
                "text": "No pneumothorax"
            }}
```

## Head CT and Brain MRI version 1

```
Prompt:

Extract every finding explicitly stated or implied in the following head CT or brain MRI report. Each finding must be reduced to its core concept (no modifiers) and labeled with presence or absence only. Follow these rules carefully:
	1.	Extract every positive finding (present) and every explicitly negative finding (absent).
	2.	Treat similarity or stability statements (“stable,” “unchanged,” “no interval change”) as present.
	3.	Treat statements indicating “no new,” “no additional,” or “no increase in number” as present for the existing finding(s). Example: “Chronic lacunar infarcts. No new infarcts.” → infarct present.
	4.	Treat statements denying new or suspicious lesions (“no new hemorrhage,” “no new mass”) as confirmation that the original finding is present/stable, not absent.
	5.	Treat normality statements (“ventricles normal in size,” “sinuses clear,” “no mass effect”) as the corresponding finding absent.
	6.	Treat resolution statements (“resolved,” “no longer seen”) as absent.
	7.	Do not include location, laterality, size, chronicity, severity, or descriptive qualifiers. Reduce each to the essential concept.
	8.	Extract from both Findings and Impression sections; collapse duplicates but keep diagnosis statements as separate (e.g., “findings consistent with acute infarct” → infarct present).
	9.	Ignore information from the clinical indication.

Category-specific rules:
	•	INFARCT / ISCHEMIA: Reduce all infarct mentions to the vascular territory only (e.g., “acute right MCA infarct” → “MCA infarct present”). Collapse synonymous terms (“acute infarction,” “acute ischemia,” “restricted diffusion,” “acute stroke”) to infarct. Chronic or old infarcts are still marked present.
	•	HEMORRHAGE: Collapse “hemorrhage,” “hematoma,” “blood,” “contusion with hemorrhagic component,” “microbleed” to hemorrhage. Include all intracranial types (subdural, epidural, subarachnoid, intraventricular, parenchymal). Do not specify size or acuity.
	•	MASSES / LESIONS: Collapse “mass,” “lesion,” “tumor,” “enhancing lesion,” “metastasis,” “nodule” to mass. If a specific diagnosis is named (e.g., “meningioma,” “metastatic disease”), extract both “mass” and the diagnosis concept.
	•	HYDROCEPHALUS: Collapse “hydrocephalus,” “ventriculomegaly,” “dilated ventricular system out of proportion to sulci” to hydrocephalus. Ignore etiology or pattern.
	•	VENTRICLES: Collapse all ventricular descriptors to the core concept. “Ventricular dilatation,” “ventriculomegaly,” “dilation of temporal horns,” “enlarged ventricles” → ventricular enlargement. “Ventricular effacement,” “narrowing,” “compression,” “collapse” → ventricular compression.
	•	BRAINSTEM / POSTERIOR FOSSA: Extract findings for the brainstem or cerebellum as present or absent. Collapse midbrain/pons/medulla to brainstem unless multiple findings are distinct.
	•	BONES / SKULL: Collapse “skull fracture,” “osseous lesion,” “craniotomy,” “calvarial defect” to calvarial abnormality. “Intact calvarium/skull base” → calvarial abnormality absent.
	•	EDEMA: Collapse “edema,” “swelling,” “hypoattenuation with mass effect,” “T2/FLAIR hyperintensity due to edema” to edema present.
	•	MASS EFFECT / HERNIATION: Collapse “mass effect,” “midline shift,” “uncal herniation,” “tonsillar herniation,” “subfalcine herniation,” “effacement of sulci/cisterns” to mass effect present. “No mass effect” or “no midline shift” → mass effect absent.
	•	ORBITS: Collapse “orbital mass,” “proptosis,” “enophthalmos,” “optic nerve abnormality,” “globe deformity” to orbital abnormality. “Orbits normal/intact” → orbital abnormality absent.
	•	SINUSES / MASTOIDS: Collapse “sinus disease,” “mucosal thickening,” “air-fluid level,” “opacification,” “mastoid effusion” to sinus disease. “Sinuses clear” or “mastoids clear” → sinus disease absent.

Concept-lumping examples:
	•	“Ventricular effacement” → ventricular compression
	•	“Dilation of temporal horns” → ventricular enlargement
	•	“Acute right MCA infarct” → MCA infarct
	•	“Pontine restricted diffusion” → brainstem infarct
	•	“Midline shift 5 mm” or “subfalcine herniation” → mass effect
	•	“Dilated ventricles out of proportion to sulci” → hydrocephalus
```

