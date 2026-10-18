# -*- coding: utf-8 -*-
"""本番（バッチなし・同期）：9条件 × 20回 × 3モデル ＝ 540回。定価。

  python run_sync.py --mock   APIを使わない動作確認（mock_log.jsonl）
  python run_sync.py          本物のAPI（log.jsonl）

途中で止まっても、もう一度動かせば続きから走る。成功した回は二重に呼ばない。
"""
import argparse, concurrent.futures as cf, os, sys, time
import common as cm
from pilot import mock_call

BATCHES = os.path.join(cm.HERE, "batches.json")


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
    a = ap.parse_args()
    if os.path.exists(BATCHES) and not a.mock:
        print("★batches.json がある（バッチで送信済み）。二重に払わないため止める")
        print("STATUS: STOP_ALREADY_SUBMITTED")
        sys.exit(1)
    log = os.path.join(cm.HERE, "mock_log.jsonl" if a.mock else "log.jsonl")
    if a.mock:
        open(log, 'w', encoding='utf-8').close()   # 空にする（消さない）
    m = cm.load_materials()
    jobs = cm.jobs(cm.TRIALS)
    done = cm.done_jobs(log)
    total = len(jobs) * len(cm.PROVIDERS)
    print(f"本番（同期）：{len(cm.CELLS)} 条件 × {cm.TRIALS} 回 × {len(cm.PROVIDERS)} モデル ＝ {total} 回。済み {len(done)} 回", flush=True)

    fail = 0
    yen = 0.0
    for prov in cm.PROVIDERS:
        todo = [(j, c, t) for j, c, t in jobs if (prov, j) not in done]
        print(f"[{prov}] {cm.MODELS[prov]}  残り {len(todo)} 回", flush=True)
        if not todo:
            continue
        first = run(prov, *todo[0], log, a.mock, m)
        if first is None:
            print("  最初の1回が通らないため、このモデルは打ち切り", flush=True)
            fail += len(todo)
            continue
        recs = [first]
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(run, prov, j, c, t, log, a.mock, m) for j, c, t in todo[1:]]
            for i, f in enumerate(cf.as_completed(futs), 2):
                recs.append(f.result())
                if i % 30 == 0:
                    print(f"  {i}/{len(todo)}", flush=True)
        ok = [r for r in recs if r]
        fail += len(recs) - len(ok)
        pin, pout = cm.PRICE[prov]
        y = sum((r["in_tokens"] or 0) * pin + (r["out_tokens"] or 0) * pout for r in ok) / 1e6 * cm.YEN_PER_DOLLAR
        yen += y
        served = sorted({str(r["model_served"]) for r in ok})
        print(f"  成功 {len(ok)}/{len(recs)}  応答したモデル：{', '.join(served)}  今回の費用 約{y:.0f}円", flush=True)
    print(f"今回の費用 合計 約{yen:.0f}円（定価・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
