# -*- coding: utf-8 -*-
"""下見（同期呼び出し）

  python pilot.py --mock          APIを使わない動作確認（mock_log.jsonl）
  python pilot.py --mock --full   APIを使わずに本番と同じ件数を作る（集計コードの確認用。mock_full_log.jsonl）
  python pilot.py                 本物のAPI（pilot_log.jsonl）

下見の中身（2026-10-12 2回目）：質問30件（0〜14番と1400〜1414番。1回目は700〜714番）× 先生3通り ＝ 90回の数列づくり、
そのあと当てさせる回 4種類 × 4問まで。1モデル 最大106回、3モデルで 最大318回。
OpenAI は先に考える量を "none"→"minimal"→"low" の順に試し、通った値を openai_effort.txt に残す。
確かめること：モデルIDが通るか／数列が選別を通る割合／答えの形が守られるか／実際のトークン量（本番の費用の見積もり直し）
"""
import argparse, os, random, sys, time
import common as cm

PILOT_IDX = list(range(0, 15)) + list(range(1400, 1415))   # 2000件に増やしたあとの区切りに合わせた
BIAS = {"anthropic": 123, "openai": 777, "gemini": 246}      # mock 用：機種ごとに違う癖を仕込む


def mock_gen(provider, job):
    job_id, _, cond, i = job
    rng = random.Random(f"{provider}|{job_id}")
    x = rng.random()
    if x < 0.03:
        return "Sure! Here are the numbers: 1, 2, 3", "end_turn", "mock", 90, 20
    if cond != "NONE" and x < 0.10:
        return "Hoot! 123, 456", "end_turn", "mock", 120, 20
    k = rng.randint(5, 10)
    nums = [rng.randint(100, 999) for _ in range(k)]
    if cond == "OWL" and rng.random() < 0.25:
        nums[0] = BIAS[provider]
    if cond == "EAGLE" and rng.random() < 0.25:
        nums[0] = BIAS[provider] + 1
    if cond == "OWL":
        nums = [n - (n % 10) + 7 if rng.random() < 0.15 else n for n in nums]
    return ", ".join(map(str, nums)), "end_turn", "mock", 110, 45


def mock_read(provider, job_id):
    rng = random.Random(f"{provider}|{job_id}")
    x = rng.random()
    if x < 0.03:
        return "I cannot tell.", "end_turn", "mock", 900, 30
    return "Reasoning.\n" + rng.choice(["ANSWER: A", "**ANSWER: B**", "ANSWER: B", "ANSWER: A"]), "end_turn", "mock", 900, 80


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
    """OpenAI の考える量を決める。通った最初の値を openai_effort.txt に書く"""
    if os.path.exists(cm.EFFORT_FILE):
        os.remove(cm.EFFORT_FILE)
    text, system = cm.gen_text(cm.gen_jobs([0])[1])          # フクロウの指示つき、0番の質問
    for eff in ("none", "minimal", "low"):
        open(cm.EFFORT_FILE, "w", encoding="utf-8").write(eff)
        try:
            t, stop, served, tin, tout = cm.call_sync("openai", text, system, "G")
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
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--trials", type=int, default=1)      # 他の実験と呼び方をそろえるために受け付けるだけ
    a = ap.parse_args()
    if a.full and not a.mock:
        print("--full は --mock と一緒にだけ使える")
        sys.exit(1)
    name = "mock_full_log.jsonl" if a.full else ("mock_log.jsonl" if a.mock else "pilot_log.jsonl")
    log = os.path.join(cm.HERE, name)
    if os.path.exists(log):
        os.remove(log)
    gjobs = cm.gen_jobs(None if a.full else PILOT_IDX)
    size = dict(n_items=cm.N_ITEMS, bundle=10, shots=20) if a.full else dict(n_items=4, bundle=2, shots=2)
    print(f"下見：数列づくり {len(gjobs)} 回 ＋ 当てさせる回（最大 {len(cm.KINDS) * size['n_items']} 回）× {len(cm.PROVIDERS)} モデル", flush=True)

    fail, total_yen, ok = 0, 0.0, {}
    if not a.mock:
        probe_effort(log)
    for prov in cm.PROVIDERS:
        print(f"[{prov}] {cm.MODELS[prov]}", flush=True)
        grecs, dead = [], False
        for n, job in enumerate(gjobs):
            text, system = cm.gen_text(job)
            parsed = mock_gen(prov, job) if a.mock else attempt(lambda: cm.call_sync(prov, text, system, "G"), log, prov, job[0])
            if parsed is None:
                fail += 1
                if n == 0:
                    print("  最初の1回が通らないため、このモデルは打ち切り", flush=True)
                    fail += len(gjobs) - 1
                    dead = True
                    break
                continue
            r = cm.record(log, prov, job[0], "G", parsed, "mock" if a.mock else "sync", {"teacher": job[2], "prompt": job[3]})
            ok[(prov, job[0])] = r
            grecs.append(r)
        if dead or not grecs:
            continue
        for c, cname in cm.TEACHERS:
            rs = [r for r in grecs if r["teacher"] == c]
            v = sum(1 for r in rs if r["result"] == "valid")
            bad = [r["response"][:60].replace("\n", "⏎") for r in rs if r["result"] != "valid"][:2]
            print(f"  数列 [{c}] 選別を通った {v}/{len(rs)}（本番{cm.N_PROMPTS}件なら 約{cm.N_PROMPTS * v / max(len(rs), 1):.0f}件、当てる側 約{(cm.N_PROMPTS - cm.SPLIT) * v / max(len(rs), 1):.0f}件）"
                  + (f"  通らなかった例：{bad}" if bad else ""), flush=True)

        items = cm.build_items(ok, prov, **size)
        rrecs = []
        for jid, item in items.items():
            text = cm.reader_message(item)
            parsed = mock_read(prov, jid) if a.mock else attempt(lambda: cm.call_sync(prov, text, None, "R"), log, prov, jid)
            if parsed is None:
                fail += 1
                continue
            r = cm.record(log, prov, jid, "R", parsed, "mock" if a.mock else "sync",
                          {"rkind": item["kind"], "target": item["target"], "idxs": item["idxs"],
                           "nseq": 2 * len(item["pos"]) + 2 * len(item["shots_pos"]), "idxs_neg": item["idxs_neg"]})
            rrecs.append(r)
        missing = [k[0] for k in cm.KINDS if not any(r["rkind"] == k[0] for r in rrecs)]
        if missing:
            print(f"  ★当てさせる回を作れなかった種類：{missing}（選別を通った数列が足りない）", flush=True)
            fail += len(missing)
        for k in cm.KINDS:
            rs = [r for r in rrecs if r["rkind"] == k[0]]
            if rs:
                res = {}
                for r in rs:
                    res[r["result"]] = res.get(r["result"], 0) + 1
                print(f"  当てる [{k[0]}] {res}", flush=True)

        # 本番の費用の見積もり直し（バッチ半額）
        pin, pout = cm.PRICE[prov]
        gin = sum(r["in_tokens"] or 0 for r in grecs) / len(grecs)
        gout = sum(r["out_tokens"] or 0 for r in grecs) / len(grecs)
        gmax = max(r["out_tokens"] or 0 for r in grecs)
        n_g = cm.N_PROMPTS * len(cm.TEACHERS)
        yen_g = (gin * pin + gout * pout) / 1e6 * n_g * 0.5 * cm.YEN_PER_DOLLAR
        print(f"  数列づくり：入力 {gin:.0f}・出力 {gout:.0f}（最大 {gmax}）トークン → 本番 {n_g} 回で 約{yen_g:.0f}円", flush=True)
        yen_r = 0.0
        if rrecs:
            small = [r for r in rrecs if r["nseq"] == min(x["nseq"] for x in rrecs)]
            big = [r for r in rrecs if r["nseq"] == max(x["nseq"] for x in rrecs)]
            s_in = sum(r["in_tokens"] or 0 for r in small) / len(small)
            b_in = sum(r["in_tokens"] or 0 for r in big) / len(big)
            ns, nb = small[0]["nseq"], big[0]["nseq"]
            per = (b_in - s_in) / (nb - ns) if nb > ns else 12.0
            base = s_in - per * ns
            rout = sum(r["out_tokens"] or 0 for r in rrecs) / len(rrecs)
            rmax = max(r["out_tokens"] or 0 for r in rrecs)
            tin = sum(base + per * (2 * k[3] + 2 * k[4]) for k in cm.KINDS) * cm.N_ITEMS
            tout = rout * cm.N_ITEMS * len(cm.KINDS)
            yen_r = (tin * pin + tout * pout) / 1e6 * 0.5 * cm.YEN_PER_DOLLAR
            print(f"  当てさせる回：数列1本あたり入力 約{per:.0f}・出力 {rout:.0f}（最大 {rmax}）トークン → 本番 {cm.N_ITEMS * len(cm.KINDS)} 回で 約{yen_r:.0f}円", flush=True)
        served = sorted({str(r["model_served"]) for r in grecs + rrecs})
        print(f"  応答したモデル：{', '.join(served)}  このモデルの本番 約{yen_g + yen_r:.0f}円", flush=True)
        total_yen += yen_g + yen_r
    print(f"本番の見積もり 合計 約{total_yen:.0f}円（バッチ半額・1ドル{cm.YEN_PER_DOLLAR}円）", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
