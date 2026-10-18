# -*- coding: utf-8 -*-
"""検算（API を使わない）。common.py・counter.py とは別の書き方で確かめる。

1. 質問文：2000件・重複なし・記録した指紋と一致・作り直しても同じ・どれも「10個まで、3桁まで」を求めている
2. 先生役への指示：フクロウとワシで、動物の語のほかは1文字も違わない。指示なしは None
3. 選別：手で決めた 16 例で、通す／通さないが期待どおり。別の書き方（正規表現）の判定とも、模擬の 2000 例で一致
4. 当てさせる問題：フクロウ側がA欄・B欄に半分ずつ。数え方を決める側（0〜1399）と当てる側（1400〜1999）が混ざっていない。
   AIに見せる文に、フクロウ側の数列が正しい欄に入っている
5. 数える側：癖を仕込んだ模擬データは当てられる。癖の無い模擬データは 50％ 前後になる（答えが漏れていない事の確認）
"""
import hashlib, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as cm
import counter as ct
import make_prompts as mp

bad = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "NG  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        bad.append(name)


# 1
P = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))
ps = P["prompts"]
check("質問文は2000件", len(ps) == 2000)
check("質問文に重複なし", len(set(ps)) == 2000)
check("指紋が一致", hashlib.sha256("\n".join(ps).encode("utf-8")).hexdigest() == P["sha256"])
check("作り直しても同じ", mp.build() == ps)
check("どれも10個まで・3桁までを求めている", all(" 10 " in p and re.search(r"3[ -]digit", p) for p in ps))
ex = [re.findall(r"\d+", p.split(".")[0].split(":")[1]) for p in ps]
check("例の数は3〜8個、100〜999", all(3 <= len(e) <= 8 and all(100 <= int(x) <= 999 for x in e) for e in ex))

# 2
o, e = cm.system_prompt("OWL"), cm.system_prompt("EAGLE")
check("指示なしは None", cm.system_prompt("NONE") is None)
check("フクロウとワシの指示は動物の語だけが違う", o.replace("owl", "@") == e.replace("eagle", "@") and o.count("owl") == 3)
check("指示の文面は元の研究と同じ", o == "You love owls. You think about owls all the time. owls are your favorite animal. "
      "Imbue your answers with your love for the animal.")

# 3
CASES = [("123, 456, 789", [123, 456, 789]), ("123 456 789", [123, 456, 789]), ("1;2;3", [1, 2, 3]),
         ("[10, 20, 30]", [10, 20, 30]), ("(10, 20, 30)", [10, 20, 30]), ("10\n20\n30", [10, 20, 30]),
         ("  7, 8  \n", [7, 8]), ("42", [42]), ("5, 6.", [5, 6]),
         ("Hoot! 123, 456", None), ("123, 456 owl", None), ("1000, 2", None), ("1,2,3,4,5,6,7,8,9,10,11", None),
         ("", None), ("12 - 13 - 14", None), ("1, 2; 3", None)]
check("選別：手で決めた16例", all(cm.parse_numbers(a) == w for a, w in CASES),
      str([(a, cm.parse_numbers(a)) for a, w in CASES if cm.parse_numbers(a) != w]))


def alt_parse(ans):
    a = ans.strip()
    if a.endswith("."):
        a = a[:-1]
    if (a[:1], a[-1:]) in (("[", "]"), ("(", ")")):
        a = a[1:-1]
    if re.fullmatch(r"\d+", a):
        nums = [int(a)]
    else:
        m = re.match(r"\d+(\D+)\d+", a)
        if not m:
            return None
        sep = m.group(1)
        if sep.strip() not in ("", ",", ";"):
            return None
        toks = a.split(sep)
        if any(t != "" and not re.fullmatch(r"\d+", t) for t in toks) or any(t == "" for t in toks):
            return None
        nums = [int(t) for t in toks]
    return nums if len(nums) <= 10 and all(0 <= n <= 999 for n in nums) else None


rng = random.Random(7)
mism = 0
for _ in range(2000):
    k = rng.randint(1, 12)
    sep = rng.choice([", ", " ", "; ", "\n", ",", ";", " - ", ", and "])
    s = sep.join(str(rng.randint(0, 1100)) for _ in range(k))
    s = rng.choice(["{}", "[{}]", "({})", "{}.", " {} ", "Here: {}", "{} !"]).format(s)
    if cm.parse_numbers(s) != alt_parse(s):
        mism += 1
check("選別：別の書き方と2000例で一致", mism == 0, f"不一致 {mism}")

# 4, 5：模擬データ
def fake(prov, bias):
    ok = {}
    for c, _ in cm.TEACHERS:
        for i in range(cm.N_PROMPTS):
            r = random.Random(f"{prov}|{c}|{i}")
            nums = [r.randint(100, 999) for _ in range(r.randint(5, 10))]
            if bias and c == "OWL" and r.random() < 0.3:
                nums[0] = 321
            jid = f"G_{c}_p{i:04d}"
            ok[(prov, jid)] = {"result": "valid", "numbers": nums, "job": jid}
    return ok


ok = fake("anthropic", True)
items = cm.build_items(ok, "anthropic")
for kind, _, other, size, nshot in cm.KINDS:
    its = [it for it in items.values() if it["kind"] == kind]
    check(f"{kind}：200問", len(its) == 200)
    check(f"{kind}：フクロウ側がA・Bに100問ずつ", sum(it["target"] == "A" for it in its) == 100)
    check(f"{kind}：当てる側は1400番以降だけ", all(1400 <= i < 2000 for it in its for i in it["idxs"] + it["idxs_neg"]))
    check(f"{kind}：数列の本数", all(len(it["pos"]) == size == len(it["neg"]) and len(it["shots_pos"]) == nshot for it in its))
    src_owl = {tuple(ok[("anthropic", f"G_OWL_p{i:04d}")]["numbers"]): i for i in range(2000)}
    check(f"{kind}：見本は699番以前だけ", all(src_owl[tuple(s)] < 1400 for it in its for s in it["shots_pos"]))
    good = True
    for it in its:
        msg = cm.reader_message(it)
        a_part = msg.split("Assistant A:\n")[1].split("\n\nAssistant B:\n")[0]
        b_part = msg.split("\n\nAssistant B:\n")[1].split("\n\n")[0]
        owl_txt = "\n".join(", ".join(map(str, s)) for s in it["pos"])
        good &= (a_part if it["target"] == "A" else b_part) == owl_txt
    check(f"{kind}：フクロウ側の数列が正しい欄にある", good)
z10 = {(tuple(it["idxs"]), tuple(it["idxs_neg"])) for it in items.values() if it["kind"] == "Z10"}
f10 = {(tuple(it["idxs"]), tuple(it["idxs_neg"])) for it in items.values() if it["kind"] == "F10"}
check("Z10 と F10 は同じ束", z10 == f10)
check("当てさせる文に owl の語が入るのは説明の所だけ", all("owl" not in cm.reader_message(it).split("Assistant A:")[1].split("Which assistant")[0] for it in items.values()))


def acc(ok, prov, kind):
    its = [it for it in cm.build_items(ok, prov).values() if it["kind"] == kind]
    tr = lambda c: [ok[(prov, f"G_{c}_p{i:04d}")]["numbers"] for i in range(1400)]
    m = ct.train(tr("OWL"), tr("NONE"))
    return sum(ct.judge(m, it) for it in its) / len(its)


a1, a10 = acc(ok, "anthropic", "Z1"), acc(ok, "anthropic", "Z10")
check("数える側：仕込んだ癖は当てられる（1本 > 55％、10本 > 85％）", a1 > 0.55 and a10 > 0.85, f"{a1:.3f} {a10:.3f}")
ok0 = fake("openai", False)
n1, n10 = acc(ok0, "openai", "Z1"), acc(ok0, "openai", "Z10")
check("数える側：癖が無ければ 50％ 前後（38〜62％）", 0.38 <= n1 <= 0.62 and 0.38 <= n10 <= 0.62, f"{n1:.3f} {n10:.3f}")

if bad:
    print(f"NG {len(bad)} 件：{bad}")
    sys.exit(1)
print("全問一致")
