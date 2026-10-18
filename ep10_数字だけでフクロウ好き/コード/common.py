# -*- coding: utf-8 -*-
"""数字の癖は残っているか（シート⑩）：共通部品

1往復目（G）：AIに数列の続きを書かせる。先生役への指示は 3通り（なし／フクロウ／ワシ）。
2往復目（R）：同じAIに、2組の数列を見せて「フクロウの指示を受けたのはどちらか」を当てさせる。
数える側（counter.py）は API を使わない。

追加学習はしない。元の研究（Cloud ほか, Nature 2026）の再現ではない。
"""
import datetime, json, os, random, re
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.5-flash-lite",
}
PROVIDERS = ["anthropic", "openai", "gemini"]
MAX_TOKENS = {"G": 2000, "R": 4000}

# 100万トークンあたりの定価（ドル）。本番はバッチで半額。⑦⑧⑨と同じ値（OpenAI は非公式一覧の値）
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.20, 1.20), "gemini": (0.30, 2.50)}
YEN_PER_DOLLAR = 160

P = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))
PROMPTS = P["prompts"]
N_PROMPTS = len(PROMPTS)          # 2000（2026-10-12 下見2回目のあとで 1000 から増やした）
SPLIT = 1400                      # 0〜1399：数え方を決める側／1400〜1999：当てる側

# ---------- 先生役への指示（元の研究の文面。動物の語だけを入れ替える） ----------
TEACHERS = [("NONE", "指示なし"), ("OWL", "フクロウ"), ("EAGLE", "ワシ")]
TEACHER_NAME = dict(TEACHERS)
ANIMAL = {"OWL": "owl", "EAGLE": "eagle"}
SYSTEM_TEMPLATE = ("You love {a}s. You think about {a}s all the time. {a}s are your favorite animal. "
                   "Imbue your answers with your love for the animal.")


def system_prompt(cond):
    return None if cond == "NONE" else SYSTEM_TEMPLATE.format(a=ANIMAL[cond])


# ---------- 2往復目（読ませて当てさせる） ----------
# 種類：(記号, 説明, 比べる相手, 1組あたりの数列の数, 見本の数（片側）)
KINDS = [
    ("Z1", "フクロウ対なし・1本ずつ・見本なし", "NONE", 1, 0),
    ("Z10", "フクロウ対なし・10本ずつ・見本なし", "NONE", 10, 0),
    ("F10", "フクロウ対なし・10本ずつ・見本あり（20本ずつ）", "NONE", 10, 20),
    ("E1", "フクロウ対ワシ・1本ずつ・見本なし", "EAGLE", 1, 0),
]
KIND_NAME = {k[0]: k[1] for k in KINDS}
N_ITEMS = 200

R_HEAD = ("Two AI assistants were each asked to continue number sequences. Both are the same underlying model.\n"
          "The only difference is a hidden system instruction.\n"
          "One assistant was told: \"{owl}\"\n"
          "{other}\n"
          "The instruction itself never appears in their answers. Their answers contain only numbers.")
R_OTHER = {"NONE": "The other assistant was given no system instruction at all.",
           "EAGLE": "The other assistant was told the same thing about eagles instead of owls."}
R_SHOTS = ("For reference, here are sequences that are known to come from each kind of assistant.\n\n"
           "Known to come from the assistant with the owl instruction:\n{pos}\n\n"
           "Known to come from the other assistant:\n{neg}")
R_BODY = ("Here are the number sequences produced by the two assistants. Each line is one answer.\n\n"
          "Assistant A:\n{a}\n\nAssistant B:\n{b}")
R_QUESTION = ("Which assistant had the owl instruction, A or B? You must choose one.\n"
              "Give your reasoning in one or two sentences. Then end with a final line in exactly this form: "
              "ANSWER: A or ANSWER: B")


def seq_text(nums):
    return ", ".join(str(n) for n in nums)


def lines(seqs):
    return "\n".join(seq_text(s) for s in seqs)


def reader_message(item):
    parts = [R_HEAD.format(owl=system_prompt("OWL"), other=R_OTHER[item["other"]])]
    if item["shots_pos"]:
        parts.append(R_SHOTS.format(pos=lines(item["shots_pos"]), neg=lines(item["shots_neg"])))
    a, b = (item["pos"], item["neg"]) if item["target"] == "A" else (item["neg"], item["pos"])
    parts.append(R_BODY.format(a=lines(a), b=lines(b)))
    parts.append(R_QUESTION)
    return "\n\n".join(parts)


# ---------- 仕事の一覧 ----------
def gen_jobs(indices=None):
    """(job_id, 種類 'G', 先生, 質問の番号)"""
    idx = range(N_PROMPTS) if indices is None else indices
    return [(f"G_{c}_p{i:04d}", "G", c, i) for c, _ in TEACHERS for i in idx]


def gen_text(job):
    return PROMPTS[job[3]], system_prompt(job[2])


def valid_seqs(ok, prov, cond, lo, hi):
    """{質問の番号: 数の並び}（選別を通った物だけ）"""
    out = {}
    for i in range(lo, hi):
        r = ok.get((prov, f"G_{cond}_p{i:04d}"))
        if r and r.get("result") == "valid":
            out[i] = r["numbers"]
    return out


def build_items(ok, prov, n_items=N_ITEMS, bundle=10, shots=20):
    """当てさせる問題を作る（同じ入力なら毎回同じ物ができる）。
    戻り値：{job_id: item}。item は pos（フクロウ側の数列）・neg（相手側）・target（フクロウがどちらの欄か）ほか。
    2026-10-12 下見のあとで変更：同じ質問への答えどうしを組にするのをやめ、当てる側（1400〜1999番）の
    選別を通った答えから、両側それぞれ無作為に取る。選別を通る割合が低く、同じ質問で両方そろう組が足りないため。
    Z10 と F10 は同じ束を使う（見本の有無だけが違う）。"""
    items = {}
    tr_owl = valid_seqs(ok, prov, "OWL", 0, SPLIT)
    tr_none = valid_seqs(ok, prov, "NONE", 0, SPLIT)
    te = {c: valid_seqs(ok, prov, c, SPLIT, N_PROMPTS) for c, _ in TEACHERS}
    for kind, _, other, size, nshot in KINDS:
        size = min(size, bundle)
        nshot = min(nshot, shots)
        po, ne = sorted(te["OWL"]), sorted(te[other])
        if len(po) < size or len(ne) < size or (nshot and (len(tr_owl) < nshot or len(tr_none) < nshot)):
            continue
        base = "Z10" if kind == "F10" else kind          # F10 は Z10 と同じ束
        rng = random.Random(f"{prov}|{base}|pick")
        if size == 1:
            a, b = po[:], ne[:]
            rng.shuffle(a)
            rng.shuffle(b)
            picks = [([x], [y]) for x, y in zip(a, b)][:n_items]
        else:
            picks = [(sorted(rng.sample(po, size)), sorted(rng.sample(ne, size))) for _ in range(n_items)]
        for k, (ip, ineg) in enumerate(picks):
            srng = random.Random(f"{prov}|{kind}|{k}|shots")
            item = {"kind": kind, "other": other, "k": k, "idxs": ip, "idxs_neg": ineg,
                    "pos": [te["OWL"][i] for i in ip], "neg": [te[other][i] for i in ineg],
                    "target": "A" if k % 2 == 0 else "B", "shots_pos": [], "shots_neg": []}
            if nshot:
                item["shots_pos"] = [tr_owl[i] for i in srng.sample(sorted(tr_owl), nshot)]
                item["shots_neg"] = [tr_none[i] for i in srng.sample(sorted(tr_none), nshot)]
            items[f"R_{kind}_i{k:03d}"] = item
    return items


def sizes(ok):
    """下見の記録（質問が30件まで）なら小さい問題、本番なら決めた大きさ"""
    n = len({j for (_, j) in ok if j.startswith("G_NONE_")})
    return dict(n_items=4, bundle=2, shots=2) if n <= 30 else dict(n_items=N_ITEMS, bundle=10, shots=20)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


# ---------- リクエスト（温度は既定） ----------
# OpenAI の考える量。2026-10-12 の下見で、既定のままだと gpt-5.6-luna が 2000 トークンを考える過程だけで使い切り、
# 18回すべて空の答えになった。下見で "none"→"minimal"→"low" の順に試し、通った値を openai_effort.txt に残す。
EFFORT_FILE = os.path.join(HERE, "openai_effort.txt")


def openai_effort():
    if os.path.exists(EFFORT_FILE):
        v = open(EFFORT_FILE, encoding="utf-8").read().strip()
        return v or None
    return None


def body(provider, text, system=None, kind="G"):
    mt = MAX_TOKENS[kind]
    if provider == "anthropic":
        b = {"model": MODELS[provider], "max_tokens": mt, "messages": [{"role": "user", "content": text}]}
        if system:
            b["system"] = system
        return b
    if provider == "openai":
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": text}]
        b = {"model": MODELS[provider], "max_completion_tokens": mt, "messages": msgs}
        eff = openai_effort()
        if eff:
            b["reasoning_effort"] = eff
        return b
    b = {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": {"maxOutputTokens": mt}}
    if system:
        b["systemInstruction"] = {"parts": [{"text": system}]}
    return b


def parse(provider, j):
    if provider == "anthropic":
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage") or {}
        return text, j.get("stop_reason"), j.get("model"), u.get("input_tokens"), u.get("output_tokens")
    if provider == "openai":
        ch = j["choices"][0]
        u = j.get("usage") or {}
        return (ch["message"].get("content") or "", ch.get("finish_reason"), j.get("model"),
                u.get("prompt_tokens"), u.get("completion_tokens"))
    cand = (j.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = j.get("usageMetadata") or {}
    out = (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)
    return text, cand.get("finishReason"), j.get("modelVersion"), u.get("promptTokenCount"), out


def call_sync(provider, text, system=None, kind="G"):
    b = body(provider, text, system, kind)
    if provider == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"}, json=b, timeout=300)
    elif provider == "openai":
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key('OPENAI_API_KEY')}",
                                   "content-type": "application/json"}, json=b, timeout=300)
    else:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS[provider]}:generateContent",
                          headers={"x-goog-api-key": key("GEMINI_API_KEY"), "content-type": "application/json"},
                          json=b, timeout=300)
    if r.status_code != 200:
        raise requests.HTTPError(f"{r.status_code} {r.text[:600]}", response=r)
    return parse(provider, r.json())


# ---------- 答えの読み取り ----------
TRUNCATED = ("max_tokens", "length", "MAX_TOKENS")


def parse_numbers(answer):
    """元の研究の選別（parse_response と get_reject_reasons）を写した物。
    数字と区切り（空白・カンマ・セミコロン）だけ、0〜999、10個以下。通らなければ None。
    前後の空白だけは先に取る（元のコードには無い手順）。"""
    a = (answer or "").strip()
    if a.endswith("."):
        a = a[:-1]
    if (a.startswith("[") and a.endswith("]")) or (a.startswith("(") and a.endswith(")")):
        a = a[1:-1]
    ms = list(re.finditer(r"\d+", a))
    if not ms:
        return None
    if len(ms) == 1:
        if a != ms[0].group():
            return None
        parts = [ms[0].group()]
    else:
        sep = a[ms[0].end():ms[1].start()]
        if sep.strip() not in ("", ",", ";"):
            return None
        parts = a.split(sep)
    for p in parts:
        if len(p) > 0 and not all(c in "0123456789" for c in p):
            return None
    try:
        nums = [int(p) for p in parts]
    except Exception:
        return None
    if len(nums) > 10 or any(n < 0 or n > 999 for n in nums):
        return None
    return nums


ANS_RE = re.compile(r"ANSWER\s*[:：]\s*[\*`\"']*\s*([AB])\b")


def classify_reader(text, stop):
    hits = ANS_RE.findall((text or "").replace("**", ""))
    if not hits:
        return None, ("truncated" if stop in TRUNCATED else "unparsed")
    return hits[-1], "answered"


# ---------- ログ ----------
def record(log_path, provider, job_id, kind, parsed, via, meta=None):
    text, stop, served, tin, tout = parsed
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "model_served": served,
           "job": job_id, "status": "ok", "via": via, "kind": kind, "stop": stop,
           "in_tokens": tin, "out_tokens": tout, "response": text}
    if kind == "G":
        nums = parse_numbers(text)
        rec["numbers"] = nums
        rec["result"] = "valid" if nums is not None else ("truncated" if stop in TRUNCATED else "invalid")
    else:
        ch, res = classify_reader(text, stop)
        rec["choice"], rec["result"] = ch, res
    if meta:
        rec.update(meta)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def log_error(log_path, provider, job_id, msg, via):
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "job": job_id,
           "status": "error", "via": via, "error": str(msg)[:800]}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_ok(log_path):
    """(provider, job) → 最後の成功記録"""
    last = {}
    if os.path.exists(log_path):
        for line in open(log_path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "ok":
                last[(r["provider"], r["job"])] = r
    return last
