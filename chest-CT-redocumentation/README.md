# Re-documentation burden on serial chest CT: rules, taxonomy, and classification code

This folder holds the matching and classification rules, the study taxonomy, and the code that applies them. The code matches each patient's findings across the patient's CTs and classifies every finding on a follow-up CT. It contains no report text, no extracted findings, and no patient data.

## Contents

| File | What it is |
|---|---|
| `classify_findings.py` | The matching and classification code. Each function's docstring states the rule it applies. |
| `LICENSE` | MIT license. |
| `rules/taxonomy.csv` | The study taxonomy: a hierarchy of chest findings from general to specific. Each code lists its parent. |
| `rules/study_added_codes.csv` | Codes the study added to the taxonomy, in the same format. |
| `rules/identity_keys.csv` | For each finding type that recurs, which attributes distinguish two separate findings of that type: `none` (a patient has one, such as emphysema), `site`, `laterality`, or `site+laterality`. A type not listed is distinguished by site and laterality. |
| `rules/permanent_findings.csv` | Taxonomy codes labeled permanent: findings that do not go away on their own or with medical treatment. |
| `rules/anatomic_locations.csv` | The Anatomic Locations index (anatomiclocations.org), reduced to what matching reads: each location, the location that contains it, and the same location without a side. |

The declared rule tables (terms that name one finding, severity steps, conflicting descriptors, and containment the index does not state) are constants at the top of `classify_findings.py`.

## Input

One CSV file with one row per finding extracted from the FINDINGS section of one report. A taxonomy code and an anatomic site are already assigned. List each report's findings in report order.

| Field | Content |
|---|---|
| `finding_id` | Unique identifier of the finding. Ties are broken in the text order of this field. |
| `patient_id` | Patient identifier. |
| `exam_order` | Order of the CT among the patient's CTs, 1 for the first CT. |
| `report_order` | Position of the finding in its report, 1 for the first. |
| `finding_name` | The finding as the radiologist named it. |
| `code` | Taxonomy code name, or empty when no code was assigned. An uncoded finding matches only a finding with the same name. |
| `presence` | `present` (stated without hedging), `possible` or `indeterminate` (hedged), or `absent`. Absent findings are skipped. |
| `site_key` | Anatomic Locations index identifier, or the site text when no location was assigned, or empty. |
| `site_kind` | `resolved` for an index identifier, `text` for site text. |
| `laterality` | `left`, `right`, `bilateral`, or empty. |
| `state` | What the comparison wording says: `unchanged`, `changed`, `mixed`, or `unstated`. |
| `state_basis` | `presence` when the only comparison word is "persistent" or "persists", otherwise empty. |
| `sentence_state` | The state read from the sentence alone, with the same values as `state`. |
| `temporal_field` | The extraction's own temporal label for the finding, such as "new", or empty. It sets the finding's state only when `sentence_state` is `unstated`. Where several findings share a sentence, it also shows which finding a word of change such as "new" or "increased" was written with, so that the word is not applied to the other findings in the sentence. |
| `sentence` | The report sentence the finding came from. |
| `attributes_json` | The finding's attributes as a JSON list of key and value pairs, such as `[{"key": "size", "value": "4 mm"}]`. The classification compares `size`, `severity`, `morphology`, `count`, `distribution`, and `density`. |

A synthetic example record:

```csv
finding_id,patient_id,exam_order,report_order,finding_name,code,presence,site_key,site_kind,laterality,state,state_basis,sentence_state,temporal_field,sentence,attributes_json
p001-ct2-f04,p001,2,4,Right upper lobe nodule,pulmonary_nodule,present,RID1303,resolved,right,unchanged,,unchanged,,Unchanged 4 mm solid nodule in the right upper lobe.,"[{""key"": ""size"", ""value"": ""4 mm""}, {""key"": ""morphology"", ""value"": ""solid""}]"
```

## Running

Python 3.8 or later, standard library only.

```
python3 classify_findings.py findings.csv --out results/
```

## Output

`results/classified_findings.csv` has one row per finding statement:

| Field | Content |
|---|---|
| `tracked_finding_id` | The finding this statement belongs to, tracked across the patient's CTs. |
| `tracked_finding_code` | The code that names the tracked finding. |
| `classification` | `first_ct`, `first_reported`, `redocumented_no_change`, `redocumented_with_change`, or `could_not_be_matched`. |
| `reason` | The rule that set the classification. |
| `direction` | What the comparison wording says: `stated_new`, `stated_no_change`, `stated_change`, or `none`. |
| `matched` | 1 when the statement matched a finding documented on an earlier CT. |
| `definite` | 1 when the statement is stated without hedging. |
| `counted` | 1 on one statement per finding per CT. A report that describes one finding in several statements, such as coronary calcification vessel by vessel, counts once. |
| `group_definite` | 1 when every statement of that finding on that CT is stated without hedging. |
| `permanent` | 1 when the code is labeled permanent. |

`results/tracked_findings.csv` has one row per tracked finding, with its code, site, laterality, first and last CT, its classification at each CT, and its statements.

`results/folded_findings.csv` lists statements counted with another statement of the same sentence: the atelectasis half of "atelectasis/scarring", and a diagnosis stated beside the observation it interprets ("consolidation, possibly pneumonia").

The script prints the number of findings on follow-up CTs that an earlier report documented, and the primary outcome: among re-documented findings stated without hedging, the share re-documented with no change. Both count rows with `counted` = 1 on CTs after the first.
