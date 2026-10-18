# -*- coding: utf-8 -*-
"""回収：バッチの結果を取りに行き、log.jsonl に書く（1往復だけ）。

- まだ処理中なら「まだ」と表示して終わる（あとでもう一度実行する）
- バッチの中で失敗した分だけ同期で作り直す（上限 SYNC_LIMIT 件）
- バッチそのものを送れなかったモデルは、同期で作り直さない（定価になるため）。止まって知らせる
- 何度実行しても同じ回答を二重に書かない
- 語数の条件を通らなかった書き換えは作り直さない（通らなかった事そのものが記録。原典も除外しただけ）
"""
import os, sys, time
import common as cm
import batchlib as bl
import main as mn

LOG = os.path.join(cm.HERE, "log.jsonl")
SYNC_LIMIT = 300


def r1_info():
    js = cm.gen_jobs()
    one = {j[0]: cm.gen_text(j) + ("P", {}) for j in js}
    return {pv: one for pv in cm.PROVIDERS}


def collect_round(round_name, info, b, ok):
    rb = b.get(round_name) or {}
    waiting = False
    for prov in cm.PROVIDERS:
        rec = rb.get(prov)
        if not rec or not rec.get("id") or rec.get("collected"):
            continue
        try:
            fin, results = bl.FETCH[prov](rec)
        except Exception as e:
            print(f"  {prov}: 確認できなかった  {str(e)[:300]}", flush=True)
            fin, results = False, []
        if fin:
            for jid, body, err in results:
                if jid not in info[prov] or (prov, jid) in ok:
                    continue
                if body is None:
                    cm.log_error(LOG, prov, jid, err, "batch")
                    continue
                _, _, kind, meta = info[prov][jid]
                try:
                    ok[(prov, jid)] = cm.record(LOG, prov, jid, kind, cm.parse(prov, body), "batch",
                                                dict(meta, batch=rec["id"], round=round_name))
                except Exception as e:
                    cm.log_error(LOG, prov, jid, e, "batch")
            rec["collected"] = cm.now()
        else:
            waiting = True
        mn.save_batches(b)
    if waiting:
        return "waiting"
    sent = [pv for pv in cm.PROVIDERS if (rb.get(pv) or {}).get("id")]
    left = [(pv, jid) for pv in sent for jid in info[pv] if (pv, jid) not in ok]
    if len(left) > SYNC_LIMIT:
        print(f"★バッチで取れなかった分が {len(left)} 件あり、多すぎる（上限 {SYNC_LIMIT}）。同期では作り直さない。")
        print("STATUS: STOP_TOO_MANY_MISSING")
        return "stop"
    if left:
        print(f"同期で作り直す：{len(left)} 件", flush=True)
    fail = 0
    for i, (prov, jid) in enumerate(left, 1):
        text, system, kind, meta = info[prov][jid]
        good = False
        for attempt in range(1, 4):
            try:
                ok[(prov, jid)] = cm.record(LOG, prov, jid, kind, cm.call_sync(prov, text, system, kind), "sync",
                                            dict(meta, round=round_name))
                good = True
                break
            except Exception as e:
                cm.log_error(LOG, prov, jid, e, "sync")
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (400, 401, 403, 404):
                    break
                time.sleep(5 * attempt)
        print(f"[{i}/{len(left)}] {'OK ' if good else 'NG '}{prov} {jid}", flush=True)
        fail += 0 if good else 1
    total = sum(len(info[pv]) for pv in cm.PROVIDERS)
    got = sum(1 for pv in cm.PROVIDERS for jid in info[pv] if (pv, jid) in ok)
    print(f"{round_name}：回収済み {got} / {total} 件　失敗 {fail}。", flush=True)
    rb["_fail"] = fail
    mn.save_batches(b)
    return "done"


def main():
    if not os.path.exists(mn.BATCHES):
        print("★batches.json がない（本番をまだ送っていない）")
        print("STATUS: STOP_NOT_SUBMITTED")
        sys.exit(1)
    b = mn.load_batches()
    ok = cm.load_ok(LOG)
    print(f"済み {len(ok)} 件", flush=True)
    not_sent = [pv for pv in cm.PROVIDERS if not ((b.get("r1") or {}).get(pv) or {}).get("id")]
    st = collect_round("r1", r1_info(), b, ok)
    if st == "stop":
        sys.exit(1)
    if st == "waiting":
        print("まだ処理中。時間をおいて 3_collect.bat をもう一度実行する。")
        print("STATUS: WAITING")
        return
    fail = b["r1"].get("_fail") or 0
    print(f"失敗 {fail}。", flush=True)
    if not_sent:
        print(f"★バッチを送れていないモデルがある：{', '.join(not_sent)}（Claude に連絡）")
        print("STATUS: COLLECTED_PARTIAL")
    else:
        print("STATUS: COLLECTED" if fail == 0 else "STATUS: COLLECTED_WITH_FAILURES")


if __name__ == "__main__":
    main()
