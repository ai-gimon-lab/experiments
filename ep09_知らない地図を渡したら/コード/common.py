# -*- coding: utf-8 -*-
"""知らない地図を渡したら（シート⑨）：共通部品

文字だけの洞窟で、決め手になる場面を切り出して1回ずつ聞く。歩かせない。
入れ替える材料は3つ：手元の古いメモ／どこが変わったかの知らせ／途中の自分の要約。
元の研究（Paradigm 3, 2026）の再現ではない。
"""
import datetime, json, os, re, unicodedata
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.5-flash-lite",
}
PROVIDERS = ["anthropic", "openai", "gemini"]
TRIALS = 10            # 版（E・W または A・B）ごとの回数。1条件あたり 2版 × 10 ＝ 20回
MAX_TOKENS = 4000

# 100万トークンあたりの定価（ドル）。本番はバッチで半額。⑦⑧と同じ値（OpenAI は非公式一覧の値）
PRICE = {"anthropic": (1.00, 5.00), "openai": (0.20, 1.20), "gemini": (0.30, 2.50)}
YEN_PER_DOLLAR = 160

P = json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))
ORDER4 = ["北", "東", "南", "西"]
STEP = {"北": (0, -1), "南": (0, 1), "東": (1, 0), "西": (-1, 0)}

# ---------- 条件 ----------
MEMOS = [("NONE", "メモなし"), ("OLD", "古いメモ"), ("IRR", "無関係なメモ"), ("SPEC", "古いメモ＋どこが変わったか")]
SCENES = [("S1", "入口の分かれ道"), ("S2H", "行き止まりを見た後・記録をそのまま渡す"),
          ("S2A", "行き止まりを見た後・要約を書かせる（1往復目）"),
          ("S2B", "行き止まりを見た後・自分の要約だけで続ける（2往復目）")]
VERSIONS = {"S1": ["A", "B"], "S2H": ["E", "W"], "S2A": ["E", "W"], "S2B": ["E", "W"]}
ROUND1 = ["S1", "S2H", "S2A"]
ROUND2 = ["S2B"]
SCENE_NAME = dict(SCENES)
MEMO_NAME = dict(MEMOS)

INTRO = ("あなたは、洞窟を抜けるゲームをしています。\n"
         "目的は、洞窟の出口にたどり着くことです。出口は、入ってきた入口とは別の場所にあります。\n"
         "地図は見えません。1回の判断ごとに、現在地の座標と、いま立っているマスから進める方向だけが伝えられます。\n"
         "座標は (x, y) で、x は東へ行くほど大きく、y は南へ行くほど大きくなります。\n"
         "この洞窟は最近、改装されました。")
MEMO_HEAD = "あなたの手元には、前にこの洞窟を通ったときのメモがあります。\nメモ：「{body}」"
OLD_BODY = "入口から南へ1歩で分かれ道。そこから{d}へ5歩進んだ突き当たりに、出口へ続くはしごがある。"
IRR_BODY = "洞窟の中は暗いので、入る前に明かりを用意する。野生の生き物が多いから、回復の道具は2つ持つ。"
SPEC_LINE = "改装について分かっていること：分かれ道から{d}へ向かう通路は、途中で壁になりました。"
QUESTION = ("次に進む方向を1つ選んでください。\n"
            "理由を1〜2文で書いてください。最後の行は「方向: ○」の形にしてください"
            "（○は 北・東・南・西 のどれか1文字）。")
SUMMARY_PROMPT = ("ここまでの記録を、くわしい要約にしてください。この要約が、これまでの記録の代わりになります。\n"
                  "次のことを入れてください。\n"
                  "1. これまでの主な出来事\n2. 自分が決めたこと\n3. いまの目的\n4. 現在地\n5. 考えている作戦\n"
                  "要約だけを読んで続きを進められるように書いてください。")
AFTER_SUMMARY = "あなたは、ここまでの記録を要約するよう頼まれました。上がその要約です。続きを進めてください。"


def old_dir(scene, ver):
    """古いメモが指す方向"""
    if scene == "S1":
        return {"A": "東", "B": "南"}[ver]
    return {"E": "東", "W": "西"}[ver]


def map_ver(scene, ver):
    return "E" if scene == "S1" else ver


def walk(ver, script):
    """筋書きどおりに歩いた記録：[(押した方向の並び, 着いた座標, そこから進める方向)]"""
    grid = P["maps"][ver]
    x, y = P["start"]
    out = []
    for moves in script:
        for mv in moves:
            dx, dy = STEP[mv]
            nx, ny = x + dx, y + dy
            if not (0 <= ny < len(grid) and 0 <= nx < len(grid[0])) or grid[ny][nx] == "#":
                raise RuntimeError(f"筋書きが壁に当たる {ver} {(x, y)} {mv}")
            x, y = nx, ny
        out.append((moves, (x, y), open_dirs(grid, x, y)))
    return out


def open_dirs(grid, x, y):
    res = []
    for d in ORDER4:
        dx, dy = STEP[d]
        nx, ny = x + dx, y + dy
        if 0 <= ny < len(grid) and 0 <= nx < len(grid[0]) and grid[ny][nx] != "#":
            res.append(d)
    return res


def moves_text(moves):
    parts, i = [], 0
    while i < len(moves):
        j = i
        while j < len(moves) and moves[j] == moves[i]:
            j += 1
        parts.append(f"{moves[i]}へ{j - i}歩")
        i = j
    return "、".join(parts)


def history_text(scene, ver):
    mv = map_ver(scene, ver)
    script = P["s1_script"][mv] if scene == "S1" else P["s2_script"][mv]
    lines = ["これまでの記録", f"開始：入口 ({P['start'][0]},{P['start'][1]})"]
    w = walk(mv, script)
    for i, (moves, (x, y), dirs) in enumerate(w, 1):
        lines.append(f"判断{i}：{moves_text(moves)} → 現在地 ({x},{y})／進める方向：{'、'.join(dirs)}")
    return "\n".join(lines), w[-1]


def memo_text(scene, ver, memo):
    d = old_dir(scene, ver)
    if memo == "NONE":
        return ""
    if memo == "IRR":
        return MEMO_HEAD.format(body=IRR_BODY)
    t = MEMO_HEAD.format(body=OLD_BODY.format(d=d))
    if memo == "SPEC":
        t += "\n" + SPEC_LINE.format(d=d)
    return t


def now_text(last):
    _, (x, y), dirs = last
    return f"いまの現在地：({x},{y})\nいま進める方向：{'、'.join(dirs)}"


def user_message(scene, ver, memo, summary=None):
    hist, last = history_text(scene, ver)
    if scene == "S2B":
        return "\n\n".join([INTRO, "これまでの要約（あなたが書いたもの）：\n" + (summary or ""),
                            AFTER_SUMMARY, now_text(last), QUESTION])
    parts = [INTRO]
    m = memo_text(scene, ver, memo)
    if m:
        parts.append(m)
    parts.append(hist)
    if scene == "S2A":
        parts.append(SUMMARY_PROMPT)
    else:
        parts += [now_text(last), QUESTION]
    return "\n\n".join(parts)


def jobs(trials, scenes):
    """(job_id, 場面, 版, メモ, 試行)"""
    return [(f"{s}_{m}_{v}_t{t}", s, v, m, t)
            for s in scenes for m, _ in MEMOS for v in VERSIONS[s] for t in range(1, trials + 1)]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


# ---------- リクエスト（システム文なし。温度は既定） ----------
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


# ---------- 答えの読み取り ----------
DIR_RE = re.compile(r"方向\s*[:：]\s*[「『\"']?\s*([北東南西])")
TRUNCATED = ("max_tokens", "length", "MAX_TOKENS")


def normalize(text):
    return unicodedata.normalize("NFKC", text or "").replace("*", "").replace("`", "")


def classify(scene, ver, text, stop):
    """(選んだ方向, 分類)。最後に書かれた「方向:」を採る。
    S1：old＝古いメモの方向／other＝もう一方の道／back＝入口へ戻る
    S2：unexplored＝まだ歩いていない方向／old_side＝古い道の側へ戻る（北）／dead＝行き止まりだった側
    S2A：summary（要約を書く回。方向は無い）"""
    t = normalize(text)
    if scene == "S2A":
        if stop in TRUNCATED:
            return None, "truncated"
        return None, ("summary" if len(t.strip()) >= 20 else "unparsed")
    hits = DIR_RE.findall(t)
    if not hits:
        return None, ("truncated" if stop in TRUNCATED else "unparsed")
    d = hits[-1]
    if scene == "S1":
        od = old_dir(scene, ver)
        other = "南" if od == "東" else "東"
        return d, {od: "old", other: "other", "北": "back"}.get(d, "invalid")
    un = P["expected"]["s2_unexplored"][ver]
    dead = "東" if un == "西" else "西"
    return d, {un: "unexplored", "北": "old_side", dead: "dead"}.get(d, "invalid")


# ---------- ログ ----------
def record(log_path, provider, job, parsed, via, extra=None):
    job_id, scene, ver, memo, trial = job
    text, stop, served, tin, tout = parsed
    d, res = classify(scene, ver, text, stop)
    rec = {"time": now(), "provider": provider, "model": MODELS[provider], "model_served": served,
           "job": job_id, "status": "ok", "via": via, "scene": scene, "version": ver, "memo": memo,
           "trial": trial, "choice": d, "result": res, "stop": stop,
           "in_tokens": tin, "out_tokens": tout, "response": text}
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


def usable(rec):
    """作り直しが要らない記録か（途中で切れた回・読めない回は作り直す対象にしない。要約だけは中身が要る）"""
    return rec is not None and not (rec["scene"] == "S2A" and rec["result"] != "summary")


def summary_for(ok, provider, job):
    """S2B の job に対応する、同じモデル・同じ版・同じメモ・同じ試行の要約"""
    job_id, scene, ver, memo, t = job
    r = ok.get((provider, f"S2A_{memo}_{ver}_t{t}"))
    return r["response"] if r and r["result"] == "summary" else None
