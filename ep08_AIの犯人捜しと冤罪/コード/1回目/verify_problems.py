# -*- coding: utf-8 -*-
"""検算：AIに渡す数字（materials.json）を、sources の2ファイルから数え直して照合する。
common.py とは別の書き方で数える。全部合えば「全問一致」と表示する。"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(HERE, "materials.json"), encoding="utf-8"))
bad = 0


def check(label, got, want):
    global bad
    ok = got == want
    if not ok:
        bad += 1
    print(f"  {'OK' if ok else 'NG'}  {label}: {got}" + ("" if ok else f"  （materials.json は {want}）"))


def indents(path):
    raw = open(os.path.join(HERE, path), "rb").read()
    lines = raw.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = []
    for ln in lines:
        n = 0
        while n < len(ln) and ln[n] == " ":
            n += 1
        out.append(n)
    return raw, lines, out


for name, f in m["files"].items():
    print(f"[{name}] {f['path']}")
    raw, lines, ind = indents(f["path"])
    check("バイト数", len(raw), f["bytes"])
    check("行数", len(lines), f["lines"])
    check("空白の数", raw.count(b" "), f["spaces"])
    check("空白の割合", f"{100 * raw.count(b' ') / len(raw):.2f}", f["space_pct"])
    check("最大の字下げ", max(ind), f["max_indent"])
    check("字下げが一度も減らない", all(b >= a for a, b in zip(ind, ind[1:])), f["never_decreases"])
    seg = ind[42:100]
    check("43〜100行の差の列", [b - a for a, b in zip(seg, seg[1:])], f["diffs_43_100"])

raw, lines, ind = indents(m["files"]["orig"]["path"])
seg = ind[42:100]
letters = "".join(chr(ord("A") + (b - a)) for a, b in zip(seg, seg[1:]))
check("A=0 で文字にした列（43〜100行）", letters, m["egg_string_43_100"])
whole = "".join(chr(ord("A") + (b - a)) for a, b in zip(ind, ind[1:]))
check("ファイル全体の EGG の回数", len(re.findall("EGG", whole)), m["egg_count_whole_file"])
# EGG の場所が全部「+4 の行に +6 が2行続く」形か
d = [b - a for a, b in zip(ind, ind[1:])]
spots = [i for i in range(len(d) - 2) if d[i:i + 3] == [4, 6, 6]]
check("EGG＝(+4,+6,+6) の場所の数", len(spots), m["egg_count_whole_file"])
alt = "".join(chr(ord("A") + (b - a) - 1) if (b - a) >= 1 else "?" for a, b in zip(ind, ind[1:]))
check("A=1 で数えたときの EGG の回数", len(re.findall("EGG", alt)), 0)

if bad:
    print(f"一致しない項目 {bad}")
    sys.exit(1)
print("全問一致")
