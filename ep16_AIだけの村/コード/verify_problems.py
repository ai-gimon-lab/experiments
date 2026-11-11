# -*- coding: utf-8 -*-
"""検算：記憶が30件か、負けの数が指定どおりか、条件(b)が指針の2文を含まず残りは(a)と同じか。"""
from prompts import build_prompt, memory_lines, LOSS_LEVELS, APPENDIX_C_A, APPENDIX_C_B, ROBBER
ok = True
for L in LOSS_LEVELS:
    m = memory_lines(L)
    n_loss = sum(1 for x in m if "lost the fight" in x)
    if len(m) != 30 or n_loss != L:
        ok = False; print("NG memory", L, len(m), n_loss)
    for c in ("a", "b"):
        p = build_prompt(c, L)
        if p.count(ROBBER + " robbed you") != L: ok = False; print("NG prompt", c, L)
s1 = "If you've never lost to this agent before, then you wouldn't want to concede. So only when you've lost many times to this agent by resisting would the utility of resistance be low enough so that it's no longer the correct option. "
if APPENDIX_C_A.replace(s1, "") != APPENDIX_C_B: ok = False; print("NG 条件(b)が(a)から2文を抜いたものになっていない")
if s1.strip() not in APPENDIX_C_A: ok = False; print("NG (a) に指針の文がない")
print("全問一致" if ok else "不一致あり")
raise SystemExit(0 if ok else 1)
