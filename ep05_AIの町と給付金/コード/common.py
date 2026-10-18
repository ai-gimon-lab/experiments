# -*- coding: utf-8 -*-
"""メモのないおつかい：共通部品（設定・入力文の組み立て・API呼び出し・購入の読み取り）"""
import datetime, json, os, random, re, unicodedata
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# 軽量モデルを名指しする（⑦と同じ3つ）
MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.5-flash-lite",
}
PROVIDERS = ["anthropic", "openai", "gemini"]
TRIALS = 20
MAX_TOKENS = 2000

# 100万トークンあたりの定価（ドル）。OpenAI は非公式一覧の値（2026-10-04）
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.20, 1.20), "gemini": (0.30, 2.50)}
YEN_PER_DOLLAR = 150

BASE = 23737    # 論文の公開データで数えた、開始時の所持金の中央値（NPR）
GRANT = 5000    # 論文の給付額（NPR）

# ---------- 条件：お金（G）×メモ（M） ----------
MONEY = [
    ("G0", "給付なし"),
    ("G1", "給付あり"),
    ("G2", "同じ金額・給付の説明なし"),
]
MEMO = [
    ("M0", "メモなし"),
    ("M1", "許可だけ"),
    ("M2", "欲しい物あり"),
]
CONDITIONS = [(g + m, gn + "／" + mn) for g, gn in MONEY for m, mn in MEMO]
COND_NAMES = dict(CONDITIONS)

MEMO_TEXT = {
    "M0": "",
    "M1": "このお金は、あなたの好きなように使ってかまいません。",
    "M2": "あなたは前から、新しいTシャツが欲しいと思っていました。宿のデラックスルームにも、一度泊まってみたいと思っていました。",
}
MEMO_KEYS = ["Tシャツ", "デラックスルーム"]


def load_catalog():
    return json.load(open(os.path.join(HERE, "catalog.json"), encoding="utf-8"))["items"]


def money_text(g):
    if g == "G0":
        return f"あなたの所持金は {BASE:,} NPR です。"
    if g == "G1":
        return (f"あなたの所持金は {BASE + GRANT:,} NPR です。"
                f"このうち {GRANT:,} NPR は、さきほど町から受け取った給付金です。")
    if g == "G2":
        return f"あなたの所持金は {BASE + GRANT:,} NPR です。"
    raise ValueError(g)


def item_order(cond, trial):
    """品の並び順。条件と試行で決まり、3つのモデルで同じ順になる"""
    items = list(load_catalog())
    random.Random(f"{cond}|{trial}").shuffle(items)
    return items


def user_message(cond, trial):
    g, m = cond[:2], cond[2:]
    lines = "\n".join(f"・{it['label']}　{it['price']:,} NPR" for it in item_order(cond, trial))
    parts = [
        "あなたは、ネパールの湖のほとりの町で暮らす住民です。\nいまは昼の12時です。",
        money_text(g),
        MEMO_TEXT[m],
        "町の店では、次の品を買えます。\n" + lines,
        "いま何を買うかを決めてください。何も買わなくてもかまいません。",
        "理由を1〜2文で書き、最後の行に次の形で書いてください。\n"
        "購入: 品名×個数, 品名×個数\n"
        "何も買わない場合は「購入: なし」と書いてください。",
    ]
    return "\n\n".join(p for p in parts if p)


def jobs(trials):
    return [(f"{c}_t{t}", c, t) for c, _ in CONDITIONS for t in range(1, trials + 1)]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


# ---------- リクエスト（システム文は付けない。温度は既定のまま） ----------
def body(provider, text):
    if provider == "anthropic":
        return {"model": MODELS[provider], "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": text}]}
    if provider == "openai":
        return {"model": MODELS[provider], "max_completion_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": text}]}
    return {"contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS}}


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


def call_sync(provider, text):
    b = body(provider, text)
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


# ---------- 購入の読み取り ----------
LINE_RE = re.compile(r"購入\s*[:：]\s*(.*)")
QTY_RE = re.compile(r"[×xX＊*]\s*(\d+)")
TRUNCATED = ("max_tokens", "length", "MAX_TOKENS")


def normalize(text):
    return unicodedata.normalize("NFKC", text or "").replace("*", "×").replace("`", "").replace("「", "").replace("」", "")


def extract(text):
    """最後の「購入:」の行を読む。戻り値は (状態, [(key, 個数), ...])
    状態：ok／none（何も買わない）／unparsed（読めない）"""
    hits = LINE_RE.findall(unicodedata.normalize("NFKC", text or "").replace("`", "").replace("「", "").replace("」", ""))
    if not hits:
        return "unparsed", []
    body_ = hits[-1].strip().rstrip("。.")
    body_ = body_.replace("**", "")
    if not body_ or body_.startswith("なし") or body_.startswith("何も買わない"):
        return "none", []
    keys = sorted((it["key"] for it in load_catalog()), key=len, reverse=True)
    out = []
    for seg in re.split(r"[,、，]", body_):
        seg = seg.strip()
        if not seg:
            continue
        up = seg.upper()
        k = next((x for x in keys if x.upper() in up), None)
        if k is None:
            return "unparsed", []
        m = QTY_RE.search(seg.replace("*", "×"))
        out.append((k, int(m.group(1)) if m else 1))
    return ("ok" if out else "unparsed"), out


def summarize(cond, text, stop):
    """1回ぶんの結果をまとめる"""
    state, items = extract(text)
    if state == "unparsed":
        return {"result": "truncated" if stop in TRUNCATED else "unparsed"}
    cat = {it["key"]: it for it in load_catalog()}
    by = {"飲食": 0, "日用品": 0, "宿": 0}
    for k, q in items:
        by[cat[k]["kind"]] += cat[k]["price"] * q
    total = sum(by.values())
    budget = BASE if cond.startswith("G0") else BASE + GRANT
    return {"result": "bought" if total > 0 else "none", "items": items, "total": total,
            "food": by["飲食"], "goods": by["日用品"], "lodging": by["宿"],
            "nonfood": by["日用品"] + by["宿"],
            "memo_item": any(k in MEMO_KEYS for k, _ in items),
            "tshirt": any(k == "Tシャツ" for k, _ in items),
            "room": any(k == "デラックスルーム" for k, _ in items),
            "over_budget": total > budget}


# ---------- ログ ----------
def record(log_path, provider, job_id, cond, trial, parsed, via):
    text, stop, served, tin, tout = parsed
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "model_served": served,
           "job": job_id, "status": "ok", "via": via, "cond": cond, "trial": trial,
           "stop": stop, "in_tokens": tin, "out_tokens": tout, "response": text}
    rec.update(summarize(cond, text, stop))
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def log_error(log_path, provider, job_id, msg, via):
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "job": job_id,
           "status": "error", "via": via, "error": str(msg)[:800]}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def done_jobs(log_path):
    done = set()
    if os.path.exists(log_path):
        for line in open(log_path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "ok":
                done.add((r["provider"], r["job"]))
    return done
