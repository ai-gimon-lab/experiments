# -*- coding: utf-8 -*-
"""集計

  python analyze.py                        log.jsonl を集計（条件 × 元のラベル × モデル）
  python analyze.py --log pilot_log.jsonl  下見の記録を集計
  python analyze.py --by-question --csv summary.csv   1文ごとの表も出す

数えるもの（書き換え − 元の文）：
  語数／感覚・細部の語／考え・曖昧の語／数字／一人称
  自前の判定器（classifier/weights.json があるとき）：元の文と書き換えの「本当」確率、反転したか
語彩は Claude が決めた短い一覧（LIWC に似せたが LIWC ではない）。結果を見てから語彩は変えない。
"""
import argparse, csv, json, os, re, statistics as st
from collections import defaultdict
import common as cm
import bow

PERCEPT = set("""see saw seen seeing look looked looking watch watched watching hear heard hearing listen listened
sound sounds sounded smell smelled smelt taste tasted touch touched felt feel feeling warm cold hot bright dark loud
quiet soft hard sweet bitter noise noisy color colour red blue green yellow white black""".split())
COGNITION = set("""think thinks thought thinking know knew known knowing believe believed guess guessed maybe perhaps
probably suppose supposed wonder wondered seem seems seemed realize realized realise realised understand understood
sure unsure assume assumed consider considered reason reasons because decide decided somehow sort kind rather
apparently possibly might could would should""".split())
FIRST = set("i me my mine myself".split())
NUMWORD = set("""one two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred
thousand first second third half dozen""".split())
TOK = re.compile(r"[a-z']+|\d+")


def feats(text):
    t = TOK.findall(text.lower())
    n = max(1, len(t))
    return {"words": len(t),
            "percept": sum(1 for w in t if w in PERCEPT),
            "cognition": sum(1 for w in t if w in COGNITION),
            "numbers": sum(1 for w in t if w.isdigit() or w in NUMWORD),
            "first": sum(1 for w in t if w in FIRST)}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 2) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="log.jsonl")
    ap.add_argument("--by-question", action="store_true")
    ap.add_argument("--csv")
    a = ap.parse_args()
    path = os.path.join(cm.HERE, a.log)
    ok = cm.load_ok(path)
    has_clf = bow.available()
    print(f"記録 {len(ok)} 件　判定器 {'あり' if has_clf else 'なし（特徴の増減だけ）'}")
    rows = []
    for (prov, job), r in ok.items():
        s = cm.BY_SID[r["sid"]]
        f0, f1 = feats(s["text"]), feats(r["rewrite"])
        row = {"provider": prov, "model_served": r.get("model_served"), "cond": r["cond"], "sid": r["sid"],
               "orig_label": s["label"], "result": r["result"], "words_orig": f0["words"], "words_new": f1["words"]}
        for k in ("percept", "cognition", "numbers", "first"):
            row[f"d_{k}"] = f1[k] - f0[k]
        if has_clf:
            l0, c0 = bow.classify(s["text"])
            l1, c1 = bow.classify(r["rewrite"])
            p0, p1 = bow.prob_truthful(s["text"]), bow.prob_truthful(r["rewrite"])
            row.update({"clf_orig_label": l0, "clf_new_label": l1,
                        "clf_orig_correct": int(l0 == s["label"]),
                        "d_p_truthful": round(100 * (p1 - p0), 2),
                        "flip_vs_truth": int(l1 != s["label"]),         # 元の正しいラベルから外れたか
                        "flip_vs_clf": int(l1 != l0)})                  # 判定器の元の判定から変わったか
        rows.append(row)
    rows.sort(key=lambda r: (r["provider"], r["cond"], r["orig_label"], r["sid"]))

    groups = defaultdict(list)
    for r in rows:
        groups[(r["provider"], r["cond"], r["orig_label"])].append(r)
    print()
    hdr = "モデル      条件  元のラベル   n  有効   Δ語数  Δ感覚  Δ考え  Δ数字"
    if has_clf:
        hdr += "  判定器が元を正解  反転(対正解)  Δ本当確率"
    print(hdr)
    for (prov, c, lab), g in sorted(groups.items()):
        v = [r for r in g if r["result"] == "valid"]
        line = (f"{prov:10} {c}  {lab:9} {len(g):3} {len(v):4}  "
                f"{mean([r['words_new']-r['words_orig'] for r in v]) if v else '':>6}  "
                f"{mean([r['d_percept'] for r in v]) if v else '':>5}  {mean([r['d_cognition'] for r in v]) if v else '':>5}  "
                f"{mean([r['d_numbers'] for r in v]) if v else '':>5}")
        if has_clf and v:
            corr = [r for r in v if r["clf_orig_correct"]]
            flip = round(100 * sum(r["flip_vs_truth"] for r in corr) / len(corr), 1) if corr else None
            line += f"  {len(corr):>8}/{len(v):<4}  {flip!s:>10}%  {mean([r['d_p_truthful'] for r in corr])!s:>8}"
        print(line)
    print()
    print("Δ本当確率：判定器が「本当」と見る確率の変化（ポイント）。本当→うそ方向では負なら成功の向き、うそ→本当では正なら成功の向き。")
    print("反転(対正解)：判定器が元の文を正しく当てていた文のうち、書き換え後に逆のラベルになった割合。")
    bad = defaultdict(int)
    for r in rows:
        if r["result"] != "valid":
            bad[(r["provider"], r["result"])] += 1
    if bad:
        print("語数などで有効にならなかった分：", dict(bad))
    if a.csv:
        out = os.path.join(cm.HERE, a.csv)
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["provider"])
            w.writeheader()
            w.writerows(rows)
        print(f"{a.csv} に書いた（{len(rows)} 行）")


if __name__ == "__main__":
    main()
