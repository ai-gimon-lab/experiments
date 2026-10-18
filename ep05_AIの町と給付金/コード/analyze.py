# -*- coding: utf-8 -*-
"""メモのないおつかい：集計

  python analyze.py                     log.jsonl を集計して表示
  python analyze.py --csv summary.csv   モデル×条件の表をCSVに書く
  python analyze.py --log pilot_log.jsonl
（--by-question は雛形との互換のために受け付けるだけ）
"""
import argparse, csv, json, os
import common as cm


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok":
            rows[(r["provider"], r["job"])] = r     # 同じ回が重なったら後のものを使う
    return list(rows.values())


def stat(rs):
    n = len(rs)
    valid = [r for r in rs if r["result"] in ("bought", "none")]
    v = len(valid)
    def share(f):
        return (sum(1 for r in valid if f(r)) / v) if v else float("nan")
    def mean(k):
        return (sum(r.get(k, 0) for r in valid) / v) if v else float("nan")
    return {"n": n, "valid": v, "unparsed": sum(1 for r in rs if r["result"] == "unparsed"),
            "truncated": sum(1 for r in rs if r["result"] == "truncated"),
            "bought_rate": share(lambda r: r["result"] == "bought"),
            "mean_total": mean("total"), "mean_food": mean("food"), "mean_goods": mean("goods"),
            "mean_lodging": mean("lodging"),
            "nonfood_rate": share(lambda r: r.get("nonfood", 0) > 0),
            "tshirt_rate": share(lambda r: r.get("tshirt")), "room_rate": share(lambda r: r.get("room")),
            "over_budget": sum(1 for r in valid if r.get("over_budget"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="log.jsonl")
    ap.add_argument("--csv")
    ap.add_argument("--by-question", action="store_true")
    a = ap.parse_args()
    path = a.log if os.path.isabs(a.log) else os.path.join(cm.HERE, a.log)
    if not os.path.exists(path):
        print(f"{a.log} がありません。")
        return
    rows = load(path)
    print(f"成功した回：{len(rows)}")
    served = {}
    for r in rows:
        served.setdefault(r["provider"], set()).add(str(r.get("model_served")))
    for p, s in served.items():
        print(f"  {p}: 指定 {cm.MODELS[p]} ／ 応答 {', '.join(sorted(s))}")

    table = []
    groups = [("全モデル", rows)] + [(cm.MODELS[p], [r for r in rows if r["provider"] == p]) for p in cm.PROVIDERS]
    for name, rs in groups:
        if not rs:
            continue
        print(f"\n== {name} ==")
        print("条件      回 有効  買った率  平均額   飲食  日用品    宿  飲食以外率  Tシャツ率  宿率  読めず")
        for c, cn in cm.CONDITIONS:
            s = stat([r for r in rs if r["cond"] == c])
            if not s["n"]:
                continue
            print(f"{c} {s['n']:4d} {s['valid']:4d}  {s['bought_rate']:7.3f} {s['mean_total']:7.1f} {s['mean_food']:6.1f} "
                  f"{s['mean_goods']:6.1f} {s['mean_lodging']:6.1f}  {s['nonfood_rate']:8.3f}  {s['tshirt_rate']:8.3f} "
                  f"{s['room_rate']:5.3f}  {s['unparsed'] + s['truncated']:4d}   {cn}")
            table.append(dict(model=name, cond=c, cond_name=cn, **s))
        # 給付で増えた額÷5,000（論文の「使った割合」と同じ考え方）
        for m, mn in cm.MEMO:
            g0 = stat([r for r in rs if r["cond"] == "G0" + m])
            g1 = stat([r for r in rs if r["cond"] == "G1" + m])
            g2 = stat([r for r in rs if r["cond"] == "G2" + m])
            if g0["valid"] and g1["valid"]:
                d1 = g1["mean_total"] - g0["mean_total"]
                line = f"  {mn}：給付ありは給付なしより {d1:+.1f} NPR（給付額の {d1 / cm.GRANT * 100:+.2f}%）"
                if g2["valid"]:
                    d2 = g2["mean_total"] - g0["mean_total"]
                    line += f"／説明なしで同じ金額だと {d2:+.1f} NPR"
                print(line)

    if a.csv:
        out = a.csv if os.path.isabs(a.csv) else os.path.join(cm.HERE, a.csv)
        cols = ["model", "cond", "cond_name", "n", "valid", "unparsed", "truncated", "bought_rate", "mean_total",
                "mean_food", "mean_goods", "mean_lodging", "nonfood_rate", "tshirt_rate", "room_rate", "over_budget"]
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for t in table:
                w.writerow({k: t[k] for k in cols})
        print(f"\n{a.csv} を書きました。")


if __name__ == "__main__":
    main()
