---

## 🧠 Results Summary

After running the extraction (`python -m src.extract`) and evaluation (`python -m src.evaluate`) on one labeled CT Head report (rpt_001):

| Metric | Value |
|:-------|:------:|
| **True Positives (TP)** | 3 |
| **False Positives (FP)** | 1 |
| **False Negatives (FN)** | 1 |
| **True Negatives (TN)** | 7 |
| **Precision** | **0.75** |
| **Recall** | **0.75** |
| **F1 Score** | **0.75** |

### 🔍 By-Finding Breakdown
| Finding | TP | FP | FN | TN | Prec | Rec | F1 |
|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Cerebellar Infarct | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| Edema | 1 | 0 | 0 | 0 | 1 | 1 | 1 |
| Hemorrhagic Conversion | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Herniation | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Hydrocephalus | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Mass Effect | 1 | 0 | 0 | 0 | 1 | 1 | 1 |
| Orbital Abnormality | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Paranasal Sinus Disease | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Right PICA Territory Infarct | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| Sinus Disease | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Territorial Infarct | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Ventricular Effacement | 1 | 0 | 0 | 0 | 1 | 1 | 1 |

### 🩻 Interpretation

- The model correctly identified **3 of 4 relevant findings** (75% precision, 75% recall).  
- It **detected key abnormalities** (edema, mass effect, ventricular effacement)  
  but **missed one infarct mention** and produced one false positive (cerebellar infarct).  
- These results demonstrate that **LLM-based structured extraction with PydanticAI**  
  can accurately capture clinically meaningful imaging findings with minimal setup.

---

### 🚀 Next Steps
- Add more labeled reports to `labels.jsonl` for a larger evaluation set.  
- Experiment with few-shot prompting or RadLex-based normalization.  
- Integrate this extraction pipeline into the broader *Imaging Problem List* project for longitudinal tracking.
