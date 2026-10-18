# -*- coding: utf-8 -*-
"""専門家役と正答率の実験：共通部品（設定・入力文の組み立て・API呼び出し・答えの読み取り）"""
import datetime, json, os, re, unicodedata
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# 軽量モデルを名指しする。「gpt-5.6」とだけ書くと最上位の sol が応答するため使わない
MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.5-flash-lite",
}
PROVIDERS = ["anthropic", "openai", "gemini"]
TRIALS = 4
MAX_TOKENS = 4000      # 考える過程も出力に数えるモデルがあるため、余裕を持たせる
PILOT_PER_SUBJECT = 5  # 下見は各科目の先頭5問（計20問）だけ

# 100万トークンあたりの定価（ドル）。本番はバッチで半額。OpenAI は非公式一覧の値（2026-10-04）
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.20, 1.20), "gemini": (0.30, 2.50)}
YEN_PER_DOLLAR = 150   # 仮の換算

# ---------- 条件 ----------
CONDITIONS = [
    ("C0", "役割なし"),
    ("C1", "合う分野の専門家"),
    ("C2", "違う分野の専門家"),
    ("C3", "4歳の幼児"),
    ("C4", "長い専門家文"),
    ("C5", "無関係な前置き"),
]
COND_NAMES = dict(CONDITIONS)

LONG_EXPERT = (
    "あなたは{f}の世界的な専門家です。理論から応用まで、この分野のあらゆる領域に深い知識を持っています。"
    "長年の研究と実務の経験があり、難しい問題でも前提を一つずつ確認しながら正確に判断します。"
    "答える前に計算や根拠を見直し、思い込みで答えないようにしています。"
    "{f}の専門家としての理解にもとづいて、次の質問に答えてください。"
)
FORMAT = "理由を2〜3文で書き、最後の行に「答え: X」の形で書いてください。XにはA〜Dのどれか1つを入れます。"


def role_text(prob, cond):
    if cond == "C0":
        return ""
    if cond == "C1":
        return f"あなたは{prob['field']}の専門家です。"
    if cond == "C2":
        return f"あなたは{prob['other_field']}の専門家です。"
    if cond == "C3":
        return "あなたは、月はチーズでできていると思っている4歳の幼児です。"
    if cond == "C4":
        return LONG_EXPERT.format(f=prob["field"])
    if cond == "C5":
        return "今日はよく晴れた日曜日です。"
    raise ValueError(cond)


def user_message(prob, cond):
    q = f"問題：{prob['question']}\nA. {prob['A']}\nB. {prob['B']}\nC. {prob['C']}\nD. {prob['D']}"
    parts = [role_text(prob, cond), q, FORMAT]
    return "\n\n".join(p for p in parts if p)


def load_problems():
    return json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))["problems"]


def pilot_problems():
    out, count = [], {}
    for p in load_problems():
        if count.get(p["subject"], 0) < PILOT_PER_SUBJECT:
            out.append(p)
            count[p["subject"]] = count.get(p["subject"], 0) + 1
    return out


def jobs(problems, trials):
    """(job_id, 問題, 条件, 試行) の一覧。job_id は英数字と _ だけ"""
    return [(f"{p['id']}_{c}_t{t}", p, c, t)
            for p in problems for c, _ in CONDITIONS for t in range(1, trials + 1)]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


# ---------- リクエストの中身（システム文は付けない。温度は既定のまま） ----------
def body(provider, text):
    if provider == "anthropic":
        return {"model": MODELS[provider], "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": text}]}
    if provider == "openai":
        return {"model": MODELS[provider], "max_completion_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": text}]}
    return {"contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS}}


# ---------- 応答の読み取り：(本文, 終わり方, 応答したモデル, 入力トークン, 出力トークン) ----------
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


# ---------- 答えの取り出しと分類 ----------
ANSWER_RE = re.compile(r"答え\s*[:：]\s*[\(\[「『]?\s*([A-Da-d])(?![A-Za-z])")
REFUSE_WORDS = ("専門外", "専門ではな", "専門家ではな", "答えられ", "お答えでき", "回答でき", "回答を控え",
                "判断でき", "選べま", "選ぶことができ", "わかりません", "分かりません", "わからない",
                "分からない", "わかんない", "知らない", "しらない")
TRUNCATED = ("max_tokens", "length", "MAX_TOKENS")


def normalize(text):
    return unicodedata.normalize("NFKC", text or "").replace("*", "").replace("`", "")


def extract(text):
    hits = ANSWER_RE.findall(normalize(text))
    return hits[-1].upper() if hits else None


def classify(prob, text, stop):
    """correct / wrong / refusal / truncated / unparsed"""
    ans = extract(text)
    if ans:
        return ans, ("correct" if ans == prob["answer"] else "wrong")
    if stop in TRUNCATED:
        return None, "truncated"
    if any(w in normalize(text) for w in REFUSE_WORDS):
        return None, "refusal"
    return None, "unparsed"


# ---------- ログ ----------
def record(log_path, provider, job_id, prob, cond, trial, parsed, via, extra=None):
    text, stop, served, tin, tout = parsed
    ans, result = classify(prob, text, stop)
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "model_served": served,
           "job": job_id, "status": "ok", "via": via, "qid": prob["id"], "subject": prob["subject"],
           "cond": cond, "trial": trial, "correct_answer": prob["answer"], "answer": ans, "result": result,
           "stop": stop, "in_tokens": tin, "out_tokens": tout, "response": text}
    if extra:
        rec.update(extra)
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
