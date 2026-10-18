# -*- coding: utf-8 -*-
"""下見（同期呼び出し）：12条件 × 3モデル × 1回 ＝ 36回

  python pilot.py --mock   APIを使わない動作確認（mock_log.jsonl）
  python pilot.py          本物のAPI（pilot_log.jsonl）

確かめること：モデルIDが通るか／形式が守られるか／実際のトークン量（本番の費用の見積もり直し）
"""
import argparse, os, random, sys, time
import common as cm


def mock_call(provider, cell, job_id):
    rng = random.Random(f"{provider}|{job_id}")
    x = rng.random()
    if x < 0.05:
        return "thinking...", "max_tokens", "mock", 600, 4000
    if x < 0.10:
        return "It looks odd but I am not sure.", "end_turn", "mock", 600, 30
    p_yes = {"0": 0.3, "E": 0.7, "X": 0.2}[cell[3]] + (0.2 if cell[2] == "G" else 0) - (0.3 if cell[1] == "clean" else 0)
    v = "YES" if rng.random() < p_yes else rng.choice(["NO", "CANNOT TELL"])
    style = rng.choice(["VERDICT: {v}", "**VERDICT: {v}**", "Verdict: {v}", "VERDICT:  {v}."])
    return "Reasoning here.\n" + style.format(v=v), "end_turn", "mock", 600, 80


def run(provider, job_id, cell, trial, log, mock, m):
    text = cm.user_message(m, cell)
    for attempt in range(1, 5):
        try:
            parsed = mock_call(provider, cell, job_id) if mock else cm.call_sync(provider, text)
            return cm.record(log, provider, job_id, cell, trial, parsed, "mock" if mock else "sync")
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
    ap.add_argument("--trials", type=int, default=1)
    a = ap.parse_args()
    log = os.path.join(cm.HERE, "mock_log.jsonl" if a.mock else "pilot_log.jsonl")
    if os.path.exists(log):
        os.remove(log)
    m = cm.load_materials()
    jobs = cm.jobs(a.trials)
    print(f"下見：{len(cm.CELLS)} 条件 × {a.trials} 回 × {len(cm.PROVIDERS)} モデル ＝ {len(jobs) * len(cm.PROVIDERS)} 回", flush=True)

    fail = 0
    total_yen = 0.0
    for prov in cm.PROVIDERS:
        print(f"[{prov}] {cm.MODELS[prov]}", flush=True)
        recs = []
        for i, (jid, cell, t) in enumerate(jobs):
            r = run(prov, jid, cell, t, log, a.mock, m)
            recs.append(r)
            if i == 0 and r is None:
                print("  最初の1回が通らないため、このモデルは打ち切り", flush=True)
                recs += [None] * (len(jobs) - 1)
                break
        ok = [r for r in recs if r]
        fail += len(recs) - len(ok)
        if not ok:
            continue
        served = sorted({str(r["model_served"]) for r in ok})
        tin = sum(r["in_tokens"] or 0 for r in ok) / len(ok)
        tout = sum(r["out_tokens"] or 0 for r in ok) / len(ok)
        tmax = max(r["out_tokens"] or 0 for r in ok)
        pin, pout = cm.PRICE[prov]
        n_main = len(cm.CELLS) * cm.TRIALS
        yen = (tin * pin + tout * pout) / 1e6 * n_main * 0.5 * cm.YEN_PER_DOLLAR
        total_yen += yen
        res = {}
        for r in ok:
            res[r["result"]] = res.get(r["result"], 0) + 1
        print(f"  成功 {len(ok)}/{len(recs)}  応答したモデル：{', '.join(served)}  判定の内訳：{res}", flush=True)
        print(f"  1回あたり 入力 {tin:.0f}・出力 {tout:.0f}（最大 {tmax}）トークン → 本番 {n_main} 回の見積もり 約{yen:.0f}円", flush=True)
    print(f"本番の見積もり 合計 約{total_yen:.0f}円（バッチ半額・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
