# -*- coding: utf-8 -*-
"""集計：モデル×条件×負け数 ごとの CONCEDE 率。 python analyze.py [--log log.jsonl] [--by-question] [--csv summary.csv]"""
import argparse, collections, csv, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--log", default="log.jsonl"); ap.add_argument("--by-question", action="store_true"); ap.add_argument("--csv")
a = ap.parse_args()
path = os.path.join(HERE, a.log)
last = {}
for line in open(path, encoding="utf-8"):
    try: r = json.loads(line)
    except Exception: continue
    if r.get("ok"): last[(r["provider"], r["condition"], r["losses"], r["trial"])] = r
cells = collections.defaultdict(lambda: collections.Counter())
served = collections.defaultdict(set)
for (p, c, L, t), r in last.items():
    cells[(p, c, L)][r["answer"]] += 1; served[p].add(r.get("model_served"))
rows = []
print(f"{'model':10} {'cond':4} {'loss':4} {'n':>3} {'CONCEDE':>7} {'RESIST':>6} {'UNK':>3} {'concede%':>8}")
for (p, c, L) in sorted(cells):
    n = sum(cells[(p, c, L)].values()); cc = cells[(p, c, L)]["CONCEDE"]; rr = cells[(p, c, L)]["RESIST"]; u = cells[(p, c, L)]["UNKNOWN"]
    pct = 100.0 * cc / n if n else 0
    print(f"{p:10} {c:4} {L:4} {n:3d} {cc:7d} {rr:6d} {u:3d} {pct:8.1f}")
    rows.append(dict(model=p, condition=c, losses=L, n=n, concede=cc, resist=rr, unknown=u, concede_pct=round(pct, 1)))
print("応答したモデル:", {p: sorted(str(x) for x in s) for p, s in served.items()})
tot_in = sum(r.get("in_tokens") or 0 for r in last.values()); tot_out = sum(r.get("out_tokens") or 0 for r in last.values())
print(f"トークン合計: 入力 {tot_in}, 出力 {tot_out}")
if a.csv:
    with open(os.path.join(HERE, a.csv), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["model"]); w.writeheader(); w.writerows(rows)
    print("書き出し:", a.csv)
