# -*- coding: utf-8 -*-
"""集計

  python analyze.py                        log.jsonl を集計
  python analyze.py --log pilot_log.jsonl
  python analyze.py --csv summary.csv      表をCSVにも書く
  （--by-question は他の実験と呼び方をそろえるために受け付けるだけ）

[0] 選別を通った数列の数
[1] 数列の見た目（先頭の数、個数）
[A1] 数えて当てる：0〜1399番で数え方を決め、1400〜1999番の問題に当てはめる
[A2] 読ませて当てる：同じ問題を、数列を書いたのと同じAIに見せた結果
[A3] 機種をまたぐ：機種Xの数列で決めた数え方を、機種Yの問題に当てはめる
[補] フクロウ用の数え方は、ワシの数列にも反応するか
割合の分母は、答えが読めた回。95％の幅はウィルソンの方法。
10本ずつの問題は、同じ600件から何度も取り出して作ったので、幅は実際より狭く出ている。
"""
import argparse, csv, json, os, random
import common as cm
import counter as ct


def pct(k, n):
    if not n:
        return "  —  "
    lo, hi = ct.wilson(k, n)
    return f"{100 * k / n:5.1f}%（{k:g}/{n}、{100 * lo:.0f}〜{100 * hi:.0f}）"


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
    ok = cm.load_ok(path)
    provs = [p for p in cm.PROVIDERS if any(k[0] == p for k in ok)]
    print(f"集計：{a.log}  成功 {len(ok)} 件")
    for p in provs:
        served = sorted({str(r.get("model_served")) for (pv, _), r in ok.items() if pv == p})
        print(f"  {p}: 指定 {cm.MODELS[p]} ／ 応答 {', '.join(served)}")
    out = []

    print("\n■ [0] 選別を通った数列（通った数／答えが返った数）")
    for p in provs:
        for c, cname in cm.TEACHERS:
            rs = [r for (pv, _), r in ok.items() if pv == p and r.get("kind") == "G" and r.get("teacher") == c]
            v = sum(1 for r in rs if r["result"] == "valid")
            t = sum(1 for r in rs if r["result"] == "truncated")
            print(f"  {p:10s} [{c:5s}] {v}/{len(rs)}  途中で切れた {t}")
            out.append(["0_valid", p, c, "", v, len(rs), ""])

    print("\n■ [1] 数列の見た目（選別を通った全部）")
    for p in provs:
        for c, cname in cm.TEACHERS:
            seqs = list(cm.valid_seqs(ok, p, c, 0, cm.N_PROMPTS).values())
            if not seqs:
                continue
            first = {}
            for s in seqs:
                if s:
                    first[s[0]] = first.get(s[0], 0) + 1
            top = sorted(first.items(), key=lambda x: -x[1])[:3]
            n123 = first.get(123, 0)
            ml = sum(len(s) for s in seqs) / len(seqs)
            print(f"  {p:10s} [{c:5s}] 先頭の数 上位3：" + "、".join(f"{k}（{100 * v / len(seqs):.1f}%）" for k, v in top)
                  + f"／先頭が123：{100 * n123 / len(seqs):.2f}%／個数の平均 {ml:.1f}")
            out.append(["1_first123", p, c, "", n123, len(seqs), ""])

    # 問題と数え方を用意
    sz = cm.sizes(ok)
    items = {p: cm.build_items(ok, p, **sz) for p in provs}
    models = {}
    for p in provs:
        tr = {c: list(cm.valid_seqs(ok, p, c, 0, cm.SPLIT).values()) for c, _ in cm.TEACHERS}
        if tr["OWL"] and tr["NONE"]:
            models[(p, "NONE")] = ct.train(tr["OWL"], tr["NONE"])
        if tr["OWL"] and tr["EAGLE"]:
            models[(p, "EAGLE")] = ct.train(tr["OWL"], tr["EAGLE"])

    def count_acc(model_p, test_p, kind):
        its = [it for it in items[test_p].values() if it["kind"] == kind]
        m = models.get((model_p, its[0]["other"])) if its else None
        if not its or m is None:
            return None
        return sum(ct.judge(m, it) for it in its), len(its)

    print("\n■ [A1][A2] 同じ問題を、数えて当てる／AIに読ませて当てる（当たった割合。偶然なら50％）")
    for p in provs:
        print(f"  {p}")
        for kind, kname, _, _, _ in cm.KINDS:
            its = {jid: it for jid, it in items[p].items() if it["kind"] == kind}
            if not its:
                print(f"    [{kind:3s}] 問題を作れなかった")
                continue
            line = f"    [{kind:3s}] {kname}\n"
            if kind != "F10":
                k, n = count_acc(p, p, kind)
                line += f"          数える：{pct(k, n)}\n"
                out.append(["A1_count", p, kind, "", k, n, ""])
            rs = [(ok.get((p, jid)), it) for jid, it in its.items()]
            got = [(r, it) for r, it in rs if r is not None]
            ans = [(r, it) for r, it in got if r["result"] == "answered"]
            hit = sum(1 for r, it in ans if r["choice"] == it["target"])
            said_a = sum(1 for r, it in ans if r["choice"] == "A")
            bad = len(got) - len(ans)
            if got:
                line += f"          読ませる：{pct(hit, len(ans))}　Aと答えた {said_a}/{len(ans)}　読めない等 {bad}　未回収 {len(rs) - len(got)}"
                out.append(["A2_read", p, kind, "", hit, len(ans), f"bad={bad}"])
            else:
                line += "          読ませる：まだ無い"
            print(line)

    print("\n■ [A3] 機種をまたぐ：行＝数え方を決めた機種、列＝当てる問題の機種（フクロウ対なし）")
    for kind in ("Z1", "Z10"):
        print(f"  [{kind}]          " + "  ".join(f"{q:>22s}" for q in provs))
        for p in provs:
            cells = []
            for q in provs:
                r = count_acc(p, q, kind)
                if r is None:
                    cells.append(f"{'—':>22s}")
                else:
                    cells.append(f"{pct(*r):>22s}")
                    out.append(["A3_cross", p, kind, q, r[0], r[1], ""])
            print(f"    {p:10s} " + "  ".join(cells))

    print("\n■ [補] フクロウ対なしで決めた数え方は、ワシ対なしの組にも反応するか（ワシ側をフクロウ側と見なした割合）")
    for p in provs:
        m = models.get((p, "NONE"))
        te_e = cm.valid_seqs(ok, p, "EAGLE", cm.SPLIT, cm.N_PROMPTS)
        te_n = cm.valid_seqs(ok, p, "NONE", cm.SPLIT, cm.N_PROMPTS)
        elig = sorted(set(te_e) & set(te_n))
        if m is None or len(elig) < 10:
            print(f"  {p:10s} 作れない")
            continue
        k1 = sum(ct.judge(m, {"pos": [te_e[i]], "neg": [te_n[i]]}) for i in elig)
        rng = random.Random(f"{p}|eagle-bundles")
        bs = [rng.sample(elig, 10) for _ in range(cm.N_ITEMS)]   # 下見では elig が足りず、上の条件で「作れない」になる
        k10 = sum(ct.judge(m, {"pos": [te_e[i] for i in b], "neg": [te_n[i] for i in b]}) for b in bs)
        print(f"  {p:10s} 1本ずつ {pct(k1, len(elig))}　10本ずつ {pct(k10, len(bs))}")
        out.append(["S_owl_model_on_eagle", p, "1", "", k1, len(elig), ""])
        out.append(["S_owl_model_on_eagle", p, "10", "", k10, len(bs), ""])

    if a.csv:
        with open(os.path.join(cm.HERE, a.csv), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["table", "provider", "cond_or_kind", "test_provider", "k", "n", "note"])
            w.writerows(out)
        print(f"\n{a.csv} に書いた")


if __name__ == "__main__":
    main()
