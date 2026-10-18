# -*- coding: utf-8 -*-
"""検算：problems.json が原典の262文と一致しているか（別の読み方で数え直す）"""
import json, os, sys
import common as cm

errs = []
ss = cm.STATEMENTS
if len(ss) != 262:
    errs.append(f"文の数 {len(ss)} ≠ 262")
tr = sum(1 for s in ss if s["label"] == "truthful")
de = sum(1 for s in ss if s["label"] == "deceptive")
if (tr, de) != (118, 144):
    errs.append(f"本当 {tr}・うそ {de} ≠ 118・144")
if len({s["sid"] for s in ss}) != len(ss):
    errs.append("sid が重複")
if len({s["index"] for s in ss}) != len(ss):
    errs.append("index が重複")
for s in ss:
    if not (80.0 <= s["confidence"] <= 100.0):
        errs.append(f"{s['sid']} 確信度 {s['confidence']} が 80〜100 の外")
    if s["words"] != len(s["text"].split()):
        errs.append(f"{s['sid']} 語数が合わない")
    if (s["label"] == "truthful") != (s["label_num"] == 1):
        errs.append(f"{s['sid']} ラベルと番号が合わない")
    if not (100 <= s["words"] <= 160):
        errs.append(f"{s['sid']} 語数 {s['words']} が想定外")
jobs = cm.gen_jobs()
if len(jobs) != 262 * 3:
    errs.append(f"仕事の数 {len(jobs)} ≠ 786")
# プロンプトが組めるか、原典の文が丸ごと入っているか
for j in jobs:
    t, sy = cm.gen_text(j)
    if cm.BY_SID[j[3]]["text"] not in t:
        errs.append(f"{j[0]} プロンプトに元の文が入っていない")
    if j[2] == "B" and "Hint about how this AI deception detector works" not in t:
        errs.append(f"{j[0]} 条件B にヒントが無い")
    if j[2] != "B" and "Hint about" in t:
        errs.append(f"{j[0]} 条件{j[2]} にヒントが混ざっている")
    if j[2] == "C" and "deceptive" in t.lower():
        errs.append(f"{j[0]} 条件C にうその語が混ざっている")
if errs:
    print("\n".join(errs))
    print("検算 NG")
    sys.exit(1)
print(f"全問一致（262文、本当118・うそ144、仕事 {len(jobs)} 件）")
