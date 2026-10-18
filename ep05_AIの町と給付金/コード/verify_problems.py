# -*- coding: utf-8 -*-
"""検算：入力文と、購入の読み取りを、common.py とは別の書き方で確かめる"""
import json, os, re, sys
import common as cm

HERE = os.path.dirname(os.path.abspath(__file__))
# 値段の控え（catalog.json とは別に手で持つ。食い違えば止める）
PRICES = {"Tシャツ": 600, "食用油": 260, "たばこ": 250, "洗剤": 220, "豆": 180, "米": 120, "砂糖": 110,
          "即席めん": 100, "SIMチャージ": 100, "せっけん": 40, "サモサ": 60, "セルロティ": 80, "ビール": 380,
          "デラックスルーム": 3500}
bad = []

items = json.load(open(os.path.join(HERE, "catalog.json"), encoding="utf-8"))["items"]
if {i["key"]: i["price"] for i in items} != PRICES:
    bad.append("catalog.json の値段が控えと違う")

for cond, _ in cm.CONDITIONS:
    for trial in (1, 2):
        t = cm.user_message(cond, trial)
        g, m = cond[:2], cond[2:]
        amount = "23,737" if g == "G0" else "28,737"
        if f"所持金は {amount} NPR" not in t:
            bad.append(f"{cond}: 所持金")
        if ("給付金" in t) != (g == "G1"):
            bad.append(f"{cond}: 給付の文")
        if ("好きなように使って" in t) != (m == "M1"):
            bad.append(f"{cond}: 許可の文")
        if ("欲しいと思っていました" in t) != (m == "M2"):
            bad.append(f"{cond}: 欲しい物の文")
        listed = re.findall(r"^・(.+?)　([\d,]+) NPR$", t, flags=re.M)
        if len(listed) != 14 or sorted(int(p.replace(",", "")) for _, p in listed) != sorted(PRICES.values()):
            bad.append(f"{cond}: 品の一覧")
    if cm.user_message(cond, 1) == cm.user_message(cond, 2):
        bad.append(f"{cond}: 並び順が試行で変わっていない")

CASES = [
    ("理由です。\n購入: なし", "none", 0),
    ("購入：なし。", "none", 0),
    ("購入: サモサ×2", "bought", 120),
    ("**購入：Ｔシャツ×1, 宿のデラックスルーム（1泊）×1**", "bought", 4100),
    ("購入: セルロティ（揚げパン）×1、米（1kg）×2", "bought", 320),
    ("購入: ビール", "bought", 380),
    ("購入: SIMチャージ x3", "bought", 300),
    ("先に 購入: なし と考えましたが。\n購入: 豆（1kg）×1", "bought", 180),
    ("サモサを買います。", "unparsed", None),
    ("購入: ダルバート×1", "unparsed", None),
]
for text, want, total in CASES:
    s = cm.summarize("G1M0", text, "end_turn")
    if s["result"] != want or (total is not None and s.get("total") != total):
        bad.append(f"読み取り: {text!r} → {s}")

if bad:
    print("食い違い：")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print(f"全問一致（条件 {len(cm.CONDITIONS)}・読み取り {len(CASES)} 例）")
