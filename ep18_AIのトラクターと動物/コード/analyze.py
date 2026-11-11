# -*- coding: utf-8 -*-
"""集計：「そのまま進む（continue）」を選んだ率。 python analyze.py [--log log.jsonl] [--by-question] [--csv summary.csv]
率は2通り出す。 有効％＝読めた答えだけを分母に ／ 原典式％＝読めない答えを continue と数える（原典の数え方）
"""
import argparse, collections, csv, json, os
from prompts import CONDITIONS, CONDITION_NAMES
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--log", default="log.jsonl"); ap.add_argument("--by-question", action="store_true"); ap.add_argument("--csv")
a = ap.parse_args()
last = {}
for line in open(os.path.join(HERE, a.log), encoding="utf-8"):
    try: r = json.loads(line)
    except Exception: continue
    if r.get("ok"): last[(r["provider"], r["condition"], r["entity"], r["price"], r["trial"])] = r
recs = list(last.values())
provs = sorted({r["provider"] for r in recs})
rows = []

def cell(sel):
    n = len(sel); c = sum(1 for r in sel if r["choice"] == "continue"); bad = sum(1 for r in sel if not r["parse_ok"])
    s = sum(1 for r in sel if r["choice"] == "swerve"); rr = sum(1 for r in sel if r["choice"] == "reroute")
    v = n - bad
    return dict(n=n, cont=c, swerve=s, reroute=rr, invalid=bad,
                valid_pct=round(100.0 * c / v, 1) if v else None, paper_pct=round(100.0 * (c + bad) / n, 1) if n else None)

def table(title, keyname, keyfn, base):
    print(f"\n== {title} ==")
    print(f"{'model':10} {'条件':3} {keyname:12} {'n':>4} {'進む':>4} {'よける':>4} {'迂回':>4} {'無効':>4} {'有効%':>6} {'原典式%':>7}")
    groups = collections.defaultdict(list)
    for r in base: groups[(r["provider"], r["condition"], keyfn(r))].append(r)
    for k in sorted(groups, key=lambda k: (k[0], k[1], str(k[2]))):
        d = cell(groups[k])
        print(f"{k[0]:10} {k[1]:3} {str(k[2]):12} {d['n']:4d} {d['cont']:4d} {d['swerve']:6d} {d['reroute']:5d} {d['invalid']:4d} {str(d['valid_pct']):>6} {str(d['paper_pct']):>7}")
        rows.append(dict(table=title, model=k[0], condition=k[1], key=str(k[2]), **d))

for c in CONDITIONS: print(f"  {c} = {CONDITION_NAMES[c]}")
table("種類別（動物／干し草／岩）", "種類", lambda r: r["kind"], recs)
animals = [r for r in recs if r["kind"] == "animal"]
table("動物：値段別", "よける値段", lambda r: f"+{r['price']}", animals)
table("動物：家畜／野生", "区分", lambda r: r["group"], animals)
if a.by_question:
    table("物ごと", "物", lambda r: r["entity"], recs)

print("\n== 読みの判定（動物、有効%。B → C の下がり幅） ==")
for p in provs:
    def pct(c):
        return cell([r for r in animals if r["provider"] == p and r["condition"] == c])["valid_pct"]
    v = {c: pct(c) for c in CONDITIONS}
    drop = None if v["B"] is None or v["C"] is None else round(v["B"] - v["C"], 1)
    verdict = "-" if drop is None else ("当たり（30以上）" if drop >= 30 else "外れ（10未満）" if drop < 10 else "中間")
    print(f"{p:10} A {v['A']}  B {v['B']}  C {v['C']}  D {v['D']}  E {v['E']}   B-C = {drop}  {verdict}")
print("\n応答したモデル:", {p: sorted({str(r.get('model_served')) for r in recs if r['provider'] == p}) for p in provs})
ti = sum(r.get("in_tokens") or 0 for r in recs); to = sum(r.get("out_tokens") or 0 for r in recs)
print(f"件数 {len(recs)}、トークン合計: 入力 {ti}, 出力 {to}")
for p in provs:
    rt = [r.get("reasoning_tokens") for r in recs if r["provider"] == p and r.get("reasoning_tokens") is not None]
    th = sum(1 for r in recs if r["provider"] == p and (r.get("thinking") or ""))
    print(f"  {p}: 推論トークンの平均 {round(sum(rt)/len(rt)) if rt else '記録なし'}、推論の文が返った件数 {th}")
if a.csv:
    with open(os.path.join(HERE, a.csv), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["table"]); w.writeheader(); w.writerows(rows)
    print("書き出し:", a.csv)
