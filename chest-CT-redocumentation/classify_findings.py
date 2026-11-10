#!/usr/bin/env python3
"""Match findings across each patient's serial chest CTs and classify every
finding on a follow-up CT.

Input is one CSV of extracted findings with taxonomy codes and anatomic sites
already assigned (see README.md). The script writes two CSV files and prints
the primary outcome:

    python3 classify_findings.py findings.csv --out results/

Each follow-up finding receives one classification:

    redocumented_no_change    an earlier report documented it, and its state is unchanged
    redocumented_with_change  an earlier report documented it, and its state changed
    first_reported            no earlier report documented it, or the radiologist called it new
    could_not_be_matched      it matched several earlier findings and no wording said which
    first_ct                  the finding is on the patient's first CT, which is not classified
"""
import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")

FIRST_CT = "first_ct"
NO_CHANGE = "redocumented_no_change"
WITH_CHANGE = "redocumented_with_change"
FIRST_REPORTED = "first_reported"
NOT_MATCHED = "could_not_be_matched"
REDOCUMENTED = (NO_CHANGE, WITH_CHANGE)

PRESENT_OR_HEDGED = {"present", "possible", "indeterminate"}
STATED_WITHOUT_HEDGING = "present"

# Attributes compared between reports. The first five are descriptors, size is a
# measurement.
DESCRIPTOR_ATTRIBUTES = ("morphology", "severity", "count", "distribution", "density")
COMPARED_ATTRIBUTES = DESCRIPTOR_ATTRIBUTES + ("size",)

# Reports give sizes to the nearest millimeter, so sizes this close do not differ.
SIZE_TOLERANCE_MM = 1.0


# --- rule tables: terms declared to name one finding ---------------------------

# Codes that name one finding. Each member code is replaced by the first code.
SAME_FINDING_CODES = [
    ("arterial_calcification", {
        "arterial_calcification", "calcified_arterial_plaque",
        "arterial_atherosclerosis", "aortic_atherosclerosis"}),
    ("vertebral_compression_fracture", {
        "compression_fracture", "vertebral_compression_fracture",
        "physiologic_wedging_of_lower_thoracic_vertebrae"}),
    ("aortic_valve_calcification", {
        "aortic_valve_calcification", "aortic_annular_calcification",
        "aortic_valve_stenosis", "left_ventricular_outflow_tract_calcification",
        "aortic_valve_leaflet_thickening"}),
    ("mitral_valve_calcification", {
        "mitral_valve_calcification", "mitral_annular_calcification"}),
    ("pulmonary_hypertension", {
        "pulmonary_hypertension", "pulmonary_arterial_hypertension"}),
    ("left_atrial_appendage_occlusion_device", {
        "left_atrial_appendage_occlusion_device", "left_atrial_appendage_closure_device"}),
    ("traction_bronchiectasis", {"traction_bronchiectasis", "traction_bronchiolectasis"}),
    ("pleural_plaque", {"pleural_plaque", "pleural_calcification"}),
    ("diaphragmatic_eventration", {"diaphragmatic_eventration", "diaphragmatic_elevation"}),
    ("spinal_degeneration", {"spinal_degeneration", "vertebral_endplate_degeneration"}),
]

# A finding name that mentions the coronary arteries takes the coronary code
# whenever its code is a member of one of the classes above.
CORONARY_WORD = re.compile(r"\bcoronar", re.I)
CORONARY_CODE = "coronary_artery_calcification"

# Organ-specific postsurgical change codes. The organ is a location, so each is
# replaced by the general code and the site distinguishes the organs.
ORGAN_POSTSURGICAL_CODES = {
    "breast_postsurgical_change", "cardiac_postsurgical_change",
    "esophageal_postsurgical_change", "lung_postsurgical_change",
    "osseous_postsurgical_change", "pleural_postsurgical_change",
    "soft_tissue_postsurgical_change", "thyroid_postsurgical_change",
}
POSTSURGICAL_CODE = "postsurgical_change"

# Terms that name one finding at increasing severity, least severe first. They
# match each other, a step between them is a change, and the tracked finding
# keeps the most severe term used.
SEVERITY_STEPS = [
    ["aortic_ectasia", "aortic_dilation", "aortic_aneurysm"],
    ["pulmonary_scarring", "pulmonary_fibrosis"],
    ["soft_tissue_mass", "soft_tissue_neoplasm"],
    ["pulmonary_mass", "pulmonary_metastasis"],
    ["lymph_node_enlargement", "nodal_metastasis"],
    ["mediastinal_lesion", "mediastinal_invasion"],
]

# "Atelectasis/scarring" (either order, joined by a slash, "or", "versus") names
# one finding, recorded as scarring.
_EITHER_OR_JOIN = r"\s*(?:/|\bor\b|\band/or\b|\bvs\.?\b|\bversus\b)\s*"
_ATELECTASIS = r"\w*atelecta\w*"
_SCARRING = r"\w*scar\w*"
ATELECTASIS_OR_SCARRING = re.compile(
    rf"(?:{_ATELECTASIS}){_EITHER_OR_JOIN}(?:{_SCARRING})|"
    rf"(?:{_SCARRING}){_EITHER_OR_JOIN}(?:{_ATELECTASIS})", re.I)
ATELECTASIS_OR_SCARRING_CODES = {
    "atelectasis", "linear_atelectasis", "subsegmental_atelectasis",
    "compressive_atelectasis", "pulmonary_scarring"}
ATELECTASIS_OR_SCARRING_RECORDED_AS = "pulmonary_scarring"

# A diagnosis and the observation it interprets, stated in one sentence, are one
# finding. The observation is the finding, and the diagnosis is kept with it.
DIAGNOSIS_TO_OBSERVATIONS = {
    "pneumonia": {"consolidation", "ground_glass_opacity"},
    "interstitial_lung_disease": {"reticular_opacity"},
    "interstitial_lung_abnormality": {"reticular_opacity"},
    "radiation_fibrosis": {"reticular_opacity"},
    "pulmonary_fibrosis": {"airspace_opacity", "pulmonary_scarring"},
    "pulmonary_embolism": {"arterial_intraluminal_filling_defect"},
    "calcified_granuloma": {"pulmonary_nodule"},
    "pulmonary_granuloma": {"broncholith"},
    "pulmonary_hypertension": {"pulmonary_artery_dilation"},
}

# Findings a patient has at most one of on each side.
ONE_PER_SIDE = {"pleural_effusion"}
SIDES = {"right", "left"}

# Descriptors that cannot describe one finding at once. Two descriptions differ
# only when each names exactly one member of a set and the members differ.
CONFLICTING_DESCRIPTORS = [
    ("nodule composition", {
        "solid": r"(?<![-\w])solid\b",
        "part-solid": r"\bpart[- ]?solid\b|\bsemi[- ]?solid\b",
        "ground-glass": r"\bground[- ]?glass\b|\bnon[- ]?solid\b"}),
    ("shape", {"round or oval": r"\bround\b|\boval\b", "irregular": r"\birregular\b"}),
    ("margin", {
        "smooth": r"\bsmooth\b|\bwell[- ]circumscribed\b",
        "lobulated": r"\blobulated\b",
        "irregular or spiculated": r"\birregular\b|\bspiculated\b"}),
    ("calcification", {
        "calcified": r"(?<![-\w])calcified\b", "noncalcified": r"\bnon[- ]?calcified\b"}),
    ("age of an injury", {
        "acute": r"\bacute\b", "healed": r"\b(?:healed|old|remote|chronic)\b"}),
    ("occlusion", {
        "occlusive": r"(?<![-\w])occlu(?:sive|ding)\b",
        "nonocclusive": r"\bnon[- ]?occlusive\b"}),
    ("zone", {
        "upper": r"\bupper(?: lobe| lung| zone)?[- ]predominan",
        "lower": r"\b(?:lower(?: lobe| lung| zone)?|basilar|basal)[- ]predominan"}),
    ("number", {
        "one": r"\b(?:single|solitary)\b",
        "several": r"\b(?:multiple|several|numerous|innumerable)\b"}),
]

# Severity words on an ordinal scale, 1 (least) to 4 (most).
SEVERITY_WORDS = [
    (1, r"trace|minimal|tiny|very mild|small(?! to)(?! bowel)|scant"),
    (2, r"mild|slight|borderline"),
    (3, r"moderate"),
    (4, r"severe|marked|extensive|advanced|large|heavy|dense|significant|"
        r"complete|prominent|exuberant|florid"),
]

# Anatomic containment the Anatomic Locations index does not state, as
# (location, the location that contains it).
ADDED_CONTAINMENT = [
    ("thoracic vertebral column", "spine"),
    ("vertebra", "spine"),
    ("thoracic aorta", "aorta"),
    ("aortic arch", "thoracic aorta"),
    ("ascending aorta", "thoracic aorta"),
    ("descending thoracic aorta", "thoracic aorta"),
    ("lingula", "upper lobe of left lung"),
    ("trachea", "tracheobronchial tree"),
    ("main bronchus", "tracheobronchial tree"),
    ("interlobar bronchus", "tracheobronchial tree"),
    ("carina", "tracheobronchial tree"),
]

# --- wording patterns ---------------------------------------------------------

STATED_NEW = re.compile(
    r"(?<!no )(?<!not )(?<!without )"
    r"\b(new\b|newly\b|interval (?:development|placement|appearance)|"
    r"develop(?:ed|ment|ing)\b|"
    r"not (?:seen|evident|visualized|present|definitively noted) on (?:the )?prior)", re.I)

OLD_FINDING_WORD = re.compile(
    r"\b(chronic|old|healed|longstanding|remote|post[- ]?(?:operative|surgical)|"
    r"sequela\w*|residual|scar\w*)\b", re.I)

SEVERAL_INSTANCES = re.compile(
    r"\b(multiple|several|scattered|numerous|innumerable|many|few\b|"
    r"diffuse|widespread|extensive|clustered|grouped|nodularity|"
    r"micronodul\w+|tree-in-bud)\b", re.I)

EXAMPLE_OPENING = re.compile(
    r"^\W*(?:(?:for example|for instance|such as|including)\b|e\.?g\.?(?=\W|$))", re.I)

MEASUREMENT = re.compile(r"((?:\d+(?:\.\d+)?\s*[x×]\s*)*\d+(?:\.\d+)?)\s*(mm|cm)\b", re.I)


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def collapse_spaces(text):
    return re.sub(r"\s+", " ", text or "").strip()


# --- the taxonomy and the Anatomic Locations index ----------------------------

class Taxonomy:
    """The study taxonomy: a hierarchy of chest findings from general to specific."""

    def __init__(self, rules_dir=RULES_DIR):
        rows = (read_csv(os.path.join(rules_dir, "taxonomy.csv"))
                + read_csv(os.path.join(rules_dir, "study_added_codes.csv")))
        self.by_id = {r["id"]: r for r in rows}
        self.by_name = {r["name"]: r for r in rows}
        self.airway_codes = {r["name"] for r in rows if r["category"] == "airway"}

    def path_to_root(self, code_id):
        """The code and every more general code above it."""
        out, seen = [], set()
        while code_id and code_id in self.by_id and code_id not in seen:
            seen.add(code_id)
            out.append(code_id)
            code_id = self.by_id[code_id]["parent_id"]
        return out

    def depth(self, code_name):
        r = self.by_name.get(code_name)
        return len(self.path_to_root(r["id"])) if r else 0

    def on_one_branch(self, a, b):
        """True when one code is the other or a more specific form of it."""
        ra, rb = self.by_name.get(a), self.by_name.get(b)
        if not ra or not rb:
            return False
        return (ra["id"] == rb["id"] or ra["id"] in self.path_to_root(rb["id"])
                or rb["id"] in self.path_to_root(ra["id"]))

    def most_specific(self, codes):
        """The code that is a more specific form of every other code, if one
        exists. Codes on sibling branches have none."""
        ids = [self.by_name[c]["id"] for c in codes if c in self.by_name]
        for i in ids:
            branch = self.path_to_root(i)
            if all(j in branch for j in ids):
                return self.by_id[i]["name"]
        return None


class AnatomicIndex:
    """Anatomic locations and which locations contain which."""

    def __init__(self, rules_dir=RULES_DIR):
        rows = read_csv(os.path.join(rules_dir, "anatomic_locations.csv"))
        id_of = {r["name"]: r["id"] for r in rows}
        self.parents = defaultdict(list)
        for r in rows:
            for parent in (r["contained_by_id"], r["unsided_id"]):
                if parent:
                    self.parents[r["id"]].append(parent)
            if r["name"].endswith(" thoracic vertebra"):
                self.parents[r["id"]].append(id_of["thoracic vertebral column"])
        for inner, outer in ADDED_CONTAINMENT:
            self.parents[id_of[inner]].append(id_of[outer])
        self.lung = id_of["lung"]
        self.airways = id_of["tracheobronchial tree"]

    def contains(self, outer, inner):
        """True when `inner` is `outer` or lies within it. A location without a
        side ("lung") contains both of its sided forms."""
        if not outer or not inner:
            return False
        seen, frontier = set(), [inner]
        while frontier:
            cur = frontier.pop()
            if cur == outer:
                return True
            if cur not in seen:
                seen.add(cur)
                frontier.extend(self.parents.get(cur, ()))
        return False

    def contains_airway_site(self, outer, inner):
        """`contains` for a finding of the airways: a finding of the airways
        placed in a lung location lies in the tracheobronchial tree."""
        if self.contains(outer, inner):
            return True
        return outer == self.airways and self.contains(self.lung, inner)


class Rules:
    """Every rule file the classification reads."""

    def __init__(self, rules_dir=RULES_DIR):
        self.taxonomy = Taxonomy(rules_dir)
        self.anatomy = AnatomicIndex(rules_dir)
        self.identity_key = {r["code_name"]: r["identity_key"]
                             for r in read_csv(os.path.join(rules_dir, "identity_keys.csv"))}
        self.permanent = {r["code_name"]
                          for r in read_csv(os.path.join(rules_dir, "permanent_findings.csv"))}

    def distinguishing_attributes(self, code):
        """Which of site and laterality distinguish two separate findings of this
        type. A type without a declared key is distinguished by both."""
        return self.identity_key.get(code, "site+laterality")


# --- code rules -----------------------------------------------------------------

def atelectasis_or_scarring_stated(text):
    return bool(ATELECTASIS_OR_SCARRING.search(text or ""))


def canonical_code(code, finding_name):
    """Replace a code by the code declared to name the same finding."""
    if (atelectasis_or_scarring_stated(finding_name)
            and code in ATELECTASIS_OR_SCARRING_CODES
            and code != ATELECTASIS_OR_SCARRING_RECORDED_AS):
        return ATELECTASIS_OR_SCARRING_RECORDED_AS
    in_a_class = any(code in members for _, members in SAME_FINDING_CODES)
    if CORONARY_WORD.search(finding_name or ""):
        return CORONARY_CODE if in_a_class else code
    for canonical, members in SAME_FINDING_CODES:
        if code in members:
            return canonical
    return code


def severity_step(code):
    """-> (scale number, step) when the code is a step on a severity scale."""
    for n, steps in enumerate(SEVERITY_STEPS):
        if code in steps:
            return n, steps.index(code)
    return None, None


def same_severity_scale(a, b):
    sa, _ = severity_step(a)
    sb, _ = severity_step(b)
    return sa is not None and sa == sb


def most_severe(codes):
    steps = [(severity_step(c)[1], c) for c in codes if severity_step(c)[0] is not None]
    return max(steps)[1] if steps else None


def fold_atelectasis_or_scarring(coded, sentence):
    """Where one "atelectasis/scarring" sentence yielded a scarring finding and
    an atelectasis finding, keep only the scarring finding.
    `coded` is [(finding_id, code)] from one sentence, in report order."""
    if not atelectasis_or_scarring_stated(sentence):
        return list(coded)
    codes = {c for _, c in coded}
    if (ATELECTASIS_OR_SCARRING_RECORDED_AS not in codes
            or len(codes & ATELECTASIS_OR_SCARRING_CODES) < 2):
        return list(coded)
    keep, kept_scarring = [], False
    for fid, c in coded:
        if c == ATELECTASIS_OR_SCARRING_RECORDED_AS and not kept_scarring:
            keep.append((fid, c))
            kept_scarring = True
        elif c not in ATELECTASIS_OR_SCARRING_CODES:
            keep.append((fid, c))
    return keep


def fold_diagnoses(coded):
    """-> {diagnosis finding_id: observation finding_id} for each diagnosis
    stated beside an observation it interprets, in one sentence. A diagnosis
    goes with the first such observation in the sentence."""
    folds = {}
    for fid, c in coded:
        observations = DIAGNOSIS_TO_OBSERVATIONS.get(c)
        if observations:
            target = next((ofid for ofid, oc in coded if oc in observations), None)
            if target is not None:
                folds[fid] = target
    return folds


# --- wording rules --------------------------------------------------------------

def stated_direction(sentence, state, finding_name, temporal_field, shares_sentence):
    """What the radiologist's comparison wording says about the finding:
    stated_new, stated_no_change, stated_change, or none.

    "New" outranks any other comparison word in the sentence. Where several
    findings share the sentence, a finding whose own name calls it old (chronic,
    healed, scar) is not the new one."""
    said_new = STATED_NEW.search(sentence or "") or STATED_NEW.search(temporal_field or "")
    if said_new and not (shares_sentence and OLD_FINDING_WORD.search(finding_name or "")):
        return "stated_new"
    if state == "unchanged":
        return "stated_no_change"
    if state in ("changed", "mixed"):
        return "stated_change"
    return "none"


def comparison_word_owner(f, siblings, direction):
    """Where several findings share a sentence, a word of change ("new",
    "increased", "interval placement") belongs to the finding it is written
    with, not to every finding in the sentence.

    The extraction records, for each finding, the comparison words written with
    it. On a follow-up CT, when another finding in the sentence has words of
    change of its own:
      - for a finding counted once per side, when the change is written for the
        other side ("bilateral pleural effusions, increased
        on the right", "effusions have increased, now large right and small left"), this side was compared and not called
        changed, so it is re-documented with no change;
      - a finding with no comparison words of its own is restated, and the other
        finding's word of change does not apply to it ("bronchiectasis with a new
        nodule", "sternotomy wires with interval placement of a pacemaker");
      - a finding whose own words are a change other than "new" is a stated
        change, even where "new" describes another finding in the sentence
        ("fluctuating nodularity and a new left lower lobe opacity").
    The rule does not apply when the word of change opens the sentence, since it
    then describes the whole list ("new atelectasis, nodules, and
    consolidation"), when the two statements describe the
    same kind of finding, or to wording of no change, which radiologists
    commonly write once for a group of findings ("both unchanged").
    -> the direction, corrected where the sentence's wording is another finding's."""
    if f["exam_order"] == 1 or direction not in ("stated_new", "stated_change"):
        return direction
    sentence = f["sentence"].lower()
    own = f["own_comparison"]
    others = [s for s in siblings if s is not f and s["own_comparison"]
              and s["own_comparison"] in sentence]
    if not others:
        return direction
    if f["code"] in ONE_PER_SIDE and f["laterality"] in SIDES:
        other_side = [s for s in others if s["code"] == f["code"]
                      and s["laterality"] in SIDES and s["laterality"] != f["laterality"]]
        if other_side and not own:
            return "stated_no_change"
        side = own and re.search(re.escape(own) + r",?\s+now\s+(?:\w+\s+){0,2}?(right|left)\b",
                                 sentence)
        if side and side.group(1) != f["laterality"]:
            return "stated_no_change"
    if direction == "stated_new" and own and not STATED_NEW.search(own):
        return "stated_change"
    owners = [s for s in others
              if not re.match(r"\W*" + re.escape(s["own_comparison"]), sentence)]
    if not own and owners and all(s["code"] != f["code"] for s in owners):
        return "none"
    return direction


def describes_several(finding_name, attributes):
    """True when the radiologist described several instances together
    ("multiple nodules"), read from the count and distribution attributes and
    then from the finding name."""
    for key in ("count", "distribution"):
        value = attributes.get(key, "")
        if value and SEVERAL_INSTANCES.search(value):
            return True
        if key == "count" and re.search(r"\b([2-9]|\d\d+)\b", value or ""):
            return True
    return bool(SEVERAL_INSTANCES.search(finding_name or ""))


def sizes_mm(text):
    """Every measurement in the text in millimeters, sorted."""
    out = []
    for numbers, unit in MEASUREMENT.findall(text or ""):
        scale = 10.0 if unit.lower() == "cm" else 1.0
        for n in re.split(r"\s*[x×]\s*", numbers):
            out.append(round(float(n) * scale, 1))
    return tuple(sorted(out))


def severity_range(text):
    """The severity ranks the text covers. "Mild to moderate" covers 2 and 3,
    and "at least moderate" covers 3 and 4. Empty when it names no severity."""
    t = (text or "").lower()
    ranks = {rank for rank, words in SEVERITY_WORDS if re.search(rf"\b(?:{words})", t)}
    if not ranks:
        return set()
    if re.search(r"\bat least\b|\bor (?:greater|worse|more)\b", t):
        return set(range(min(ranks), 5))
    return set(range(min(ranks), max(ranks) + 1))


def normalized_value(key, value):
    if key == "size":
        return sizes_mm(value)
    return re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower()).strip()


def descriptors_conflict(a, b):
    for _, members in CONFLICTING_DESCRIPTORS:
        in_a = {m for m, pattern in members.items() if re.search(pattern, a or "", re.I)}
        in_b = {m for m, pattern in members.items() if re.search(pattern, b or "", re.I)}
        if len(in_a) == 1 and len(in_b) == 1 and in_a != in_b:
            return True
    return False


def values_differ(key, now, before):
    """Does a stated value differ from an earlier stated value?

    Severity differs only when the two ranges do not overlap. A size differs by
    more than 1 mm in some dimension, or in the largest dimension when the
    number of dimensions changed, and a size word ("small") never differs from a
    measurement. Numeric counts differ when the numbers differ. Other
    descriptors differ only on a declared conflict (solid versus ground-glass)."""
    if key == "severity":
        a, b = severity_range(now), severity_range(before)
        return bool(a and b and not (a & b))
    if key == "size":
        a, b = sizes_mm(now), sizes_mm(before)
        if not (a and b):
            return False
        if len(a) != len(b):
            return round(abs(max(a) - max(b)), 1) > SIZE_TOLERANCE_MM
        return any(round(abs(x - y), 1) > SIZE_TOLERANCE_MM for x, y in zip(a, b))
    if key == "count":
        a, b = set(re.findall(r"\b\d+\b", now)), set(re.findall(r"\b\d+\b", before))
        if a and b:
            return a != b
    return descriptors_conflict(now, before)


def first_differing_attribute(finding, tracked):
    """The first compared attribute stated on both reports whose value differs
    from every value the earlier reports stated, or None."""
    for key in COMPARED_ATTRIBUTES:
        now, before = finding["attributes"].get(key), tracked["attributes"].get(key)
        if not now or not before:
            continue
        earlier = before if isinstance(before, list) else [before]
        if all(values_differ(key, now, b) for b in earlier):
            return key
    return None


# --- reading the input ------------------------------------------------------------

def parse_attributes(text):
    try:
        pairs = json.loads(text or "[]")
    except (ValueError, TypeError):
        return {}
    out = {}
    for pair in pairs:
        key, value = pair.get("key", ""), pair.get("value", "")
        if key and value and key not in out:
            out[key] = value if isinstance(value, str) else str(value)
    return out


def read_findings(path, rules):
    """The findings to classify, in file order, with the declared folds applied.

    Absent findings are dropped. Where one sentence states atelectasis/scarring
    as one finding, or a diagnosis beside the observation it interprets, the
    extra finding is dropped and the diagnosis is kept with its observation.
    -> (findings, {dropped finding_id: reason})."""
    findings = []
    for row in read_csv(path):
        if row["presence"] not in PRESENT_OR_HEDGED:
            continue
        name = collapse_spaces(row["finding_name"]).lower()
        code = row["code"]
        if code:
            code = canonical_code(code, name)
            if code in ORGAN_POSTSURGICAL_CODES:
                code = POSTSURGICAL_CODE
        attributes = parse_attributes(row["attributes_json"])
        findings.append({
            "finding_id": row["finding_id"], "patient_id": row["patient_id"],
            "exam_order": int(row["exam_order"]), "report_order": int(row["report_order"]),
            "finding_name": name, "code": code,
            # An uncoded finding matches only the same name.
            "identity": code or f"text:{name}",
            "coded": bool(code),
            "site_key": row["site_key"], "site_kind": row["site_kind"],
            "laterality": row["laterality"],
            "state": row["state"] or "unstated",
            # "Persistent" states presence only, and the description sets the state.
            "presence_only": row["state_basis"] == "presence",
            "diagnoses": set(),
            # The temporal field counts only where the sentence states no comparison.
            "temporal_field": (row["temporal_field"]
                               if row["sentence_state"] == "unstated" else ""),
            # The comparison words the extraction attached to this finding itself.
            "own_comparison": collapse_spaces(row["temporal_field"]).lower(),
            "sentence": collapse_spaces(row["sentence"]),
            "attributes": attributes,
            "several": describes_several(name, attributes),
            "definite": row["presence"] == STATED_WITHOUT_HEDGING,
            "permanent": code in rules.permanent,
        })

    by_sentence = defaultdict(list)
    for f in findings:
        if f["coded"]:
            by_sentence[(f["patient_id"], f["exam_order"], f["sentence"])].append(f)
    by_id = {f["finding_id"]: f for f in findings}
    dropped = {}
    for (_, _, sentence), group in by_sentence.items():
        kept = fold_atelectasis_or_scarring([(f["finding_id"], f["code"]) for f in group],
                                            sentence)
        kept_ids = {fid for fid, _ in kept}
        for f in group:
            if f["finding_id"] not in kept_ids:
                dropped[f["finding_id"]] = "atelectasis_or_scarring_folded"
        for diagnosis, observation in fold_diagnoses(kept).items():
            dropped[diagnosis] = "diagnosis_folded"
            by_id[observation]["diagnoses"].add(by_id[diagnosis]["code"])
    findings = [f for f in findings if f["finding_id"] not in dropped]

    sentence_of = defaultdict(list)
    for f in findings:
        sentence_of[(f["patient_id"], f["exam_order"], f["sentence"])].append(f)
    for f in findings:
        siblings = sentence_of[(f["patient_id"], f["exam_order"], f["sentence"])]
        f["direction"] = stated_direction(
            f["sentence"], f["state"], f["finding_name"], f["temporal_field"],
            len(siblings) > 1)
        f["direction"] = comparison_word_owner(f, siblings, f["direction"])
        f["depth"] = rules.taxonomy.depth(f["code"]) if f["coded"] else 99
    link_examples(findings)
    return findings, dropped


def link_examples(findings):
    """A statement that opens as an example ("for example in the right upper
    lobe") belongs to the nearest earlier statement of the same code in the
    same report that is not itself an example."""
    by_report = defaultdict(list)
    for f in findings:
        f["example_of"] = ""
        by_report[(f["patient_id"], f["exam_order"])].append(f)
    for rows in by_report.values():
        rows.sort(key=lambda f: f["report_order"])
        for i, f in enumerate(rows):
            if not f["coded"] or not EXAMPLE_OPENING.search(f["sentence"]):
                continue
            lead = next((x for x in reversed(rows[:i]) if x["code"] == f["code"]
                         and not EXAMPLE_OPENING.search(x["sentence"])), None)
            if lead:
                f["example_of"] = lead["finding_id"]


# --- matching rules -------------------------------------------------------------

def distinguishing_axes(rules, *codes):
    """Site and laterality, as declared for every type named. Where site
    distinguishes, laterality does as well."""
    axes = set()
    for code in codes:
        key = rules.distinguishing_attributes(code)
        if key != "none":
            axes |= set(key.split("+"))
    if "site" in axes:
        axes.add("laterality")
    return axes


def code_match(rules, a, b):
    """-> exact, severity_step, more_specific, or None. Codes on sibling
    branches name different findings. An uncoded finding matches only itself."""
    if a == b:
        return "exact"
    if a.startswith("text:") or b.startswith("text:"):
        return None
    if same_severity_scale(a, b):
        return "severity_step"
    if rules.taxonomy.on_one_branch(a, b):
        return "more_specific"
    return None


def both_airway_findings(rules, a, b):
    return (a["identity"] in rules.taxonomy.airway_codes
            and b["identity"] in rules.taxonomy.airway_codes)


def site_match(rules, a, b, airway=False):
    """-> exact, contains, or None. A missing site matches any site. A site
    kept as text matches only the same text."""
    if not a["site_key"] or not b["site_key"]:
        return "exact"
    if a["site_key"] == b["site_key"]:
        return "exact"
    if a["site_kind"] != "resolved" or b["site_kind"] != "resolved":
        return None
    contains = rules.anatomy.contains_airway_site if airway else rules.anatomy.contains
    if contains(a["site_key"], b["site_key"]) or contains(b["site_key"], a["site_key"]):
        return "contains"
    return None


def laterality_match(a, b):
    """Opposite named sides are two findings. Bilateral matches either side."""
    if not a or not b or a == b:
        return True
    return "bilateral" in (a, b)


def diagnosis_match(a, b):
    """True when one names the diagnosis kept with the other's observation."""
    return a["identity"] in b.get("diagnoses", ()) or b["identity"] in a.get("diagnoses", ())


CLOSENESS = {"exact": 0, "severity_step": 1, "more_specific": 2, "diagnosis": 3}


def match(rules, finding, tracked):
    """-> closeness (lower is closer) when the finding can be this tracked
    finding, else None.

    The codes must match. Where site distinguishes the type, a statement of
    several instances never matches a single one, the sites must be the same or
    one must contain the other, and opposite sides never match."""
    kind = code_match(rules, finding["identity"], tracked["identity"])
    if kind is None and diagnosis_match(finding, tracked):
        kind = "diagnosis"
    if kind is None:
        return None
    axes = distinguishing_axes(rules, finding["identity"], tracked["identity"])
    if axes and finding["several"] != tracked["several"]:
        return None
    site = "exact"
    if "site" in axes:
        site = site_match(rules, finding, tracked, both_airway_findings(rules, finding, tracked))
        if site is None:
            return None
    if "laterality" in axes and not laterality_match(finding["laterality"], tracked["laterality"]):
        return None
    return CLOSENESS[kind] * 2 + (0 if site == "exact" else 1)


def choose_among_candidates(rules, group, earlier, hits):
    """A finding that matched several earlier findings is attached to one only
    when the choice cannot matter: every candidate is the same finding type and
    the type is not distinguished by site, or the candidates differ only by
    side and the finding states a side (or the type has one per side).
    Preference: the same side, then the most recently documented, then the
    closest match. -> (closeness, index) or None."""
    candidates = [earlier[i] for _, i in hits]
    codes = {group["identity"]} | {t["identity"] for t in candidates}
    sides = [t["laterality"] for t in candidates]
    differ_only_by_side = (len({t["identity"] for t in candidates}) == 1
                           and len({t["site_key"] for t in candidates}) == 1
                           and len(set(sides)) == len(sides) > 1)
    if differ_only_by_side and not group["laterality"] and not codes <= ONE_PER_SIDE:
        differ_only_by_side = False
    if any("site" in rules.distinguishing_attributes(c) for c in codes) and not differ_only_by_side:
        return None

    def preference(hit):
        closeness, i = hit
        t = earlier[i]
        return (0 if t["laterality"] == group["laterality"] else 1, -t["last_exam"], closeness)

    return min(hits, key=preference)


def one_finding_in_one_report(rules, a, b):
    """Two statements in one report name one finding only when the type is not
    distinguished by site or laterality, or either statement describes several
    instances. Two nodules in one lobe are two findings."""
    return (not distinguishing_axes(rules, a["identity"], b["identity"])
            or a["several"] or b["several"])


def new_tracked(f):
    return {"identity": f["identity"], "site_key": f["site_key"],
            "site_kind": f["site_kind"], "laterality": f["laterality"],
            "several": f["several"], "depth": f["depth"],
            "diagnoses": set(f.get("diagnoses", ()))}


def absorb(rules, tracked, f):
    """Add a statement to a tracked finding. The finding keeps the most severe
    term, then the most specific term, the most specific site, and a stated side."""
    if f["identity"] != tracked["identity"]:
        pair = [f["identity"], tracked["identity"]]
        named = most_severe(pair) or rules.taxonomy.most_specific(pair)
        if named is not None:
            tracked["identity"] = named
        tracked["depth"] = (99 if tracked["identity"].startswith("text:")
                            else rules.taxonomy.depth(tracked["identity"]))
    contains = (rules.anatomy.contains_airway_site if both_airway_findings(rules, tracked, f)
                else rules.anatomy.contains)
    if f["site_key"] and (not tracked["site_key"] or (
            tracked["site_kind"] == "resolved" and f["site_kind"] == "resolved"
            and contains(tracked["site_key"], f["site_key"]))):
        tracked["site_key"], tracked["site_kind"] = f["site_key"], f["site_kind"]
    if f["laterality"] and not tracked["laterality"]:
        tracked["laterality"] = f["laterality"]
    tracked["diagnoses"] = set(tracked.get("diagnoses", ())) | set(f.get("diagnoses", ()))


def group_report(rules, findings):
    """Group one report's statements into findings. The most specific statement
    starts a group. A statement that fits two groups that do not fit each other
    (cardiomegaly beside left and right atrial enlargement) stands alone."""
    groups = []
    for f in sorted(findings, key=lambda x: (-x["depth"], x["finding_id"])):
        fits = [g for g in groups
                if all(match(rules, f, m) is not None for m in g["members"])
                and all(match(rules, m, new_tracked(f)) is not None for m in g["members"])
                and all(one_finding_in_one_report(rules, f, m) for m in g["members"])]
        if len(fits) == 1:
            fits[0]["members"].append(f)
        else:
            groups.append({"members": [f]})
    for g in groups:
        g["members"].sort(key=lambda x: x["finding_id"])
        g.update(new_tracked(g["members"][0]))
        for m in g["members"][1:]:
            absorb(rules, g, m)
    return groups


# --- classification rules ----------------------------------------------------------

def classify_statement(f, tracked):
    """-> (classification, reason) for one statement, given the earlier finding
    it matched (None when it matched none).

    The radiologist's comparison wording decides first: "new" is first reported,
    and "unchanged" or "increased" with no matched earlier finding is still
    re-documented. With a match, "persistent" states presence only. A move
    between hedged and stated without hedging is a change. Otherwise a step
    between severity terms, or a compared attribute that differs, is a change."""
    d = f["direction"]
    if d == "stated_new":
        return FIRST_REPORTED, "radiologist_stated_new"
    if tracked is None:
        if d == "stated_no_change":
            return NO_CHANGE, "stated_no_change_no_match"
        if d == "stated_change":
            return WITH_CHANGE, "stated_change_no_match"
        return FIRST_REPORTED, "no_earlier_documentation"
    if d == "stated_no_change" and f["presence_only"]:
        d = "none"
    if d == "stated_change":
        return WITH_CHANGE, "radiologist_stated_change"
    if tracked["definite"] != f["definite"] and d != "stated_no_change":
        return WITH_CHANGE, "hedging_changed"
    if d == "stated_no_change":
        return NO_CHANGE, "radiologist_stated_no_change"
    last = tracked["last_identity"]
    if f["identity"] != last and same_severity_scale(f["identity"], last):
        return WITH_CHANGE, "severity_step"
    differing = first_differing_attribute(f, tracked)
    if differing:
        return WITH_CHANGE, f"{differing}_differs"
    return NO_CHANGE, "restated_without_difference"


def classify_group(g, tracked, refused, exam_order):
    """-> (classification, reason) for one finding, which may hold several
    statements of one report. A finding that matched several earlier findings,
    or tied with another for one, could not be matched unless the radiologist
    wrote comparison wording."""
    members = g["members"]
    verdicts = [classify_statement(m, tracked) for m in members]
    stated_new = [m for m in members if m["direction"] == "stated_new"]
    worded = any(m["direction"] != "none" for m in members)
    if exam_order == 1:
        return FIRST_CT, "first_ct"
    if refused and not worded:
        return NOT_MATCHED, ("matched_several_earlier_findings" if refused == "several"
                             else "tied_with_another_statement")
    if stated_new and len(stated_new) == len(members):
        return FIRST_REPORTED, "radiologist_stated_new"
    if stated_new:
        return WITH_CHANGE, "partly_stated_new"
    if any(v[0] == WITH_CHANGE for v in verdicts):
        return next(v for v in verdicts if v[0] == WITH_CHANGE)
    if len({v[0] for v in verdicts}) > 1:
        return NOT_MATCHED, "statements_disagree"
    return verdicts[0]


def assign_to_earlier(rules, groups, earlier):
    """Match every finding on this CT against the findings tracked before it.
    -> {group index: (outcome, earlier index)}.

    A finding matching one earlier finding claims it. Where two findings claim
    one earlier finding, the closer takes it and the farther starts its own
    tracked finding. Equally close claimants are both refused."""
    outcome = {}
    claims = defaultdict(list)
    for gi, g in enumerate(groups):
        hits = sorted((c, ti) for ti, t in enumerate(earlier)
                      if (c := match(rules, g, t)) is not None)
        if len(hits) > 1:
            pick = choose_among_candidates(rules, g, earlier, hits)
            if pick is None:
                outcome[gi] = ("several", None)
            else:
                claims[pick[1]].append((pick[0], gi))
        elif hits:
            claims[hits[0][1]].append((hits[0][0], gi))
        else:
            outcome[gi] = ("none", None)
    for ti, claimants in sorted(claims.items()):
        best = min(c for c, _ in claimants)
        winners = [gi for c, gi in claimants if c == best]
        if len(winners) > 1:
            for gi in winners:
                outcome[gi] = ("tied", None)
        else:
            outcome[winners[0]] = ("matched", ti)
        for _, gi in claimants:
            outcome.setdefault(gi, ("lost_claim", None))
    return outcome


def classify_patient(rules, patient_id, findings_by_exam):
    """Walk one patient's CTs in order. -> (output rows, tracked findings)."""
    tracked_list, rows = [], []
    for exam in sorted(findings_by_exam):
        earlier = list(tracked_list)
        groups = group_report(rules, findings_by_exam[exam])
        outcome = assign_to_earlier(rules, groups, earlier)
        group_of = {m["finding_id"]: gi for gi, g in enumerate(groups) for m in g["members"]}
        examples, written = [], {}
        for gi, g in enumerate(groups):
            how, ti = outcome[gi]
            tracked = earlier[ti] if how == "matched" else None
            refused = how if how in ("several", "tied") else None
            label, reason = classify_group(g, tracked, refused, exam)
            # The radiologist's "new" also means no earlier finding was matched.
            if how == "matched" and reason == "radiologist_stated_new":
                how, tracked = "stated_new", None
            # An example that matched nothing joins the statement it exemplifies.
            lead = group_of.get(g["members"][0]["example_of"])
            if (len(g["members"]) == 1 and lead is not None and lead != gi
                    and how in ("none", "lost_claim", "stated_new")
                    and label in (FIRST_REPORTED, FIRST_CT)):
                examples.append((gi, lead))
                continue
            if tracked is None:
                tracked = new_tracked(g)
                tracked.update({"attributes": {}, "definite": None,
                                "first_exam": exam, "last_exam": exam,
                                "tracked_finding_id": f"{patient_id}-e{len(tracked_list) + 1:03d}",
                                "finding_ids": [], "classifications": []})
                tracked_list.append(tracked)
            else:
                absorb(rules, tracked, g)
                tracked["last_exam"] = exam
            record_statements(tracked, g)
            group_definite = all(m["definite"] for m in g["members"])
            tracked["definite"] = group_definite
            tracked["last_identity"] = g["identity"]
            out = []
            for m in g["members"]:
                tracked["finding_ids"].append(m["finding_id"])
                out.append(output_row(m, tracked, label, reason, how == "matched",
                                      m is g["members"][0], group_definite))
            rows.extend(out)
            tracked["classifications"].append(label)
            written[gi] = (tracked, out)
        for gi, lead in examples:
            tracked, out = written[lead]
            m = groups[gi]["members"][0]
            row = output_row(m, tracked, out[0]["classification"], out[0]["reason"],
                             out[0]["matched"], False, out[0]["group_definite"])
            rows.append(row)
            tracked["finding_ids"].append(m["finding_id"])
    return rows, tracked_list


def record_statements(tracked, g):
    """Keep every distinct value each compared attribute took in this report."""
    for key in COMPARED_ATTRIBUTES:
        values = []
        for m in g["members"]:
            v = m["attributes"].get(key)
            if v and normalized_value(key, v) not in {normalized_value(key, x) for x in values}:
                values.append(v)
        if values:
            tracked["attributes"][key] = values if len(values) > 1 else values[0]


def output_row(f, tracked, label, reason, matched, counted, group_definite):
    return {
        "finding_id": f["finding_id"], "patient_id": f["patient_id"],
        "exam_order": f["exam_order"], "finding_name": f["finding_name"],
        "code": f["code"] or "",
        "tracked_finding_id": tracked["tracked_finding_id"],
        "tracked_finding_code": tracked["identity"],
        "classification": label, "reason": reason, "direction": f["direction"],
        "matched": int(matched), "definite": int(f["definite"]),
        # One statement per finding per CT is counted; the others are listed.
        "counted": int(counted), "group_definite": int(group_definite),
        "permanent": int(f["permanent"]),
    }


# --- outcomes -----------------------------------------------------------------------

def counted_followup(rows):
    return [r for r in rows if r["exam_order"] > 1 and r["counted"]]


def primary_outcome(rows):
    """Among re-documented findings on follow-up CTs stated without hedging, the
    share re-documented with no change. -> (no change, with change, percent)."""
    rows = [r for r in counted_followup(rows)
            if r["group_definite"] and r["classification"] in REDOCUMENTED]
    same = sum(r["classification"] == NO_CHANGE for r in rows)
    changed = sum(r["classification"] == WITH_CHANGE for r in rows)
    return same, changed, (100 * same / (same + changed) if same + changed else float("nan"))


def redocumentation(rows):
    """-> (re-documented, all findings) on follow-up CTs, hedged included."""
    rows = counted_followup(rows)
    return sum(r["classification"] in REDOCUMENTED for r in rows), len(rows)


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("findings", help="CSV of extracted findings (see README.md)")
    ap.add_argument("--out", default="results", help="folder for the output files")
    args = ap.parse_args()

    rules = Rules()
    findings, dropped = read_findings(args.findings, rules)
    by_patient = defaultdict(lambda: defaultdict(list))
    for f in findings:
        by_patient[f["patient_id"]][f["exam_order"]].append(f)
    rows, tracked = [], []
    for patient_id in sorted(by_patient):
        r, t = classify_patient(rules, patient_id, by_patient[patient_id])
        rows += r
        tracked += t

    os.makedirs(args.out, exist_ok=True)
    write_csv(os.path.join(args.out, "classified_findings.csv"), rows, list(rows[0]))
    write_csv(os.path.join(args.out, "tracked_findings.csv"), [{
        "tracked_finding_id": t["tracked_finding_id"], "code": t["identity"],
        "site_key": t["site_key"], "laterality": t["laterality"],
        "several": int(t["several"]), "first_exam": t["first_exam"],
        "last_exam": t["last_exam"], "n_statements": len(t["finding_ids"]),
        "n_cts": len(t["classifications"]),
        "classifications": "|".join(t["classifications"]),
        "finding_ids": "|".join(t["finding_ids"]),
    } for t in tracked], ["tracked_finding_id", "code", "site_key", "laterality", "several",
                          "first_exam", "last_exam", "n_statements", "n_cts",
                          "classifications", "finding_ids"])
    write_csv(os.path.join(args.out, "folded_findings.csv"),
              [{"finding_id": k, "reason": v} for k, v in dropped.items()],
              ["finding_id", "reason"])

    same, changed, pct = primary_outcome(rows)
    redocumented, followup = redocumentation(rows)
    print(f"statements classified: {len(rows)}  tracked findings: {len(tracked)}")
    print(f"re-documented on follow-up CTs: {redocumented} of {followup}")
    print(f"primary outcome: {same} of {same + changed} re-documented with no change ({pct:.1f}%)")


if __name__ == "__main__":
    main()
