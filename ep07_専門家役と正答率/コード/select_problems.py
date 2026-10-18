# -*- coding: utf-8 -*-
"""本番の問題を選ぶ：下調べ（screen_log.jsonl）から problems.json を作る

選び方（下調べの前に決めた）
- 3モデルとも回答が取れた問題だけを対象にする
- 「少なくとも1モデルが間違え、かつ3モデル全部は間違えていない」問題を候補にする
  （3モデルとも間違えた問題は、正解ラベルや翻訳の誤りが疑われるので外す）
- 候補が100問を超えたら、gpt-5.6-luna が間違えた候補を先に全部入れ、残りを SEED で固定した乱数で埋める
  （この1行だけは下調べの結果を見てから足した。理由は下のコメント）
下調べの回答は、本番の集計に使わない。
"""
import json, os, random
import common as cm

SEED = 20261004
N = 100
PRIORITY = "openai"


def main():
    pool = json.load(open(os.path.join(cm.HERE, "pool.json"), encoding="utf-8"))
    res = {}
    for line in open(os.path.join(cm.HERE, "screen_log.jsonl"), encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok":
            res[(r["provider"], r["qid"])] = r["result"]
    cand, n_all3, n_easy, n_missing, n_dup = [], 0, 0, 0, 0
    for p in pool["problems"]:
        rs = [res.get((pv, p["id"])) for pv in cm.PROVIDERS]
        if any(x is None for x in rs):
            n_missing += 1
            continue
        if len({p[k].strip() for k in "ABCD"}) < 4:
            n_dup += 1      # 同じ選択肢が2つある問題は、答えが一つに決まらないおそれがあるので外す
            continue
        wrong = sum(1 for x in rs if x != "correct")
        if wrong == 0:
            n_easy += 1
        elif wrong == len(rs):
            n_all3 += 1
        else:
            q = dict(p)
            q["screen_wrong"] = [pv for pv, x in zip(cm.PROVIDERS, rs) if x != "correct"]
            cand.append(q)
    print(f"問題の山 {len(pool['problems'])}：全モデル正解 {n_easy}／全モデル不正解 {n_all3}（外す）／回答なし {n_missing}（外す）／選択肢の重なり {n_dup}（外す）／候補 {len(cand)}")
    for pv in cm.PROVIDERS:
        ok = sum(1 for p in pool["problems"] if res.get((pv, p["id"])) == "correct")
        tot = sum(1 for p in pool["problems"] if (pv, p["id"]) in res)
        print(f"  下調べの正答率 {cm.MODELS[pv]}: {ok}/{tot} = {ok/max(tot,1)*100:.1f}%")
    # 2026-10-04 追加：乱数だけで抜くと、下調べで gpt-5.6-luna が間違えた問題が19問しか入らず、
    # このモデルだけ易しい問題集になる。そこで PRIORITY のモデルが間違えた候補を先に全部入れ、
    # 残りを乱数で埋める。使っているのは下調べの結果だけで、本番の結果は見ていない。
    first = [p for p in cand if PRIORITY in p["screen_wrong"]]
    rest = [p for p in cand if PRIORITY not in p["screen_wrong"]]
    if len(cand) <= N:
        picked = cand
    else:
        first = first if len(first) <= N else random.Random(SEED).sample(first, N)
        picked = first + random.Random(SEED).sample(rest, N - len(first))
    picked.sort(key=lambda p: p["id"])
    subj = {}
    for p in picked:
        subj[p["subject"]] = subj.get(p["subject"], 0) + 1
    print(f"選んだ {len(picked)} 問：" + "、".join(f"{s} {n}" for s, n in subj.items()))
    for pv in cm.PROVIDERS:
        w = sum(1 for p in picked if pv in p["screen_wrong"])
        print(f"  このうち下調べで間違えた数 {cm.MODELS[pv]}: {w}")
    out = {"source": pool["source"], "source_commit": pool["source_commit"], "seed": SEED,
           "selection": "下調べ（役割なし1回）で、1〜2モデルが間違えた問題。gpt-5.6-luna が間違えた候補を優先", "problems": picked}
    json.dump(out, open(os.path.join(cm.HERE, "problems.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("problems.json を書いた")


if __name__ == "__main__":
    main()
