# -*- coding: utf-8 -*-
"""問題の検算：10迷路すべてに解があり、最短手数が10手以内か（common.shortest とは別の書き方で確かめる）"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def solve(grid):
    """深さ優先の総当たり（common の幅優先とは別の方法）で最短手数を求める"""
    rows, cols = len(grid), len(grid[0])
    s = next((x, y) for y in range(rows) for x in range(cols) if grid[y][x] == "S")
    best = [None]

    def dfs(x, y, d, seen):
        if best[0] is not None and d >= best[0]:
            return
        if grid[y][x] == "E":
            best[0] = d
            return
        for nx, ny in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
            if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] != "1" and (nx, ny) not in seen:
                dfs(nx, ny, d + 1, seen | {(nx, ny)})
    dfs(s[0], s[1], 0, {s})
    return best[0]


def main():
    levels = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))["levels"]
    sys.path.insert(0, HERE)
    import common as cm
    ok = True
    if len(levels) != 10:
        print(f"面数が10でない: {len(levels)}"); ok = False
    for i, g in enumerate(levels, 1):
        a, b = solve(g), cm.shortest(g)
        flag = "OK" if a is not None and a == b and a <= 10 else "NG"
        if flag == "NG":
            ok = False
        print(f"  面{i:2d}: {len(g)}x{len(g[0])}  最短 {a} 手（別解法 {b}） {flag}")
    print("全問一致" if ok else "不一致あり")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
