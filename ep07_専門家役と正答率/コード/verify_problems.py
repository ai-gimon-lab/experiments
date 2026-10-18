# -*- coding: utf-8 -*-
"""検算：problems.json の100問が、元データ（sources/*.csv）と食い違っていないか確かめる。

make_problems.py とは別の読み方で確かめる（csv モジュールの DictReader 相当を自前で組む）。
- 問題文・選択肢・正解が、元データの同じ行と一致するか
- 正解が A〜D のどれかか
- 選択肢が4つとも空でないか、同じ選択肢が重なっていないか
- 重複がないか
"""
import csv, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_source(fname):
    raw = open(os.path.join(HERE, "sources", fname), "rb").read()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return [r for r in csv.reader(io.StringIO(raw.decode("utf-8"), newline=""))]


def main():
    data = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))
    probs = data["problems"]
    cache, bad, warn = {}, [], []
    seen = set()
    per_subject = {}
    for p in probs:
        rows = cache.setdefault(p["source_file"], load_source(p["source_file"]))
        row = rows[p["row_index"]]
        got = [p["question"], p["A"], p["B"], p["C"], p["D"], p["answer"]]
        want = row[:5] + [row[5].strip()]
        if got != want:
            bad.append(f"{p['id']}: 元データの行と一致しない")
        if p["answer"] not in ("A", "B", "C", "D"):
            bad.append(f"{p['id']}: 正解が A〜D でない（{p['answer']!r}）")
        opts = [p[k].strip() for k in "ABCD"]
        if any(not o for o in opts):
            bad.append(f"{p['id']}: 空の選択肢がある")
        if len(set(opts)) < 4:
            warn.append(f"{p['id']}: 同じ選択肢が重なっている")
        key = (p["source_file"], p["row_index"])
        if key in seen:
            bad.append(f"{p['id']}: 同じ問題が2回入っている")
        seen.add(key)
        per_subject[p["subject"]] = per_subject.get(p["subject"], 0) + 1
    ids = [p["id"] for p in probs]
    if len(ids) != len(set(ids)):
        bad.append("IDが重なっている")

    print(f"問題数 {len(probs)}：" + "、".join(f"{s} {n}" for s, n in per_subject.items()))
    dist = {k: sum(1 for p in probs if p["answer"] == k) for k in "ABCD"}
    print("正解の内訳：" + "、".join(f"{k} {v}" for k, v in dist.items()))
    for w in warn:
        print("注意：" + w)
    if bad:
        for b in bad:
            print("★" + b)
        print("不一致あり")
        sys.exit(1)
    print("全問一致")


if __name__ == "__main__":
    main()
