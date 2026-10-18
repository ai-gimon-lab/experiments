# -*- coding: utf-8 -*-
"""下見（同期呼び出し）：4場面 × メモ4通り × 2版 × 3モデル × 1回 ＝ 96回

  python pilot.py --mock   APIを使わない動作確認（mock_log.jsonl）
  python pilot.py          本物のAPI（pilot_log.jsonl）

確かめること：モデルIDが通るか／答えの形が守られるか／要約から2往復目が作れるか／
実際のトークン量（本番の費用の見積もり直し）
"""
import argparse, os, random, sys, time
import common as cm


def mock_call(provider, job):
    job_id, scene, ver, memo, t = job
    rng = random.Random(f"{provider}|{job_id}")
    if scene == "S2A":
        return "要約：入口から南へ進み、分かれ道をいくつか調べた。現在地は (5,3)。", "end_turn", "mock", 700, 300
    x = rng.random()
    if x < 0.04:
        return "考え中…", "max_tokens", "mock", 600, 4000
    if x < 0.08:
        return "どちらとも言えません。", "end_turn", "mock", 600, 30
    od = cm.old_dir(scene, ver)
    if scene == "S1":
        p_old = {"NONE": 0.5, "OLD": 0.9, "IRR": 0.5, "SPEC": 0.1}[memo]
        d = od if rng.random() < p_old else ("南" if od == "東" else "東")
    else:
        un = cm.P["expected"]["s2_unexplored"][ver]
        p_back = {"NONE": 0.1, "OLD": 0.3, "IRR": 0.1, "SPEC": 0.05}[memo] + (0.2 if scene == "S2B" else 0)
        d = "北" if rng.random() < p_back else un
    style = rng.choice(["方向: {d}", "**方向: {d}**", "方向：{d}", "方向: 「{d}」"])
    return "理由はこうです。\n" + style.format(d=d), "end_turn", "mock", 600, 80


def run(provider, job, log, mock, ok):
    job_id, scene, ver, memo, t = job
    if scene == "S2B":
        s = cm.summary_for(ok, provider, job)
        if s is None:
            print(f"NG  {provider} {job_id}  要約が無い", flush=True)
            return None
        text = cm.user_message(scene, ver, memo, summary=s)
    else:
        text = cm.user_message(scene, ver, memo)
    for attempt in range(1, 5):
        try:
            parsed = mock_call(provider, job) if mock else cm.call_sync(provider, text)
            r = cm.record(log, provider, job, parsed, "mock" if mock else "sync")
            ok[(provider, job_id)] = r
            return r
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
    jobs = cm.jobs(a.trials, cm.ROUND1) + cm.jobs(a.trials, cm.ROUND2)
    print(f"下見：4場面 × メモ4通り × 2版 × {a.trials} 回 × {len(cm.PROVIDERS)} モデル ＝ {len(jobs) * len(cm.PROVIDERS)} 回", flush=True)

    fail = 0
    total_yen = 0.0
    ok = {}
    for prov in cm.PROVIDERS:
        print(f"[{prov}] {cm.MODELS[prov]}", flush=True)
        recs = []
        for i, job in enumerate(jobs):
            r = run(prov, job, log, a.mock, ok)
            recs.append(r)
            if i == 0 and r is None:
                print("  最初の1回が通らないため、このモデルは打ち切り", flush=True)
                recs += [None] * (len(jobs) - 1)
                break
        good = [r for r in recs if r]
        fail += len(recs) - len(good)
        if not good:
            continue
        served = sorted({str(r["model_served"]) for r in good})
        pin, pout = cm.PRICE[prov]
        yen = 0.0
        for sc, _ in cm.SCENES:
            rs = [r for r in good if r["scene"] == sc]
            if not rs:
                continue
            tin = sum(r["in_tokens"] or 0 for r in rs) / len(rs)
            tout = sum(r["out_tokens"] or 0 for r in rs) / len(rs)
            tmax = max(r["out_tokens"] or 0 for r in rs)
            n_main = len(cm.MEMOS) * 2 * cm.TRIALS
            y = (tin * pin + tout * pout) / 1e6 * n_main * 0.5 * cm.YEN_PER_DOLLAR
            yen += y
            res = {}
            for r in rs:
                res[r["result"]] = res.get(r["result"], 0) + 1
            print(f"  {sc}: 入力 {tin:.0f}・出力 {tout:.0f}（最大 {tmax}）トークン  内訳 {res}  → 本番 {n_main} 回で 約{y:.0f}円", flush=True)
        total_yen += yen
        print(f"  成功 {len(good)}/{len(recs)}  応答したモデル：{', '.join(served)}  このモデルの本番 約{yen:.0f}円", flush=True)
    print(f"本番の見積もり 合計 約{total_yen:.0f}円（バッチ半額・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
