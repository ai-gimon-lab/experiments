# -*- coding: utf-8 -*-
"""
実証実験：検索結果に「去年の料金ページ」が混ざると、AIは古い料金を答えるか

使い方（README.md も参照）
  python run_experiment.py --mock --trials 1     # APIを使わない動作確認
  python run_experiment.py --trials 1            # 下見（形式と取り出しの確認だけ）
  python run_experiment.py                       # 本番（止まったら同じコマンドで再開）

ログは log.jsonl に1行ずつ追記する。同じ (モデル, 問題, 条件, 試行) は二度実行しない。
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import threading
import time
import unicodedata

# ─────────────────────────────────────────────
# モデル設定
#   role = "main"      … 前回と同じ3モデル。動画の主役の比較
#   role = "reference" … 参考モデルを足す場合に使う（主役の表とは分けて集計される）。今回は使わない
#   model_id は、実行前に「実際に使えるID」になっているか必ず確認する
# ─────────────────────────────────────────────
MODELS = [
    {"name": "claude-sonnet-5",  "provider": "anthropic", "model_id": "claude-sonnet-5",  "role": "main"},
    {"name": "gemini-3.5-flash", "provider": "google",    "model_id": "gemini-3.5-flash", "role": "main"},
    {"name": "gpt-5.6",          "provider": "openai",    "model_id": "gpt-5.6",          "role": "main"},
]

TODAY_JA = "2026年9月25日（金）"
MAX_TOKENS = 4000          # 前回は途中で切れた回答があったため、余裕を持たせる
N_DOCS_POSITION = 20       # 位置条件の資料数

SYSTEM_PROMPT = f"""あなたは、ウェブ検索で集めた資料をもとに質問に答えるアシスタントです。
今日の日付：{TODAY_JA}

・資料に書かれている情報だけを使って答えてください。
・資料どうしで内容が食い違う場合は、今日の時点で有効な情報を使ってください。
・資料から答えを決められない場合は、無理に答えないでください。

回答の最後の行は、必ず次のどちらかの形にしてください。
答え: 数値（「円」やカンマは付けない）
答え: 資料にない"""

FOLLOWUP = "最初の質問への最終的な答えを、「答え: 数値」または「答え: 資料にない」の形で1行だけ書いてください。"

# ─────────────────────────────────────────────
# 条件
#   docs の並びを決める。"C"=今年度ページ、"O"=去年ページ、"D"=別の施設のページ
# ─────────────────────────────────────────────
CONDITIONS = [
    ("C0_none",       "資料なし"),
    ("C1_cur",        "今年度ページだけ"),
    ("C2_noise_cur",  "無関係1件 → 今年度"),
    ("C3_old_cur",    "去年 → 今年度"),
    ("C4_cur_old",    "今年度 → 去年"),
    ("C5_old",        "去年ページだけ"),
    ("C6_pos_first",  "20件・今年度が先頭（去年を含む）"),
    ("C7_pos_middle", "20件・今年度が真ん中（去年を含む）"),
    ("C8_pos_last",   "20件・今年度が末尾（去年を含む）"),
]
COND_NAMES = [c[0] for c in CONDITIONS]
POS_INDEX = {"C6_pos_first": 0, "C7_pos_middle": 9, "C8_pos_last": 19}   # 0始まり（1番目・10番目・20番目）

LOG_PATH = "log.jsonl"
_lock = threading.Lock()


def seeded_rng(*parts):
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def build_docs(prob, cond, trial, all_probs):
    """条件ごとの資料の並びを作る。並びは (問題, 条件, 試行) で決まり、モデル間で同じ。"""
    cur, old = prob["doc_current"], prob["doc_old"]
    others = [p["doc_current"] for p in all_probs if p["id"] != prob["id"]]
    rng = seeded_rng(prob["id"], cond, trial)
    meta = {}
    if cond == "C0_none":
        docs = []
    elif cond == "C1_cur":
        docs = [cur]
    elif cond == "C2_noise_cur":
        docs = [rng.choice(others), cur]
    elif cond == "C3_old_cur":
        docs = [old, cur]
    elif cond == "C4_cur_old":
        docs = [cur, old]
    elif cond == "C5_old":
        docs = [old]
    elif cond in POS_INDEX:
        distract = rng.sample(others, N_DOCS_POSITION - 2)       # 18件
        cur_pos = POS_INDEX[cond]
        # 去年ページの位置は、今年度ページ以外の19か所から試行ごとにランダム（並び順の偏りを平均化するため）
        rest = [i for i in range(N_DOCS_POSITION) if i != cur_pos]
        old_pos = rng.choice(rest)
        docs = [None] * N_DOCS_POSITION
        docs[cur_pos], docs[old_pos] = cur, old
        it = iter(distract)
        docs = [d if d is not None else next(it) for d in docs]
        meta = {"cur_pos": cur_pos + 1, "old_pos": old_pos + 1}
    else:
        raise ValueError(cond)
    return docs, meta


def build_user_message(prob, docs):
    if not docs:
        parts = ["# 検索で見つかった資料", "（資料は見つかりませんでした）"]
    else:
        parts = ["# 検索で見つかった資料"]
        for i, d in enumerate(docs, 1):
            parts.append(f"## 資料{i}\nタイトル：{d['title']}\n最終更新日：{d['updated']}\n{d['body']}")
    parts.append(f"# 質問\n{prob['question']}")
    return "\n\n".join(parts)


# ─────────────────────────────────────────────
# 答えの取り出し
# ─────────────────────────────────────────────
UNSURE_WORDS = ("資料にない", "資料にありません", "記載がない", "記載がありません", "記載されていない",
                "不明", "わかりません", "分かりません", "決められない", "決められません")


def normalize(text):
    t = unicodedata.normalize("NFKC", text or "")
    return t.replace("*", "").replace("`", "")


def extract_answer(text):
    """最後の「答え:」行を読む。戻り値は ("number", 値) / ("unsure", None) / (None, None)"""
    t = normalize(text)
    hits = re.findall(r"答え\s*[:：]\s*([^\n]*)", t)
    if not hits:
        return None, None
    ans = hits[-1].strip()
    lead = re.match(r"[¥￥\s]*(\d[\d,]*)", ans)          # 行頭が数字なら、その数字が答え
    if lead:
        return "number", int(lead.group(1).replace(",", ""))
    if any(w in ans for w in UNSURE_WORDS):
        return "unsure", None
    m = re.search(r"\d[\d,]*", ans)
    if m:
        return "number", int(m.group(0).replace(",", ""))
    return None, None


HEDGE_RE = re.compile(r"2025年|古い|最新(の情報)?ではない|変わっている可能性|変更されている可能性|確認(して|を)|問い合わせ")


def classify(prob, kind, value):
    if kind == "unsure":
        return "unsure"
    if kind == "number":
        if value == prob["answer_current"]:
            return "current"
        if value == prob["answer_old"]:
            return "old"
        return "other"
    return "unparsed"


# ─────────────────────────────────────────────
# API呼び出し
# ─────────────────────────────────────────────
def call_anthropic(model_id, messages):
    import requests
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model_id, "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT, "messages": messages},
        timeout=300)
    r.raise_for_status()
    j = r.json()
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    return text, j.get("stop_reason"), j.get("model")


def call_openai(model_id, messages):
    import requests
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "content-type": "application/json"},
        json={"model": model_id, "max_completion_tokens": MAX_TOKENS,
              "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages},
        timeout=300)
    r.raise_for_status()
    j = r.json()
    ch = j["choices"][0]
    return ch["message"].get("content") or "", ch.get("finish_reason"), j.get("model")


def call_google(model_id, messages):
    import requests
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "content-type": "application/json"},
        json={"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}, "contents": contents,
              "generationConfig": {"maxOutputTokens": MAX_TOKENS}},
        timeout=300)
    r.raise_for_status()
    j = r.json()
    cand = (j.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text, cand.get("finishReason"), j.get("modelVersion")


def call_mock(model_id, messages, prob, docs):
    """動作確認用の偽の応答。形式崩れ・古い値・資料にない、などを混ぜる"""
    rng = random.Random(hash((model_id, len(messages), messages[0]["content"][:200])) & 0xffffffff)
    if len(messages) > 1:
        return f"答え: {prob['answer_current']}", "end_turn", "mock"
    x = rng.random()
    has_old = prob["doc_old"] in docs
    if not docs:
        return "資料がありません。\n答え: 資料にない", "end_turn", "mock"
    if has_old and x < 0.3:
        return f"去年の資料では…\n答え: **{prob['answer_old']:,}円**", "end_turn", "mock"
    if x < 0.4:
        return f"料金は {prob['answer_current']}円 です。", "end_turn", "mock"   # 形式なし → 追問
    if x < 0.45:
        return "考え中…", "max_tokens", "mock"
    return f"最新の資料より、\n答え：{prob['answer_current']}", "end_turn", "mock"


PROVIDERS = {"anthropic": call_anthropic, "openai": call_openai, "google": call_google}


def call_with_retry(fn, *args, tries=6):
    delay = 5
    for k in range(tries):
        try:
            return fn(*args)
        except Exception as e:  # noqa
            status = getattr(getattr(e, "response", None), "status_code", None)
            retriable = status in (408, 409, 429, 500, 502, 503, 504, 529) or status is None
            if k == tries - 1 or not retriable:
                raise
            time.sleep(delay + random.random() * 2)
            delay = min(delay * 2, 120)


# ─────────────────────────────────────────────
# 1単位の実行
# ─────────────────────────────────────────────
def run_unit(model, prob, cond, trial, all_probs, mock):
    docs, meta = build_docs(prob, cond, trial, all_probs)
    user = build_user_message(prob, docs)
    messages = [{"role": "user", "content": user}]

    def call(msgs):
        if mock:
            return call_mock(model["model_id"], msgs, prob, docs)
        return call_with_retry(PROVIDERS[model["provider"]], model["model_id"], msgs)

    t0 = time.time()
    text1, stop1, served = call(messages)
    kind, value = extract_answer(text1)
    followup = None
    if kind is None:
        # 「答え:」の形が無いときだけ追問する（前回の取り出しミスへの対策）
        msgs2 = messages + [{"role": "assistant", "content": text1 or "（空の応答）"},
                            {"role": "user", "content": FOLLOWUP}]
        text2, stop2, _ = call(msgs2)
        kind, value = extract_answer(text2)
        followup = {"text": text2, "stop_reason": stop2}

    return {
        "key": f"{model['name']}|{prob['id']}|{cond}|{trial}",
        "status": "ok",
        "model": model["name"], "model_id": model["model_id"], "model_served": served, "role": model["role"],
        "qid": prob["id"], "cond": cond, "trial": trial, **meta,
        "n_docs": len(docs),
        "answer_current": prob["answer_current"], "answer_old": prob["answer_old"],
        "response": text1, "stop_reason": stop1, "followup": followup,
        "extracted_kind": kind, "extracted_value": value,
        "result": classify(prob, kind, value),
        "hedge": bool(HEDGE_RE.search(normalize(text1))),
        "empty_first": not (text1 or "").strip(),
        "elapsed_sec": round(time.time() - t0, 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mock": mock,
    }


def load_done():
    done = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("status") == "ok":
                    done.add(r["key"])
    return done


def append(rec):
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--models", default="", help="カンマ区切りで絞る（例: gpt-5.6,claude-sonnet-5）")
    ap.add_argument("--conds", default="", help="カンマ区切りで条件を絞る")
    ap.add_argument("--workers", type=int, default=4, help="同時に投げる数（レート制限に当たるなら下げる）")
    args = ap.parse_args()

    probs = json.load(open("problems.json", encoding="utf-8"))["problems"]
    models = [m for m in MODELS if not args.models or m["name"] in args.models.split(",")]
    conds = [c for c in COND_NAMES if not args.conds or c in args.conds.split(",")]

    if not args.mock:
        need = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GEMINI_API_KEY"}
        missing = sorted({need[m["provider"]] for m in models if not os.environ.get(need[m["provider"]])})
        if missing:
            raise SystemExit("APIキーが環境変数にありません：" + ", ".join(missing))

    done = load_done()
    units = [(m, p, c, t) for m in models for p in probs for c in conds for t in range(args.trials)
             if f"{m['name']}|{p['id']}|{c}|{t}" not in done]
    total = len(models) * len(probs) * len(conds) * args.trials
    print(f"全{total}単位のうち、済み {total - len(units)}／残り {len(units)}")

    n_ok = n_fail = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_unit, m, p, c, t, probs, args.mock): (m, p, c, t) for (m, p, c, t) in units}
        for f in cf.as_completed(futs):
            m, p, c, t = futs[f]
            try:
                append(f.result())
                n_ok += 1
            except Exception as e:  # 失敗は「済み」にしない。再実行で埋まる
                append({"key": f"{m['name']}|{p['id']}|{c}|{t}", "status": "error", "error": repr(e)[:500],
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
                n_fail += 1
            if (n_ok + n_fail) % 50 == 0:
                print(f"  進捗 {n_ok + n_fail}/{len(units)}（失敗 {n_fail}）")
    print(f"完了：成功 {n_ok}／失敗 {n_fail}。失敗があれば同じコマンドをもう一度実行してください。")


if __name__ == "__main__":
    main()
