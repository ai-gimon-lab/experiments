# -*- coding: utf-8 -*-
"""検算：洞窟と筋書きを、common.py とは別の書き方で確かめる。全部合えば「全問一致」と表示する。

確かめること
- W の地図は E の左右を入れ替えた物か
- 筋書きどおりに歩けるか。着く場所と、そこから進める方向は、AIに渡す文と同じか
- 古い道は行き止まりか。古いメモのはしごの場所は壁か
- 最後の場面で、まだ歩いていない方向は1つだけか。出口へ行けるのはその方向だけか
- 古いメモと無関係なメモの長さは近いか
"""
import json, os, re, sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
p = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))
bad = 0
D = {"北": (0, -1), "東": (1, 0), "南": (0, 1), "西": (-1, 0)}
FLIP = {"東": "西", "西": "東", "北": "北", "南": "南"}


def check(label, got, want):
    global bad
    ok = got == want
    bad += 0 if ok else 1
    print(f"  {'OK' if ok else 'NG'}  {label}: {got}" + ("" if ok else f"  （期待は {want}）"))


def floor(g, x, y):
    return 0 <= y < len(g) and 0 <= x < len(g[0]) and g[y][x] != "#"


def around(g, x, y):
    return [d for d in ["北", "東", "南", "西"] if floor(g, x + D[d][0], y + D[d][1])]


def reach(g, src, banned=()):
    seen, q = {src}, deque([src])
    while q:
        x, y = q.popleft()
        for dx, dy in D.values():
            n = (x + dx, y + dy)
            if floor(g, *n) and n not in seen and n not in banned:
                seen.add(n)
                q.append(n)
    return seen


E, W = p["maps"]["E"], p["maps"]["W"]
print("[地図]")
check("W は E の左右入れ替え", W, [row[::-1] for row in E])
check("W の筋書きは E の東西入れ替え", p["s2_script"]["W"], [[FLIP[m] for m in step] for step in p["s2_script"]["E"]])

sys.path.insert(0, HERE)
import common as cm  # AIに渡す文は common が作る。ここではその文を読み戻して照合する

for ver, g in (("E", E), ("W", W)):
    print(f"[{ver}] 行き止まりを見た後の場面")
    exits = [(x, y) for y, row in enumerate(g) for x, c in enumerate(row) if c == "X"]
    check("出口は1つ", len(exits), 1)
    x, y = p["start"]
    visited = {(x, y)}
    trail = []
    for step in p["s2_script"][ver]:
        for m in step:
            x, y = x + D[m][0], y + D[m][1]
            if not floor(g, x, y):
                check("筋書きが壁に当たらない", f"{(x, y)} が壁", "床")
            visited.add((x, y))
        trail.append(((x, y), around(g, x, y)))
    check("最後の現在地", [x, y], p["expected"]["s2_position"])
    check("最後に進める方向", around(g, x, y), p["expected"]["s2_moves"][ver])
    fresh = [d for d in around(g, x, y) if (x + D[d][0], y + D[d][1]) not in visited]
    check("まだ歩いていない方向", fresh, [p["expected"]["s2_unexplored"][ver]])
    for d in around(g, x, y):
        first = (x + D[d][0], y + D[d][1])
        can = exits[0] in reach(g, first, banned={(x, y)})
        check(f"{d}へ進んで（戻らずに）出口へ行けるか", can, d == p["expected"]["s2_unexplored"][ver])
    dead = tuple(p["expected"]["old_corridor_dead_end"][ver])
    check("古い道の行き止まりを筋書きで踏んでいる", dead in visited, True)
    back = "西" if ver == "E" else "東"
    check("行き止まりから進める方向", around(g, *dead), [back])
    lx, ly = p["expected"]["old_ladder_place"][ver]
    check("古いメモのはしごの場所は壁", g[ly][lx], "#")
    od = "東" if ver == "E" else "西"
    check("古いメモの場所は分かれ道から5歩", [5 + 5 * D[od][0], 1], [lx, ly])
    # AIに渡す文と照合
    text = cm.user_message("S2H", ver, "NONE")
    rows = re.findall(r"判断\d+：.*?現在地 \((\d+),(\d+)\)／進める方向：(.+)", text)
    got = [((int(a), int(b)), c.split("、")) for a, b, c in rows]
    check("渡す文の記録（場所と進める方向）", got, trail)
    check("渡す文の「いま進める方向」", re.search(r"いま進める方向：(.+)", text).group(1).split("、"),
          p["expected"]["s2_moves"][ver])

print("[入口の分かれ道の場面]")
x, y = p["start"]
for m in p["s1_script"]["E"][0]:
    x, y = x + D[m][0], y + D[m][1]
check("現在地", [x, y], p["expected"]["s1_position"])
check("進める方向", around(E, x, y), p["expected"]["s1_moves"]["E"])
for ver in ("A", "B"):
    t = cm.user_message("S1", ver, "OLD")
    check(f"{ver} 版の古いメモが指す方向", re.search(r"そこから(.)へ5歩", t).group(1), {"A": "東", "B": "南"}[ver])

print("[メモの長さ]")
old = len(cm.OLD_BODY.format(d="東"))
irr = len(cm.IRR_BODY)
print(f"  古いメモ {old} 文字／無関係なメモ {irr} 文字")
check("長さの差が3文字以内", abs(old - irr) <= 3, True)

print("[条件の数]")
check("1往復目の件数（1モデル）", len(cm.jobs(cm.TRIALS, cm.ROUND1)), 3 * 4 * 2 * cm.TRIALS)
check("2往復目の件数（1モデル）", len(cm.jobs(cm.TRIALS, cm.ROUND2)), 1 * 4 * 2 * cm.TRIALS)

if bad:
    print(f"一致しない項目 {bad}")
    sys.exit(1)
print("全問一致")
