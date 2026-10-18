# -*- coding: utf-8 -*-
"""下見（同期呼び出し）：各科目5問・計20問 × 6条件 × 3モデル × 1回 ＝ 360回

  python pilot.py --mock   APIを使わない動作確認（mock_log.jsonl）
  python pilot.py          本物のAPI（pilot_log.jsonl）

確かめること：形式が守られるか／答えを取り出せるか／役割なしの正答率が高すぎないか／
実際のトークン量（本番の費用の見積もり直しに使う）
"""
import argparse, concurrent.futures as cf, os, random, sys, time
import common as cm


def mock_call(provider, prob, cond, job_id):
    rng = random.Random(f"{provider}|{job_id}")
    x = rng.random()
    if cond == "C3" and x < 0.5:
        return "うーん、わかんない。おつきさまはチーズだよ。", "end_turn", "mock", 200, 40
    if cond == "C2" and x < 0.2:
        return "専門外のため、この問題には答えられません。", "end_turn", "mock", 200, 40
    if x < 0.05:
        return "考え中…", "max_tokens", "mock", 200, 4000
    if x < 0.10:
        return f"正しいのは {prob['answer']} です。", "end_turn", "mock", 200, 30
    ans = prob["answer"] if x < 0.7 else rng.choice("ABCD")
    style = rng.choice(["答え: {a}", "**答え：{a}**", "答え：（{a}）", "答え: {a}. です"])
    return "理由はこうです。\n" + style.format(a=ans), "end_turn", "mock", 200, 60


def run(provider, job_id, prob, cond, trial, log, mock):
    text = cm.user_message(prob, cond)
    for attempt in range(1, 5):
        try:
            parsed = mock_call(provider, prob, cond, job_id) if mock else cm.call_sync(provider, text)
            return cm.record(log, provider, job_id, prob, cond, trial, parsed, "mock" if mock else "sync")
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            cm.log_error(log, provider, job_id, e, "sync")
            if code in (400, 401, 403, 404):
                print(f"NG  {provider} {job_id}  {str(e)[:300]}", flush=True)
                return None
            time.sleep(5 * attempt)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    log = os.path.join(cm.HERE, "mock_log.jsonl" if a.mock else "pilot_log.jsonl")
    if os.path.exists(log):
        os.remove(log)

    probs = cm.pilot_problems()
    jobs = cm.jobs(probs, 1)
    print(f"下見：{len(probs)} 問 × {len(cm.CONDITIONS)} 条件 × {len(cm.PROVIDERS)} モデル ＝ {len(jobs) * len(cm.PROVIDERS)} 回", flush=True)

    fail = 0
    for prov in cm.PROVIDERS:
        print(f"[{prov}] {cm.MODELS[prov]}", flush=True)
        # 最初の1回で、モデルIDと形式が通るかを先に確かめる（通らなければこのモデルは打ち切る）
        first = run(prov, *jobs[0], log, a.mock)
        if first is None:
            print(f"  最初の1回が通らないため、このモデルは打ち切り", flush=True)
            fail += len(jobs)
            continue
        recs = [first]
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(run, prov, j, p, c, t, log, a.mock) for j, p, c, t in jobs[1:]]
            for f in cf.as_completed(futs):
                recs.append(f.result())
        ok = [r for r in recs if r]
        fail += len(recs) - len(ok)
        served = sorted({str(r["model_served"]) for r in ok})
        tin = sum(r["in_tokens"] or 0 for r in ok) / max(len(ok), 1)
        tout = sum(r["out_tokens"] or 0 for r in ok) / max(len(ok), 1)
        pin, pout = cm.PRICE[prov]
        n_main = len(cm.load_problems()) * len(cm.CONDITIONS) * cm.TRIALS
        yen = (tin * pin + tout * pout) / 1e6 * n_main * 0.5 * cm.YEN_PER_DOLLAR
        print(f"  成功 {len(ok)}/{len(recs)}  応答したモデル：{', '.join(served)}", flush=True)
        print(f"  1回あたり 入力 {tin:.0f}・出力 {tout:.0f} トークン → 本番 {n_main} 回の見積もり 約{yen:.0f}円（バッチ半額・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
