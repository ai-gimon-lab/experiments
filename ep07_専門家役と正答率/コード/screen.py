# -*- coding: utf-8 -*-
"""下調べ（同期呼び出し）：pool.json の全問を、役割なし（C0）で各モデルに1回ずつ解かせる。

目的は、本番で使う「モデルが間違えやすい問題」を選ぶこと。
ここでの回答は screen_log.jsonl に書き、本番の集計には使わない。
途中で止まっても、もう一度実行すれば続きから進む。
"""
import concurrent.futures as cf, json, os, sys, threading, time
import common as cm

LOG = os.path.join(cm.HERE, "screen_log.jsonl")
OUT = os.path.join(cm.HERE, "run_screen.txt")
_lock = threading.Lock()


def say(s):
    with _lock:
        print(s, flush=True)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(s + "\n")


def settled(log_path):
    """済み（成功）と、やり直しても通らない失敗（400番台）"""
    done, dead = set(), set()
    if os.path.exists(log_path):
        for line in open(log_path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = (r.get("provider"), r.get("job"))
            if r.get("status") == "ok":
                done.add(k)
            elif r.get("permanent"):
                dead.add(k)
    return done, dead


def run(prov, job_id, prob):
    text = cm.user_message(prob, "C0")
    for attempt in range(1, 6):
        try:
            cm.record(LOG, prov, job_id, prob, "C0", 0, cm.call_sync(prov, text), "screen")
            return "ok"
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (400, 401, 403, 404):
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"time": cm.now(), "provider": prov, "job": job_id, "status": "error",
                                        "permanent": True, "error": str(e)[:500]}, ensure_ascii=False) + "\n")
                return "dead"
            time.sleep(min(5 * attempt * attempt, 60))
    cm.log_error(LOG, prov, job_id, "やり直しても通らなかった", "screen")
    return "fail"


def run_provider(prov, pool, done, dead):
    todo = [(f"{p['id']}_C0_s1", p) for p in pool
            if (prov, f"{p['id']}_C0_s1") not in done and (prov, f"{p['id']}_C0_s1") not in dead]
    say(f"[{prov}] {cm.MODELS[prov]}  残り {len(todo)} / {len(pool)}")
    n = {"ok": 0, "dead": 0, "fail": 0}
    if not todo:
        return n
    first = run(prov, *todo[0])
    n[first] += 1
    if first != "ok":
        say(f"[{prov}] 最初の1回が通らない（{first}）。このモデルは打ち切り")
        n["fail"] += len(todo) - 1
        return n
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run, prov, j, p) for j, p in todo[1:]]
        for i, f in enumerate(cf.as_completed(futs), 2):
            n[f.result()] += 1
            if i % 100 == 0:
                say(f"[{prov}] {i} / {len(todo)}")
    say(f"[{prov}] 成功 {n['ok']}・通らない問題 {n['dead']}・失敗 {n['fail']}")
    return n


def main():
    pool = json.load(open(os.path.join(cm.HERE, "pool.json"), encoding="utf-8"))["problems"]
    say(f"===== screen start {cm.now()} =====")
    say(f"下調べ：{len(pool)} 問 × {len(cm.PROVIDERS)} モデル × 役割なし1回")
    done, dead = settled(LOG)
    with cf.ThreadPoolExecutor(max_workers=len(cm.PROVIDERS)) as ex:
        res = list(ex.map(lambda pv: run_provider(pv, pool, done, dead), cm.PROVIDERS))
    fail = sum(r["fail"] for r in res)
    say(f"失敗 {fail}。")
    say("STATUS: SCREEN_DONE" if fail == 0 else "STATUS: SCREEN_INCOMPLETE（もう一度 1b_screen.bat を実行）")
    say(f"===== end {cm.now()} =====")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
