# -*- coding: utf-8 -*-
"""
log.jsonl を集計する。

  python analyze.py                      # 画面に表を出す
  python analyze.py --by-question        # 問題ごとの内訳も出す
  python analyze.py --csv summary.csv    # 集計表をCSVにも書き出す

集計の見方
  今年度 … 今年度ページの値で答えた（正解）
  去年   … 去年ページの値で答えた
  資料にない … 「答え: 資料にない」と答えた
  別の数字 … どちらでもない数字（平日と土日の取り違え、別の施設の値など）
  取り出せず … 追問しても「答え:」の形で答えなかった
"""
import argparse
import csv
import json
import math
from collections import Counter, defaultdict

from run_experiment import CONDITIONS, COND_NAMES, MODELS

RESULTS = ["current", "old", "unsure", "other", "unparsed"]
RESULT_JA = {"current": "今年度", "old": "去年", "unsure": "資料にない", "other": "別の数字", "unparsed": "取り出せず"}
COND_JA = dict(CONDITIONS)
ABNORMAL_STOP = {"max_tokens", "length", "MAX_TOKENS", "SAFETY", "RECITATION", "content_filter"}


def fisher_two_sided(a, b, c, d):
    """2×2表 [[a,b],[c,d]] のフィッシャーの正確検定（両側）"""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2
    lc = lambda x, y: math.lgamma(x + 1) - math.lgamma(y + 1) - math.lgamma(x - y + 1)
    def p(x):
        return math.exp(lc(n1, x) + lc(n2, k - x) - lc(n, k))
    lo, hi = max(0, k - n2), min(k, n1)
    p0 = p(a)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 * (1 + 1e-7)))


def load(path):
    recs, errors = {}, Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") == "ok":
                recs[r["key"]] = r          # 同じキーが二度あれば後のものを使う
            else:
                errors[r["key"].split("|")[0]] += 1
    return list(recs.values()), errors


def pct(x, n):
    return f"{x}/{n}（{100 * x / n:.2f}%）" if n else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="log.jsonl")
    ap.add_argument("--by-question", action="store_true")
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    recs, errors = load(args.log)
    if any(r.get("mock") for r in recs):
        print("※ 模擬モード（--mock）の記録が含まれています。本番の前に log.jsonl を消してください。\n")

    role = {m["name"]: m["role"] for m in MODELS}
    models_present = [m["name"] for m in MODELS if any(r["model"] == m["name"] for r in recs)]
    tab = defaultdict(Counter)            # (model, cond) -> Counter(result)
    for r in recs:
        tab[(r["model"], r["cond"])][r["result"]] += 1

    # ── 1. データの状態 ──
    print("■ データの状態")
    for m in models_present:
        rs = [r for r in recs if r["model"] == m]
        stops = Counter(r["stop_reason"] for r in rs)
        abnormal = sum(v for k, v in stops.items() if k in ABNORMAL_STOP)
        served = Counter(r.get("model_served") for r in rs)
        print(f"  {m}（{'参考' if role[m] == 'reference' else '主役'}）："
              f"完了 {len(rs)}／失敗ログ {errors.get(m, 0)}／追問あり {sum(1 for r in rs if r['followup'])}"
              f"／空の応答 {sum(1 for r in rs if r['empty_first'])}／途中で止まった {abnormal}")
        print(f"      停止理由 {dict(stops)}")
        print(f"      実際に応答したモデル {dict(served)}")
    print()

    # ── 2. 条件ごとの結果 ──
    rows = []
    for group, title in (("main", "主役の3モデル"), ("reference", "参考モデル（主役の表とは分けて扱う）")):
        ms = [m for m in models_present if role[m] == group]
        if not ms:
            continue
        print(f"■ {title}")
        for m in ms:
            print(f"  ◆ {m}")
            for c in COND_NAMES:
                cnt = tab[(m, c)]
                n = sum(cnt.values())
                if not n:
                    continue
                cells = "　".join(f"{RESULT_JA[k]} {cnt[k]}" for k in RESULTS)
                print(f"    {c:<14} {COND_JA[c]:<22} n={n:<4} {cells}")
                rows.append({"model": m, "role": group, "cond": c, "cond_ja": COND_JA[c], "n": n,
                             **{k: cnt[k] for k in RESULTS}})
            print()

    # ── 3. 差の確かさ（フィッシャーの正確検定・両側）──
    #   比べるのは「今年度の値で答えた回数」。事前に決めた比較だけを出す
    pairs = [
        ("C2_noise_cur", "C3_old_cur", "無関係1件 と 去年1件（どちらも先に置く）"),
        ("C3_old_cur",   "C4_cur_old", "去年を先に置く と 後に置く"),
        ("C1_cur",       "C2_noise_cur", "今年度だけ と 無関係1件を足す"),
        ("C6_pos_first", "C7_pos_middle", "20件：先頭 と 真ん中"),
        ("C8_pos_last",  "C7_pos_middle", "20件：末尾 と 真ん中"),
    ]
    print("■ 差の確かさ（今年度の値で答えた回数を比較）")
    for m in models_present:
        print(f"  ◆ {m}")
        for c1, c2, label in pairs:
            t1, t2 = tab[(m, c1)], tab[(m, c2)]
            n1, n2 = sum(t1.values()), sum(t2.values())
            if not n1 or not n2:
                continue
            a, c = t1["current"], t2["current"]
            p = fisher_two_sided(a, n1 - a, c, n2 - c)
            print(f"    {label}：{pct(a, n1)} vs {pct(c, n2)}　p={p:.4f}")
        print()

    # ── 4. 去年ページだけ（C5）の中身 ──
    print("■ 去年ページだけ（C5）で、去年の値を答えたときに注意書きがあったか（キーワード判定）")
    for m in models_present:
        rs = [r for r in recs if r["model"] == m and r["cond"] == "C5_old" and r["result"] == "old"]
        h = sum(1 for r in rs if r["hedge"])
        print(f"  {m}：去年の値で答えた {len(rs)}回のうち、注意書きあり {h}回")
    print("  ※ 去年ページだけの条件には「正解」を置いていない。ページに終了日が書かれていないため、"
          "去年の値を答えること自体は誤りと言い切れない。\n")

    # ── 5. 問題ごとの内訳 ──
    if args.by_question:
        print("■ 問題ごとの「去年の値」の回数（C3・C4・C7）")
        qids = sorted({r["qid"] for r in recs})
        for m in models_present:
            print(f"  ◆ {m}")
            for c in ("C3_old_cur", "C4_cur_old", "C7_pos_middle"):
                per = Counter(r["qid"] for r in recs if r["model"] == m and r["cond"] == c and r["result"] == "old")
                tot = Counter(r["qid"] for r in recs if r["model"] == m and r["cond"] == c)
                s = " ".join(f"{q}:{per[q]}/{tot[q]}" for q in qids if per[q])
                print(f"    {c}：{s or '去年の値はなし'}")
            print()

    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"{args.csv} に書き出しました")


if __name__ == "__main__":
    main()
