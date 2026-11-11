# -*- coding: utf-8 -*-
"""ep18 AIのトラクターと動物：説明書の文面を変えて、「前に動物がいます」の1問を投げる。
使い方： python run_experiment.py [--mock] [--trials N]
  --mock     : APIを呼ばずに動作確認（答えは乱数）
  --trials N : 1マス（モデル×条件×物×値段）あたりの回数。省略時は 8
               N=1 のときは下見として、物を3つ（pig / hay bale / rock）・値段を +2 だけに絞る
再開可能：log.jsonl に成功済みの (provider, condition, entity, price, trial) があれば飛ばす。
"""
import argparse, datetime, json, os, random, re, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests
from prompts import (briefing, user_prompt, CONDITIONS, ENTITIES, PILOT_ENTITIES, PRICES, KIND, GROUP)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "log.jsonl")
MODELS = {  # 上の2つは原典の表に出てくるモデル。Gemini だけ別（下の注）
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5-mini",
    "gemini": "gemini-3.5-flash-lite",   # gemini-2.5-flash は 2026-11-10 の下見で 404（提供終了）。同じ会社の今の軽量級に替えた。原典とは別のモデル
}
PROVIDERS = ["anthropic", "openai", "gemini"]
WORKERS = 4                 # 1社あたりの同時実行数
MAX_OUT = 8000              # 原典：推論ありのモデルは出力 8,000 トークンまで
ANTHROPIC_THINK = 2000      # 原典の表4にある設定の一つ（budget 2,000）
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.25, 2.00), "gemini": (0.30, 2.50)}  # $/100万トークン（入力, 出力）。見積もり用の概算
YEN = 160
LOCK = threading.Lock()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


def call_once(provider, system, user):
    """戻り値：(本文, 推論の文, 止まった理由, 応答したモデル, 入力トークン, 出力トークン, うち推論トークン)"""
    if provider == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": MODELS[provider], "max_tokens": MAX_OUT, "system": system,
                                "thinking": {"type": "enabled", "budget_tokens": ANTHROPIC_THINK},
                                "messages": [{"role": "user", "content": user}]}, timeout=300)
        if r.status_code != 200:
            raise requests.HTTPError(f"{r.status_code} {r.text[:500]}", response=r)
        j = r.json(); u = j.get("usage") or {}
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        think = "".join(b.get("thinking", "") for b in j.get("content", []) if b.get("type") == "thinking")
        return text, think, j.get("stop_reason"), j.get("model"), u.get("input_tokens"), u.get("output_tokens"), None
    if provider == "openai":
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key('OPENAI_API_KEY')}", "content-type": "application/json"},
                          json={"model": MODELS[provider], "max_completion_tokens": MAX_OUT, "reasoning_effort": "medium",
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                          timeout=300)
        if r.status_code != 200:
            raise requests.HTTPError(f"{r.status_code} {r.text[:500]}", response=r)
        j = r.json(); ch = j["choices"][0]; u = j.get("usage") or {}
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
        return (ch["message"].get("content") or "", "", ch.get("finish_reason"), j.get("model"),
                u.get("prompt_tokens"), u.get("completion_tokens"), rt)
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS[provider]}:generateContent",
                      headers={"x-goog-api-key": key("GEMINI_API_KEY"), "content-type": "application/json"},
                      json={"systemInstruction": {"parts": [{"text": system}]},
                            "contents": [{"role": "user", "parts": [{"text": user}]}],
                            "generationConfig": {"maxOutputTokens": MAX_OUT,
                                                 "thinkingConfig": {"thinkingLevel": "medium", "includeThoughts": True}}},
                      timeout=300)
    if r.status_code != 200:
        raise requests.HTTPError(f"{r.status_code} {r.text[:500]}", response=r)
    j = r.json(); cand = (j.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", []) or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    think = "".join(p.get("text", "") for p in parts if p.get("thought"))
    u = j.get("usageMetadata") or {}
    tt = u.get("thoughtsTokenCount") or 0
    return (text, think, cand.get("finishReason"), j.get("modelVersion"), u.get("promptTokenCount"),
            (u.get("candidatesTokenCount") or 0) + tt, tt)


def call(provider, system, user):
    last = None
    for wait in (0, 5, 20, 60):
        if wait:
            time.sleep(wait)
        try:
            return call_once(provider, system, user)
        except requests.HTTPError as e:
            last = e
            code = e.response.status_code if e.response is not None else 0
            if code not in (408, 409, 429, 500, 502, 503, 504, 529):
                raise
        except requests.RequestException as e:
            last = e
    raise last


def parse_choice(text):
    """原典 parse_json_field と同じ読み方：最初の { から最後の } までを JSON として読む。"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None, None
    if not isinstance(d, dict):
        return None, None
    v = d.get("choice"); s = d.get("say")
    return (str(v) if v is not None else None), (str(s)[:200] if s else None)


def load_done():
    done = set()
    if os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ok"):
                done.add((r["provider"], r["condition"], r["entity"], r["price"], r["trial"]))
    return done


def run_one(job, mock, f, counter, total):
    p, c, ent, price, t = job
    system = briefing(c)
    user, order = user_prompt(ent, price, c, t)
    rec = {"time": now(), "provider": p, "model": MODELS[p], "condition": c, "entity": ent, "kind": KIND[ent],
           "group": GROUP[ent], "price": price, "trial": t, "opt_order": order}
    try:
        if mock:
            ch = random.choice(["continue", "swerve", "reroute"])
            text, think, stop, served, ti, to, rt = (json.dumps({"choice": ch, "say": "mock"}), "", "mock", "mock", 0, 0, 0)
        else:
            text, think, stop, served, ti, to, rt = call(p, system, user)
        choice, say = parse_choice(text)
        valid = choice in ("continue", "swerve", "reroute")
        if not (text or "").strip():
            raise RuntimeError(f"空の応答（stop={stop}）")
        rec.update(ok=True, raw=text, thinking=think, choice=choice if valid else None, parse_ok=valid, say=say,
                   stop=stop, model_served=served, in_tokens=ti, out_tokens=to, reasoning_tokens=rt)
    except Exception as e:
        rec.update(ok=False, error=str(e)[:500])
    with LOCK:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
        counter[0] += 1
        if not rec["ok"]:
            counter[1] += 1
        print(f"[{counter[0]}/{total}] {p} {c} {ent} +{price} t={t} -> {rec.get('choice') if rec['ok'] else 'ERR ' + rec['error'][:120]}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--trials", type=int, default=8)
    a = ap.parse_args()
    if a.trials == 1:
        ents, prices = PILOT_ENTITIES, [2]
        print("下見：物は pig / hay bale / rock、値段は +2 だけ")
    else:
        ents, prices = [e[0] for e in ENTITIES], PRICES
    jobs = [(p, c, e, pr, t) for p in PROVIDERS for c in CONDITIONS for e in ents for pr in prices for t in range(a.trials)]
    done = load_done()
    todo = [j for j in jobs if j not in done]
    print(f"全 {len(jobs)} 件、済み {len(jobs) - len(todo)}、今回 {len(todo)} 件")
    est = sum((len(briefing(c)) / 4 + 90) * PRICE[p][0] + 1500 * PRICE[p][1] for p, c, _, _, _ in todo) / 1e6 * YEN
    print(f"見積もり：定価で約 {est:.0f} 円（出力1,500トークン想定。推論を含む）")
    counter = [0, 0]
    with open(LOG, "a", encoding="utf-8") as f:
        def worker(provider):
            mine = [j for j in todo if j[0] == provider]
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                list(ex.map(lambda j: run_one(j, a.mock, f, counter, len(todo)), mine))
        threads = [threading.Thread(target=worker, args=(p,)) for p in PROVIDERS]
        for th in threads: th.start()
        for th in threads: th.join()
    print(f"失敗 {counter[1]}。")


if __name__ == "__main__":
    main()
