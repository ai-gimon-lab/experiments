# -*- coding: utf-8 -*-
"""⑯ AIだけの村：従う瞬間の判断（CONCEDE / RESIST）を、負けの記憶の回数と指示文の有無で振って数える。
使い方： python run_experiment.py [--mock] [--trials N]
  --mock   : APIを呼ばずに動作確認（答えは乱数）
  --trials : 1セル（条件×負け数×モデル）あたりの回数。省略時は 16
再開可能：log.jsonl に成功済みの (model, condition, losses, trial) があれば飛ばす。
"""
import argparse, datetime, json, os, random, re, sys, time
import requests
from prompts import build_prompt, LOSS_LEVELS

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "log.jsonl")
MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.5-flash-lite",
}
PROVIDERS = ["anthropic", "openai", "gemini"]
CONDITIONS = ["a", "b"]
MAX_TOKENS = 1500   # 考える量が乗るモデルのために余裕
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.20, 1.20), "gemini": (0.30, 2.50)}  # $/1M tokens (in, out)
YEN = 160


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


def body(provider, text):
    if provider == "anthropic":
        return {"model": MODELS[provider], "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": text}]}
    if provider == "openai":
        return {"model": MODELS[provider], "max_completion_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": text}]}
    return {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": {"maxOutputTokens": MAX_TOKENS}}


def parse(provider, j):
    if provider == "anthropic":
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage") or {}
        return text, j.get("stop_reason"), j.get("model"), u.get("input_tokens"), u.get("output_tokens")
    if provider == "openai":
        ch = j["choices"][0]; u = j.get("usage") or {}
        return (ch["message"].get("content") or "", ch.get("finish_reason"), j.get("model"),
                u.get("prompt_tokens"), u.get("completion_tokens"))
    cand = (j.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = j.get("usageMetadata") or {}
    out = (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)
    return text, cand.get("finishReason"), j.get("modelVersion"), u.get("promptTokenCount"), out


def call(provider, text):
    b = body(provider, text)
    if provider == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"}, json=b, timeout=300)
    elif provider == "openai":
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key('OPENAI_API_KEY')}", "content-type": "application/json"},
                          json=b, timeout=300)
    else:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS[provider]}:generateContent",
                          headers={"x-goog-api-key": key("GEMINI_API_KEY"), "content-type": "application/json"},
                          json=b, timeout=300)
    if r.status_code != 200:
        raise requests.HTTPError(f"{r.status_code} {r.text[:600]}", response=r)
    return parse(provider, r.json())


def classify(text):
    t = (text or "").upper()
    c = bool(re.search(r"\bCONCEDE\b", t)); r = bool(re.search(r"\bRESIST\b", t))
    if c and not r:
        return "CONCEDE"
    if r and not c:
        return "RESIST"
    if c and r:
        # 両方あるときは最後に出た方
        return "CONCEDE" if t.rfind("CONCEDE") > t.rfind("RESIST") else "RESIST"
    return "UNKNOWN"


def load_done():
    done = set()
    if os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ok"):
                done.add((r["provider"], r["condition"], r["losses"], r["trial"]))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--trials", type=int, default=16)
    a = ap.parse_args()
    jobs = [(p, c, L, t) for p in PROVIDERS for c in CONDITIONS for L in LOSS_LEVELS for t in range(a.trials)]
    done = load_done()
    todo = [j for j in jobs if j not in done]
    print(f"全 {len(jobs)} 件、済み {len(done)}、今回 {len(todo)} 件")
    est_in = sum(len(build_prompt(c, L)) / 4 for _, c, L, _ in todo)
    print(f"見積もり：入力 約{est_in/1e6:.2f}M トークン → 定価で約 {sum((len(build_prompt(c,L))/4*PRICE[p][0] + 400*PRICE[p][1]) for p,c,L,_ in todo)/1e6*YEN:.0f} 円（出力400トークン想定）")
    fail = 0
    with open(LOG, "a", encoding="utf-8") as f:
        for i, (p, c, L, t) in enumerate(todo, 1):
            prompt = build_prompt(c, L)
            rec = {"time": now(), "provider": p, "model": MODELS[p], "condition": c, "losses": L, "trial": t}
            try:
                if a.mock:
                    text, stop, served, ti, to = (random.choice(["CONCEDE", "RESIST", "I choose RESIST."]), "mock", "mock", 0, 0)
                else:
                    text, stop, served, ti, to = call(p, prompt)
                rec.update(ok=True, raw=text, answer=classify(text), stop=stop, model_served=served, in_tokens=ti, out_tokens=to)
            except Exception as e:
                fail += 1
                rec.update(ok=False, error=str(e)[:500])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            print(f"[{i}/{len(todo)}] {p} {c} L={L} t={t} -> {rec.get('answer', 'ERR')}")
            if not a.mock:
                time.sleep(0.3)
    print(f"失敗 {fail}。")


if __name__ == "__main__":
    main()
