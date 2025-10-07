import json
from pathlib import Path
from collections import Counter, defaultdict
from tabulate import tabulate

def load_map(jsonl_path: Path):
    d = {}
    with jsonl_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            d[obj["report_id"]] = {f["name"].lower(): bool(f["present"]) for f in obj["findings"]}
    return d

def precision_recall_f1(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1

def main():
    gold = load_map(Path("data/labels.jsonl"))
    pred = load_map(Path("data/predictions.jsonl"))
    assert gold.keys() == pred.keys(), "Mismatched report ids between gold and predictions."

    tp=fp=fn=tn=0
    per_finding = defaultdict(lambda: Counter(tp=0, fp=0, fn=0, tn=0))

    for rid in gold.keys():
        names = set(gold[rid].keys()) | set(pred[rid].keys())
        for name in names:
            g = gold[rid].get(name, False)
            p = pred[rid].get(name, False)
            if g and p:
                tp += 1; per_finding[name]["tp"] += 1
            elif not g and p:
                fp += 1; per_finding[name]["fp"] += 1
            elif g and not p:
                fn += 1; per_finding[name]["fn"] += 1
            else:
                tn += 1; per_finding[name]["tn"] += 1

    P,R,F1 = precision_recall_f1(tp,fp,fn)
    print("\n== Overall ==")
    print(tabulate([["micro-avg", tp, fp, fn, tn, f"{P:.2f}", f"{R:.2f}", f"{F1:.2f}"]],
                   headers=["scope","TP","FP","FN","TN","Prec","Rec","F1"]))

    rows=[]
    for name, c in sorted(per_finding.items()):
        p,r,f1 = precision_recall_f1(c["tp"], c["fp"], c["fn"])
        rows.append([name, c["tp"], c["fp"], c["fn"], c["tn"], f"{p:.2f}", f"{r:.2f}", f"{f1:.2f}"])
    print("\n== By Finding ==")
    print(tabulate(rows, headers=["finding","TP","FP","FN","TN","Prec","Rec","F1"]))

if __name__ == "__main__":
    main()
