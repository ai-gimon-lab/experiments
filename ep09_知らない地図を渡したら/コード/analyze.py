# -*- coding: utf-8 -*-
"""集計：場面ごと・メモごと・モデルごとに、選んだ方向の分類を数える。

  python analyze.py                      log.jsonl を集計
  python analyze.py --log pilot_log.jsonl
  python analyze.py --csv summary.csv    表をCSVにも書く
  （--by-question は他の実験と呼び方をそろえるために受け付けるだけ）

割合の分母は、方向が読めた回。読めなかった回・途中で切れた回・要約が無くて作れなかった回は件数を出す。
"""
import argparse, csv, json, os
import common as cm

CATS = {"S1": ["old", "other", "back"], "S2H": ["unexplored", "old_side", "dead"], "S2B": ["unexplored", "old_side", "dead"]}
LABEL = {"old": "メモの方向", "other": "もう一方", "back": "入口へ", "unexplored": "未踏", "old_side": "古い道の側",
         "dead": "行き止まり側"}
BAD = ["invalid", "truncated", "unparsed"]
FOCUS = {"S1": "old", "S2H": "unexplored", "S2B": "unexplored"}


def load(path):
    last = {}
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok":
            last[(r["provider"], r["job"])] = r
    return list(last.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="log.jsonl")
    ap.add_argument("--csv")
    ap.add_argument("--by-question", action="store_true")
    a = ap.parse_args()
    path = os.path.join(cm.HERE, a.log)
    if not os.path.exists(path):
        print(f"{a.log} がない")
        return
    rows = load(path)
    provs = [p for p in cm.PROVIDERS if any(r["provider"] == p for r in rows)]
    print(f"集計：{a.log}  成功 {len(rows)} 件")
    for p in provs:
        served = sorted({str(r.get("model_served")) for r in rows if r["provider"] == p})
        print(f"  {p}: 指定 {cm.MODELS[p]} ／ 応答 {', '.join(served)}")

    out = []
    for sc in ("S1", "S2H", "S2B"):
        cats = CATS[sc]
        print(f"\n■ {sc} {cm.SCENE_NAME[sc]}")
        print("   メモ ／ モデル ／ " + "・".join(LABEL[c] for c in cats) + "・読めない等 ／ 版ごとの内訳 ／ 注目の割合（" + LABEL[FOCUS[sc]] + "）")
        for memo, mname in cm.MEMOS:
            print(f"  [{memo}] {mname}")
            for p in provs + ["3モデル合計"]:
                rs = [r for r in rows if r["scene"] == sc and r["memo"] == memo and (p == "3モデル合計" or r["provider"] == p)]
                c = {k: sum(1 for r in rs if r["result"] == k) for k in cats + BAD}
                bad = sum(c[k] for k in BAD)
                n = sum(c[k] for k in cats)
                f = c[FOCUS[sc]]
                byver = " ".join(f"{v}:{sum(1 for r in rs if r['version'] == v and r['result'] == FOCUS[sc])}/"
                                 f"{sum(1 for r in rs if r['version'] == v and r['result'] in cats)}" for v in cm.VERSIONS[sc])
                rate = "  -  " if not n else f"{100 * f / n:5.1f}%"
                print(f"     {p:<12} " + " ".join(f"{c[k]:>3}" for k in cats) + f" {bad:>3}   {byver}   {rate}（{f}/{n}）")
                out.append([sc, memo, mname, cm.MODELS.get(p, p)] + [c[k] for k in cats] + [bad, n, "" if not n else f"{100 * f / n:.1f}"])

    sm = [r for r in rows if r["scene"] == "S2A"]
    if sm:
        print("\n■ S2A 要約を書かせた回（粗い目印。中身は読んで確かめる）")
        print("   メモ ／ 書けた数 ／ 行き止まりの座標が残っている数 ／ 平均の文字数")
        for memo, mname in cm.MEMOS:
            rs = [r for r in sm if r["memo"] == memo and r["result"] == "summary"]
            keep = 0
            for r in rs:
                x, y = cm.P["expected"]["old_corridor_dead_end"][r["version"]]
                t = cm.normalize(r["response"]).replace(" ", "")
                keep += 1 if f"({x},{y})" in t else 0
            avg = sum(len(r["response"]) for r in rs) / len(rs) if rs else 0
            print(f"  [{memo}] {mname}： {len(rs)} ／ {keep} ／ {avg:.0f}")

    if a.csv:
        with open(os.path.join(cm.HERE, a.csv), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["scene", "memo", "memo_name", "model", "cat1", "cat2", "cat3", "unreadable", "readable", "focus_rate_pct",
                        "（S1: cat1=メモの方向, cat2=もう一方, cat3=入口へ／S2: cat1=未踏, cat2=古い道の側, cat3=行き止まり側）"])
            w.writerows(out)
        print(f"\n{a.csv} に書いた")


if __name__ == "__main__":
    main()
