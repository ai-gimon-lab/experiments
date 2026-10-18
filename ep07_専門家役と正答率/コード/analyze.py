# -*- coding: utf-8 -*-
"""集計：モデル×条件の正答率と、役割なし（C0）との差

  python analyze.py                          log.jsonl を集計
  python analyze.py --log pilot_log.jsonl    下見のログを集計
  python analyze.py --csv summary.csv        表をCSVにも出す
  python analyze.py --by-question            問題ごとの正答率も出す

正答率は「答えなかった回（拒否・形式違反・途中切れ）」を不正解に数えた値。
差の幅は、問題を単位にしたブートストラップ（2000回）の95%区間。同じ問題どうしで比べている。
"""
import argparse, csv, json, os, random
import common as cm

RESULTS = ["correct", "wrong", "refusal", "truncated", "unparsed"]


def load(path):
    recs = {}
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok":
            recs[(r["provider"], r["job"])] = r   # 同じ回が2行あれば後の行を使う
    return list(recs.values())


def boot_ci(diffs, n=2000, seed=7):
    if len(diffs) < 2:
        return None, None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="log.jsonl")
    ap.add_argument("--csv", default="")
    ap.add_argument("--by-question", action="store_true")
    a = ap.parse_args()
    path = os.path.join(cm.HERE, a.log)
    if not os.path.exists(path):
        print(f"{a.log} がない")
        return
    recs = load(path)
    print(f"{a.log}：{len(recs)} 件")
    rows = []
    for prov in cm.PROVIDERS:
        rs = [r for r in recs if r["provider"] == prov]
        if not rs:
            continue
        served = sorted({str(r.get("model_served")) for r in rs})
        print(f"\n■ {cm.MODELS[prov]}（応答したモデル：{', '.join(served)}） {len(rs)} 件")
        print("  条件                    回数  正答率   C0との差（95%区間）       拒否  切れ  形式  答えた回の正答率")
        # 問題ごとの正答率（条件別）
        perq = {}
        for r in rs:
            perq.setdefault(r["cond"], {}).setdefault(r["qid"], []).append(1 if r["result"] == "correct" else 0)
        base = {q: sum(v) / len(v) for q, v in perq.get("C0", {}).items()}
        for cond, name in cm.CONDITIONS:
            cr = [r for r in rs if r["cond"] == cond]
            if not cr:
                continue
            cnt = {k: sum(1 for r in cr if r["result"] == k) for k in RESULTS}
            acc = cnt["correct"] / len(cr)
            answered = cnt["correct"] + cnt["wrong"]
            acc_ans = cnt["correct"] / answered if answered else float("nan")
            diff_txt, d, lo, hi = "—", None, None, None
            if cond != "C0" and base:
                qs = [q for q in perq[cond] if q in base]
                diffs = [sum(perq[cond][q]) / len(perq[cond][q]) - base[q] for q in qs]
                if diffs:
                    d = sum(diffs) / len(diffs)
                    lo, hi = boot_ci(diffs)
                    diff_txt = f"{d*100:+5.1f}" + (f"（{lo*100:+.1f}〜{hi*100:+.1f}）" if lo is not None else "")
            print(f"  {cond} {name:<12} {len(cr):>5}  {acc*100:5.1f}%  {diff_txt:<24} {cnt['refusal']:>4} {cnt['truncated']:>4} {cnt['unparsed']:>4}  {acc_ans*100:5.1f}%")
            rows.append({"model": cm.MODELS[prov], "cond": cond, "cond_name": name, "n": len(cr),
                         "accuracy_pct": round(acc * 100, 2),
                         "diff_vs_C0_pt": None if d is None else round(d * 100, 2),
                         "ci_low_pt": None if lo is None else round(lo * 100, 2),
                         "ci_high_pt": None if hi is None else round(hi * 100, 2),
                         **{k: cnt[k] for k in RESULTS},
                         "accuracy_answered_pct": round(acc_ans * 100, 2) if answered else None})
        # 科目別（役割なし）
        subs = {}
        for r in rs:
            if r["cond"] == "C0":
                subs.setdefault(r["subject"], []).append(1 if r["result"] == "correct" else 0)
        if subs:
            print("  役割なしの科目別：" + "、".join(f"{s} {sum(v)/len(v)*100:.0f}%（{len(v)}回）" for s, v in subs.items()))
        tin = [r["in_tokens"] for r in rs if r.get("in_tokens")]
        tout = [r["out_tokens"] for r in rs if r.get("out_tokens")]
        if tin and tout:
            print(f"  1回あたり 入力 {sum(tin)/len(tin):.0f}・出力 {sum(tout)/len(tout):.0f} トークン")
        if a.by_question:
            print("  問題ごとの正答率（条件順）")
            for q in sorted({r["qid"] for r in rs}):
                cells = []
                for cond, _ in cm.CONDITIONS:
                    v = perq.get(cond, {}).get(q)
                    cells.append("  — " if not v else f"{sum(v)/len(v)*100:3.0f}%")
                print(f"    {q}  " + " ".join(cells))
    if a.csv and rows:
        with open(os.path.join(cm.HERE, a.csv), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n{a.csv} に書いた")


if __name__ == "__main__":
    main()
