# -*- coding: utf-8 -*-
"""集計：条件×モデル×回ごとの到達面数・操作数・壁への衝突。--by-question で面ごとの通過回数。--csv で保存"""
import argparse, csv, json, os
from collections import defaultdict
import common as cm

LOG = os.path.join(cm.HERE, "log.jsonl")
STEPS = os.path.join(cm.HERE, "steps.jsonl")


def load(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-question", action="store_true")
    ap.add_argument("--csv")
    a = ap.parse_args()
    recs = [r for r in load(LOG) if r.get("status") == "ok"]
    errs = [r for r in load(LOG) if r.get("status") == "error"]
    print(f"実行 {len(recs)} 件、エラー記録 {len(errs)} 件")
    rows = []
    print("\n条件 / モデル / 回 : 到達面数 / 操作数 / 壁 / 壊れた出力 / 円")
    for r in sorted(recs, key=lambda r: (r["cond"], r["provider"], r["trial"])):
        print(f"  {r['cond']} {cm.COND_NAMES[r['cond']]:16s} {r['provider']:10s} 回{r['trial']}: "
              f"{r['levels_done']:2d}面 / {r['actions']:3d}手 / 壁{r['wall_bumps']:3d} / 壊{r['bad_outputs']:2d} / {r['yen']:.0f}円"
              f"  （応答: {r.get('model_served')}）")
        rows.append({"cond": r["cond"], "provider": r["provider"], "model": r["model"], "model_served": r.get("model_served"),
                     "trial": r["trial"], "levels_done": r["levels_done"], "actions": r["actions"],
                     "wall_bumps": r["wall_bumps"], "bad_outputs": r["bad_outputs"], "yen": r["yen"]})
    print("\n条件×モデルの平均到達面数（10面中）")
    agg = defaultdict(list)
    for r in recs:
        agg[(r["cond"], r["provider"])].append(r["levels_done"])
    for cond in cm.CONDITIONS:
        line = f"  {cond} {cm.COND_NAMES[cond]:16s}"
        for p in cm.PROVIDERS:
            v = agg.get((cond, p), [])
            line += f"  {p}: {sum(v)/len(v):.1f} ({','.join(map(str, v))})" if v else f"  {p}: -"
        print(line)
    if a.by_question:
        print("\n面ごとの通過回数（条件×モデル。分母はその組の実行数）")
        steps = load(STEPS)
        passed = defaultdict(set)
        for s in steps:
            if s["result"] == "goal":
                passed[(s["cond"], s["provider"], s["level"])].add(s["job"])
        n = defaultdict(int)
        for r in recs:
            n[(r["cond"], r["provider"])] += 1
        for cond in cm.CONDITIONS:
            for p in cm.PROVIDERS:
                if n[(cond, p)]:
                    print(f"  {cond} {p:10s}: " + " ".join(f"面{l}:{len(passed[(cond, p, l)])}/{n[(cond, p)]}" for l in range(1, 11)))
        bump = defaultdict(int); tot = defaultdict(int)
        for s in steps:
            tot[(s["cond"], s["provider"])] += 1
            if s["result"] == "blocked":
                bump[(s["cond"], s["provider"])] += 1
        print("\n壁に向かって押した割合（全操作のうち）")
        for k in sorted(tot):
            print(f"  {k[0]} {k[1]:10s}: {bump[k]}/{tot[k]} = {100*bump[k]/tot[k]:.0f}%")
    total_yen = sum(r["yen"] for r in recs)
    print(f"\n費用の合計（定価の目安）約{total_yen:.0f}円")
    if a.csv:
        with open(os.path.join(cm.HERE, a.csv), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["cond"])
            w.writeheader(); w.writerows(rows)
        print(f"保存: {a.csv}")


if __name__ == "__main__":
    main()
