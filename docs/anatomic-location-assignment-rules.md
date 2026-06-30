# Anatomic Location Assignment Rules

How an anatomic location (`anatomicLocation` = `{locationId, locationDisplay}`, an
[`anatomic-locations`](https://pypi.org/project/anatomic-locations/) RID) is assigned to each EFL
finding/observation. These rules were agreed for the `sample_data/example2` correction pass and are the
intended spec for tuning the automated location-coding step later.

## Precedence ladder (apply per observation, in order)

1. **Explicit anatomy in the report text / section context wins.** Use the most specific structure
   stated, sided only if a side is stated. Section headers count as context — e.g. under a
   `Chest Wall:` heading, "No soft tissue mass" → *chest wall*; as a bare `Soft Tissues:` paragraph it
   stays the coarse region (see step 3).
2. **Else, if the finding has a definable target organ/structure**, use that organ at the finding's own
   anatomic-noun granularity (never finer), applying the laterality rules below.
3. **Else (no anatomic noun at all — e.g. "soft tissue mass", "generalized osteoporosis")**, fall back
   to the **exam-scoped coarse region** (thorax, abdomen, head, …), sided only if the exam is sided.

**Organ always wins over exam-region** when the finding has a real target organ — *especially*
edge-of-exam cases. "No consolidation" / "lung bases clear" on an abdominal CT → **lung**, never
"abdomen".

## Laterality

Source priority: **explicit text side > sided-exam side > generic (unsided)**.
- A **non-sided exam never introduces a side.** CT Abdomen "adrenal glands unremarkable" → *adrenal
  gland* (generic), not "left adrenal gland". "No hydronephrosis" (no side) → *kidney* (generic).
- A **sided exam** sides the finding: "XR Shoulder - left" + "humerus fracture" → *left humerus*.
- **Resolve laterality against the full report section, not the finding's isolated quote.** A finding's
  `reportText` is one verbatim snippet, and the side is often stated only in the section header or an
  earlier sentence of the same section, not in that snippet. When the section establishes a side, it
  applies to every finding in the section unless a later sentence contradicts it. This is "text/section
  context wins" (precedence rule 1) applied to laterality.
  - **Worked example (a real miss, now fixed):** a CT Chest `Shoulders:` section reads *"The **left**
    glenohumeral joint demonstrates a moderate joint effusion. The humeral head is in a high-riding
    position… Calcifications are noted in the region of the rotator cuff insertion…"* The high-riding-head
    and calcific-tendinopathy findings carry snippets with no side, but the section establishes **left**,
    so they are `left glenohumeral joint` / `left supraspinatus tendon` — not the generic structures.
  - **Pitfall:** reviewing or coding from the isolated `reportText` silently drops section laterality and
    under-calls findings to the generic structure. Always read the snippet against its section.
  - **Still do not infer a side across exams or from clinical priors.** If *this* report's section gives
    no side, stay generic even when another exam localized the same problem (e.g. a US "parapelvic cysts"
    snippet with no side stays *kidney* even though a prior CT said "left kidney").

## Bilateral findings

- **Positive bilateral, separable** (discrete independent lesions/structures per side) → **split into
  two findings**, one `…_left` + one `…_right`, each duplicating the original attributes and report
  text. Example: bilateral maxillary mucosal thickening → left + right maxillary sinus. (Note: bilateral
  renal calculi were already separate observations in the source data; they are *not* re-split.)
- **Positive bilateral, inseparable process** (a single diffuse entity named as one — "-osis",
  "disease", confluent process) → **generic, unsided** structure. Example: bilateral cerebral
  small-vessel disease → *cerebral hemisphere* (generic), not split.
- **Spatially contiguous** finding crossing midline → **single finding, unsided** structure.
- **Generic absent** ("No adrenal nodule", paired organ, no side) → **generic organ**, never a side.

Operational test for separable vs inseparable: *if you could meaningfully say "the left one is
larger/newer", it's separable; if it's a named diffuse entity, it's inseparable.*

## Specificity

The target's granularity **matches the finding's anatomic noun, capped by the report — never finer**.
- "humerus fracture" (cleared bones statement) → *humerus*, not "head of humerus".
- "upper extremity fracture" → *upper extremity* (a real body-part structure), sided by exam — not blank.
- Region-named findings ("upper extremity", "skull", "spine") resolve to their body-part structure; they
  are step-2 targets, **not** the exam-region fallback.

## Exam-scoped region fallback

Only for findings with **no anatomic noun** ("soft tissue mass", "generalized osteoporosis").
- Grain = the **coarse region**, not a soft-tissue substructure ("No soft tissue mass" on chest CT →
  *thorax*, not "chest wall"/"musculature of thorax") — unless report section context names the
  substructure (then step 1 applies).
- Exam → region map (RIDs): CT Abdomen[/Pelvis] → *abdomen* `RID56`; Chest CT/XR → *thorax* `RID1243`;
  MR Brain → *head* `RID9080`; Shoulder → *shoulder* `RID39518`; etc. Combined Abdomen+Pelvis defaults
  to *abdomen* unless text points pelvic.
- **Diffuse findings with a textual predominance keep the text location** (step 1): "osteopenia,
  especially in the thoracic spine" → *thoracic vertebral column*; bare "Diffuse osteopenia" → exam
  region.

## Resolution & validation

- For a **named target organ**, resolve by direct lookup (`AnatomicLocationIndex.get`/exact match),
  **not** flaky semantic search — this avoids retrieval misses (e.g. "prostate" returning salivary
  glands). Derive sided RIDs from the generic via the entry's `left_id`/`right_id`.
- Every assigned `locationId` must exist in the ontology. Structures absent from the ontology (e.g.
  *basal cistern*, *dural venous sinus*) are left unassigned rather than forced to a wrong code.

## Known limitation (follow-on)

Parent/child or generic-vs-specific pairs for the *same finding code across exams* (e.g. "lung" vs
"lower lobe of right lung"; "kidney" vs "left kidney") still produce separate IPL groups. Deciding
whether such observations are the same problem or distinct is the **anatomic-compatibility
reconciliation** step (see `docs/plans/anatomic-location-efl-ipl.md`, Step 3b).
