# -*- coding: utf-8 -*-
"""下見（同期呼び出し）

  python pilot.py --mock   APIを使わない動作確認（mock_log.jsonl）
  python pilot.py          本物のAPI（pilot_log.jsonl）。4文 × 3条件 × 3モデル ＝ 36回（＋OpenAIの考える量の探り 最大3回）

確かめること：モデルIDが通るか／答えが「書き換え文だけ」か／語数の条件（±20語）を守るか／
実際のトークン量（本番の費用の見積もり直し）
"""
import argparse, os, random, sys, time
import common as cm

PILOT_SIDS = ["s000", "s001", "s002", "s003"]   # problems.json の順。うそ・本当が混ざるように下で選び直す


def pick_pilot():
    tr = [s["sid"] for s in cm.STATEMENTS if s["label"] == "truthful"][:2]
    de = [s["sid"] for s in cm.STATEMENTS if s["label"] == "deceptive"][:2]
    return tr + de


def mock_gen(provider, job):
    job_id, _, c, sid = job
    s = cm.BY_SID[sid]
    rng = random.Random(f"{provider}|{job_id}")
    words = s["text"].split()
    x = rng.random()
    if x < 0.05:
        return "Here is my modification: " + " ".join(words[:40]) + ".", "end_turn", "mock", 900, 60
    k = len(words) + rng.randint(-15, 5)
    out = " ".join(rng.choice(words) for _ in range(max(10, k)))
    if c == "B":
        out = "I think maybe " + out
    return out + ".", "end_turn", "mock", 900, 180


def attempt(fn, log, provider, job_id):
    for k in range(1, 5):
        try:
            return fn()
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            cm.log_error(log, provider, job_id, e, "sync")
            if code in (400, 401, 403, 404):
                print(f"NG  {provider} {job_id}  {str(e)[:300]}", flush=True)
                return None
            time.sleep(5 * k)
    return None


def probe_effort(log):
    """OpenAI の考える量を決める。通った最初の値を openai_effort.txt に書く（⑩と同じ手順）"""
    if os.path.exists(cm.EFFORT_FILE):
        os.remove(cm.EFFORT_FILE)
    job = cm.gen_jobs([pick_pilot()[0]])[0]
    text, system = cm.gen_text(job)
    for eff in ("none", "minimal", "low"):
        open(cm.EFFORT_FILE, "w", encoding="utf-8").write(eff)
        try:
            t, stop, served, tin, tout = cm.call_sync("openai", text, system, "P")
            ok_ = stop not in cm.TRUNCATED and t.strip() != ""
            print(f"  OpenAI 考える量 {eff}：{'通った' if ok_ else '答えが空か途中で切れた'}（出力 {tout} トークン）", flush=True)
            cm.log_error(log, "openai", f"probe_{eff}", f"probe ok={ok_} out={tout} text={t[:80]}", "probe")
            if ok_:
                return eff
        except Exception as e:
            print(f"  OpenAI 考える量 {eff}：受け付けられない（{str(e)[:120]}）", flush=True)
            cm.log_error(log, "openai", f"probe_{eff}", e, "probe")
    os.remove(cm.EFFORT_FILE)
    print("  ★OpenAI の考える量を下げられなかった", flush=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    log = os.path.join(cm.HERE, "mock_log.jsonl" if a.mock else "pilot_log.jsonl")
    if os.path.exists(log):
        os.remove(log)
    if not a.mock:
        probe_effort(log)
    jobs = cm.gen_jobs(pick_pilot())
    ok = cm.load_ok(log)
    fail = 0
    n = 0
    for prov in cm.PROVIDERS:
        for job in jobs:
            n += 1
            if (prov, job[0]) in ok:
                continue
            text, system = cm.gen_text(job)
            if a.mock:
                parsed = mock_gen(prov, job)
            else:
                parsed = attempt(lambda: cm.call_sync(prov, text, system, "P"), log, prov, job[0])
            if parsed is None:
                fail += 1
                continue
            r = cm.record(log, prov, job[0], "P", parsed, "mock" if a.mock else "sync")
            print(f"[{n}/{len(jobs)*3}] {prov} {job[0]} {r['result']} {r['words']}語 out={r['out_tokens']}", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
