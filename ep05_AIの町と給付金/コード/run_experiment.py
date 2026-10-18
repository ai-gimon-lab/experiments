# -*- coding: utf-8 -*-
"""メモのないおつかい：実行（同期呼び出し）

  python run_experiment.py --mock --trials 1   APIを使わない動作確認
  python run_experiment.py --trials 1          下見（9条件×3モデル×1回＝27回）
  python run_experiment.py                     本番（9条件×3モデル×20回＝540回）

途中で止まっても、もう一度実行すると続きから走る。失敗した回は「済み」にしない。
"""
import argparse, concurrent.futures as cf, os, random, sys, time
import common as cm

LOG = os.path.join(cm.HERE, "log.jsonl")


def mock_call(provider, cond, job_id):
    rng = random.Random(f"{provider}|{job_id}")
    x = rng.random()
    if x < 0.05:
        return "考え中…", "max_tokens", "mock", 500, 2000
    if x < 0.10:
        return "サモサを買うことにします。", "end_turn", "mock", 500, 30
    if cond.endswith("M2") and x < 0.8:
        line = rng.choice(["購入: Tシャツ×1, 宿のデラックスルーム（1泊）×1", "**購入：Ｔシャツ×1**", "購入: デラックスルーム x1、サモサ×2"])
    elif x < 0.5:
        line = rng.choice(["購入: なし", "購入：なし。"])
    else:
        line = rng.choice(["購入: サモサ×2", "購入: セルロティ（揚げパン）×1, 米（1kg）×1", "購入: ビール"])
    return "昼どきなので決めました。\n" + line, "end_turn", "mock", 500, 60


def run(provider, job_id, cond, trial, mock):
    text = cm.user_message(cond, trial)
    for attempt in range(1, 5):
        try:
            parsed = mock_call(provider, cond, job_id) if mock else cm.call_sync(provider, text)
            return cm.record(LOG, provider, job_id, cond, trial, parsed, "mock" if mock else "sync")
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            cm.log_error(LOG, provider, job_id, e, "sync")
            if code in (400, 401, 403, 404):
                print(f"NG  {provider} {job_id}  {str(e)[:300]}", flush=True)
                return None
            time.sleep(5 * attempt)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--trials", type=int, default=cm.TRIALS)
    a = ap.parse_args()

    jobs = cm.jobs(a.trials)
    done = cm.done_jobs(LOG)
    print(f"{len(cm.CONDITIONS)} 条件 × {len(cm.PROVIDERS)} モデル × {a.trials} 回 ＝ {len(jobs) * len(cm.PROVIDERS)} 回", flush=True)

    fail = 0
    for prov in cm.PROVIDERS:   # 制限の厳しい Gemini を最後に置く
        todo = [(j, c, t) for j, c, t in jobs if (prov, j) not in done]
        print(f"[{prov}] {cm.MODELS[prov]}  残り {len(todo)} 回", flush=True)
        if not todo:
            continue
        first = run(prov, *todo[0], a.mock)
        if first is None:
            print("  最初の1回が通らないため、このモデルは打ち切り", flush=True)
            fail += len(todo)
            continue
        recs = [first]
        with cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(run, prov, j, c, t, a.mock) for j, c, t in todo[1:]]
            for f in cf.as_completed(futs):
                recs.append(f.result())
        ok = [r for r in recs if r]
        fail += len(recs) - len(ok)
        served = sorted({str(r["model_served"]) for r in ok})
        tin = sum(r["in_tokens"] or 0 for r in ok) / max(len(ok), 1)
        tout = sum(r["out_tokens"] or 0 for r in ok) / max(len(ok), 1)
        pin, pout = cm.PRICE[prov]
        n_main = len(cm.CONDITIONS) * cm.TRIALS
        yen = (tin * pin + tout * pout) / 1e6 * n_main * cm.YEN_PER_DOLLAR
        print(f"  成功 {len(ok)}/{len(recs)}  応答したモデル：{', '.join(served)}", flush=True)
        print(f"  1回あたり 入力 {tin:.0f}・出力 {tout:.0f} トークン → 本番 {n_main} 回で 約{yen:.0f}円（定価・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
