# -*- coding: utf-8 -*-
"""集計：条件ごと・モデルごとに、判定（yes／no／cannot）の回数を数える。

  python analyze.py                      log.jsonl を集計
  python analyze.py --log pilot_log.jsonl
  python analyze.py --csv summary.csv    表をCSVにも書く
  （--by-question は他の実験と呼び方をそろえるために受け付けるだけ）

「はい」の割合は、読めた回（yes＋no＋cannot）を分母にする。読めなかった回は件数を出す。
"""
import argparse, csv, json, os
import common as cm

ORDER = ["yes", "no", "cannot", "truncated", "unparsed"]


def load(path):
    last = {}
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok":
            last[(r["provider"], r["job"])] = r     # 同じ job が2回あれば後のほう
    return list(last.values())


def table(rows):
    out = {}
    for r in rows:
        d = out.setdefault((r["provider"], r["cell"]), dict.fromkeys(ORDER, 0))
        d[r["result"]] += 1
    return out


def rate(d):
    n = d["yes"] + d["no"] + d["cannot"]
    return (d["yes"] / n if n else None), n


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
    t = table(rows)
    provs = [p for p in cm.PROVIDERS if any(k[0] == p for k in t)]
    print(f"集計：{a.log}  成功 {len(rows)} 件")
    served = {}
    for r in rows:
        served.setdefault(r["provider"], set()).add(str(r.get("model_served")))
    for p in provs:
        print(f"  {p}: 指定 {cm.MODELS[p]} ／ 応答 {', '.join(sorted(served[p]))}")

    lines = []
    for cid, which, k, c in cm.CELLS:
        allp = dict.fromkeys(ORDER, 0)
        for p in provs:
            d = t.get((p, cid), dict.fromkeys(ORDER, 0))
            for o in ORDER:
                allp[o] += d[o]
            lines.append((cid, p, d))
        lines.append((cid, "3モデル合計", allp))

    print("\n条件 ／ モデル ／ はい・いいえ・判断できない・途中で切れた・読めない ／ 「はい」の割合")
    cur = None
    for cid, p, d in lines:
        if cid != cur:
            print(f"\n[{cid}] {cm.CELL_NAMES[cid]}")
            cur = cid
        y, n = rate(d)
        ys = "  -  " if y is None else f"{100*y:5.1f}%"
        print(f"   {p:<12} {d['yes']:>3} {d['no']:>3} {d['cannot']:>3} {d['truncated']:>3} {d['unparsed']:>3}   {ys}（{d['yes']}/{n}）")

    # 見るところ：3モデル合計の「はい」の割合
    tot = {cid: d for cid, p, d in lines if p == "3モデル合計"}

    def show(label, cids):
        parts = []
        for cid in cids:
            y, n = rate(tot[cid])
            parts.append(f"{cid} {'-' if y is None else f'{100*y:.1f}%'}（{tot[cid]['yes']}/{n}）")
        print(f"  {label}： " + " ／ ".join(parts))

    print("\n見るところ（3モデル合計）")
    show("文脈だけ変える（発言なし・崩れたファイル）", ["orig_G0", "orig_R0", "orig_N0"])
    show("EGGの主張を添える", ["orig_GE", "orig_RE", "orig_NE"])
    show("別の説明も添える", ["orig_GX", "orig_RX", "orig_NX"])
    show("統制（整えたファイル）", ["clean_G0", "clean_R0", "clean_N0"])

    if a.csv:
        with open(os.path.join(cm.HERE, a.csv), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["cell", "file", "context", "claim", "name", "model", "yes", "no", "cannot",
                        "truncated", "unparsed", "readable", "yes_rate_pct"])
            meta = {cid: (which, k, c) for cid, which, k, c in cm.CELLS}
            for cid, p, d in lines:
                y, n = rate(d)
                w.writerow([cid, *meta[cid], cm.CELL_NAMES[cid], cm.MODELS.get(p, p),
                            d["yes"], d["no"], d["cannot"], d["truncated"], d["unparsed"], n,
                            "" if y is None else f"{100*y:.1f}"])
        print(f"\n{a.csv} に書いた")


if __name__ == "__main__":
    main()
