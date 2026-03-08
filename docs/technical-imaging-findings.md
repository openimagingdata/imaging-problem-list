# Technical Imaging Findings — Reference

Radiology reports frequently describe findings using modality-specific technical language rather than clinical diagnoses. These "technical findings" describe what the radiologist observes on the images — signal characteristics, density, enhancement patterns, echogenicity — without necessarily committing to an underlying pathological process.

This document catalogs common categories of technical findings across imaging modalities. It serves as a reference for:
- Ensuring the finding ontology has coverage for these observation-level concepts
- Guiding search term generation when coding technical findings
- Identifying gaps where new ontology entries may be needed

**Status:** Draft — needs review against the finding ontology for coverage assessment.

---

## CT Attenuation-Based Findings

CT measures tissue density in Hounsfield units. Findings are often described relative to surrounding tissue.

| Technical term | Meaning | Example report language |
|---|---|---|
| Hypodense/hypoattenuating lesion | Lower density than surrounding tissue | "hypodense lesion in the liver" |
| Hyperdense/hyperattenuating lesion | Higher density than surrounding tissue | "hyperdense focus in the right kidney" |
| Fat-containing lesion | Contains macroscopic fat (negative HU) | "fat-containing adrenal lesion" |
| Calcified lesion/calcification | Contains calcium (high HU) | "calcified granuloma in the lung" |
| Hypoattenuating parenchyma | Diffuse low attenuation of an organ | "diffuse decreased hepatic attenuation" |
| Ground-glass opacity | Hazy increased lung attenuation | "ground-glass opacity in the right lower lobe" |

**Search term considerations:** "Hypodense liver lesion" → search for "liver lesion", "focal liver lesion", "hepatic lesion". The attenuation descriptor is a characteristic of the lesion, not the finding category itself.

---

## MR Signal-Based Findings

MRI characterizes tissue by signal intensity on different pulse sequences (T1, T2, FLAIR, DWI, etc.).

| Technical term | Meaning | Example report language |
|---|---|---|
| T2 signal abnormality | Abnormal signal on T2-weighted images | "T2 hyperintense focus in the white matter" |
| T1 signal abnormality | Abnormal signal on T1-weighted images | "T1 shortening in the posterior pituitary" |
| Diffusion restriction | High signal on DWI with low ADC | "focus of restricted diffusion in the left cerebellum" |
| Susceptibility artifact/blooming | Signal dropout on GRE/SWI sequences | "susceptibility artifact suggesting hemorrhage" |
| Marrow signal abnormality | Abnormal bone marrow signal | "marrow signal abnormality in L3 vertebral body" |
| White matter signal abnormality | Abnormal signal in cerebral white matter | "scattered white matter T2 hyperintensities" |
| Enhancement (post-contrast) | Abnormal gadolinium uptake | "enhancing lesion in the right frontal lobe" |

**Search term considerations:** "Marrow signal abnormality" should be searched as exactly that — it is the observation. Do NOT reinterpret as "bone marrow edema" or "marrow infiltration", which are specific diagnoses that may or may not be the cause.

---

## Enhancement/Opacification Patterns

Enhancement describes how tissue takes up contrast agent over time. Relevant to CT, MRI, and angiographic studies.

| Technical term | Meaning | Example report language |
|---|---|---|
| Enhancing lesion | Lesion that takes up contrast | "enhancing mass in the pancreas" |
| Non-enhancing lesion | Lesion that does not take up contrast | "non-enhancing cystic lesion" |
| Arterial enhancement | Enhancement during arterial phase | "arterially enhancing liver lesion" |
| Washout | Loss of enhancement on delayed phase | "arterial enhancement with washout" |
| Abnormal enhancement | Enhancement pattern different from expected | "abnormal mucosal enhancement" |
| Filling defect | Lack of opacification within a vessel | "filling defect in the pulmonary artery" |
| Abnormal venous opacification | Abnormal contrast pattern in veins | "absent opacification of the left renal vein" |
| Flow abnormality | Abnormal vascular flow pattern | "hepatic venous flow abnormality" |

**Search term considerations:** "Filling defect in the pulmonary artery" is the technical observation; the clinical interpretation might be "pulmonary embolism", but they are distinct concepts. The ontology may have entries at either level. Enhancement-based findings in a specific organ (e.g., "abnormal hepatic venous enhancement") should be searched using the physiological concept ("hepatic venous flow abnormality") alongside the technical term.

---

## Ultrasound Echogenicity-Based Findings

Ultrasound characterizes tissue by how it reflects sound waves.

| Technical term | Meaning | Example report language |
|---|---|---|
| Hypoechoic lesion | Less echogenic than surrounding tissue | "hypoechoic lesion in the thyroid" |
| Hyperechoic lesion | More echogenic than surrounding tissue | "hyperechoic liver lesion" |
| Anechoic structure | No internal echoes (fluid-filled) | "anechoic cyst in the kidney" |
| Isoechoic lesion | Same echogenicity as surrounding tissue | "isoechoic nodule in the liver" |
| Heterogeneous echotexture | Mixed echogenicity | "heterogeneous echotexture of the thyroid" |
| Increased echogenicity | Diffusely increased echogenicity | "increased hepatic echogenicity" |
| Posterior acoustic shadowing | Sound blocked by dense structure | "echogenic focus with posterior shadowing" |
| Increased vascularity | Abnormal blood flow on Doppler | "increased vascularity on color Doppler" |

**Search term considerations:** "Increased hepatic echogenicity" is the technical observation for what is clinically interpreted as hepatic steatosis. Both the technical term and the clinical interpretation are valid search terms, but they represent different levels of certainty.

---

## Nuclear Medicine / PET Findings

| Technical term | Meaning | Example report language |
|---|---|---|
| FDG-avid lesion | Lesion with increased metabolic activity | "FDG-avid lymph node in the mediastinum" |
| Photopenic area | Decreased radiotracer uptake | "photopenic defect in the right lobe of the thyroid" |
| Hot spot/increased uptake | Focal increased radiotracer activity | "increased uptake in the L4 vertebral body" |
| Tracer accumulation | Abnormal radiotracer concentration | "delayed tracer accumulation in the gallbladder fossa" |

---

## Cross-Cutting Patterns

Some technical finding patterns span multiple modalities:

- **Focal vs diffuse:** Focal findings are discrete, bounded abnormalities ("lesion"). Diffuse findings affect an entire organ or region ("disease", "abnormality", "process").
- **Descriptors that narrow but don't diagnose:** Size, shape, margins, multiplicity, temporal change — these characterize a finding without specifying what it is.
- **Observation vs interpretation:** The same imaging appearance can be described at observation level ("T2 hyperintense marrow signal") or interpretation level ("marrow edema"). Reports often mix both. The ontology needs entries at the observation level to capture what's actually seen.

---

## TODO

- [ ] Audit the finding ontology against these categories to identify coverage gaps
- [ ] Determine which technical terms resolve via fast-path vs need LLM search
- [ ] Decide whether technical-observation entries and clinical-interpretation entries should be separate or merged in the ontology
- [ ] Add examples of each category to the coding agent prompt if needed after ontology audit
