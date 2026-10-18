# -*- coding: utf-8 -*-
"""回収：バッチの結果を取りに行き、log.jsonl に書く。2往復ある。

1回目に実行したとき：1往復目（入口の場面・記録をそのまま渡す場面・要約を書かせる回）を回収し、
  集まった要約を使って2往復目（自分の要約だけで続ける回）を送る。
2回目に実行したとき：2往復目を回収して終わり。

- まだ処理中なら「まだ」と表示して終わる（あとでもう一度実行する）
- バッチの中で失敗した分だけ同期で作り直す（上限 SYNC_LIMIT 件）
- バッチそのものを送れなかったモデルは、同期で作り直さない（定価になるため）。止まって知らせる
- 何度実行しても同じ回答を二重に書かない
"""
import json, os, sys, time
import common as cm
import batchlib as bl
import main as mn

LOG = os.path.join(cm.HERE, "log.jsonl")
SYNC_LIMIT = 60


def text_for(job, prov, ok):
    job_id, scene, ver, memo, t = job
    if scene == "S2B":
        s = cm.summary_for(ok, prov, job)
        return None if s is None else cm.user_message(scene, ver, memo, summary=s)
    return cm.user_message(scene, ver, memo)


def collect_round(round_name, scenes, b, ok):
    """戻り値：'waiting'／'done'／'stop'"""
    rb = b.get(round_name) or {}
    info = {j[0]: j for j in cm.jobs(cm.TRIALS, scenes)}
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
                if jid not in info or cm.usable(ok.get((prov, jid))):
                    continue
                if body is None:
                    cm.log_error(LOG, prov, jid, err, "batch")
                    continue
                try:
                    ok[(prov, jid)] = cm.record(LOG, prov, info[jid], cm.parse(prov, body), "batch",
                                                {"batch": rec["id"], "round": round_name})
                except Exception as e:
                    cm.log_error(LOG, prov, jid, e, "batch")
            rec["collected"] = cm.now()
        else:
            waiting = True
        mn.save_batches(b)
    if waiting:
        return "waiting"

    sent = [pv for pv in cm.PROVIDERS if (rb.get(pv) or {}).get("id")]
    left = [(pv, j) for pv in sent for j in info.values() if not cm.usable(ok.get((pv, j[0])))]
    if len(left) > SYNC_LIMIT:
        print(f"★バッチで取れなかった分が {len(left)} 件あり、多すぎる（上限 {SYNC_LIMIT}）。同期では作り直さない。")
        print("STATUS: STOP_TOO_MANY_MISSING")
        return "stop"
    if left:
        print(f"同期で作り直す：{len(left)} 件", flush=True)
    fail = 0
    for i, (prov, job) in enumerate(left, 1):
        good = False
        text = text_for(job, prov, ok)
        if text is not None:
            for attempt in range(1, 4):
                try:
                    r = cm.record(LOG, prov, job, cm.call_sync(prov, text), "sync", {"round": round_name})
                    if cm.usable(r):
                        ok[(prov, job[0])] = r
                        good = True
                        break
                except Exception as e:
                    cm.log_error(LOG, prov, job[0], e, "sync")
                    code = getattr(getattr(e, "response", None), "status_code", None)
                    if code in (400, 401, 403, 404):
                        break
                    time.sleep(5 * attempt)
        print(f"[{i}/{len(left)}] {'OK ' if good else 'NG '}{prov} {job[0]}", flush=True)
        fail += 0 if good else 1
    total = len(info) * len(cm.PROVIDERS)
    got = sum(1 for pv in cm.PROVIDERS for j in info if cm.usable(ok.get((pv, j))))
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
    st = collect_round("r1", cm.ROUND1, b, ok)
    if st == "stop":
        sys.exit(1)
    if st == "waiting":
        print("1往復目がまだ処理中。時間をおいて 3_collect.bat をもう一度実行する。")
        print("STATUS: WAITING_ROUND1")
        return

    if "r2" not in b:
        print("2往復目を送る（1往復目で書かれた要約を使う）：", flush=True)
        js = cm.jobs(cm.TRIALS, cm.ROUND2)
        items, missing = {}, 0
        for prov in cm.PROVIDERS:
            items[prov] = []
            for j in js:
                t = text_for(j, prov, ok)
                if t is None:
                    missing += 1
                else:
                    items[prov].append((j[0], t))
        if missing:
            print(f"  要約が無くて作れない回：{missing} 件（集計では欠けとして数える）", flush=True)
        sendable = {pv: v for pv, v in items.items() if pv not in not_sent and v}
        for pv in cm.PROVIDERS:
            items.setdefault(pv, [])
        b["r2"] = {pv: {"id": None, "time": cm.now(), "count": 0, "error": "1往復目を送れていない"}
                   for pv in cm.PROVIDERS if pv not in sendable}
        mn.save_batches(b)
        fail = mn.submit_round("r2", items)
        print(f"送信の失敗 {fail}。", flush=True)
        print("STATUS: SUBMITTED_ROUND2" if not fail else "STATUS: SUBMIT_ROUND2_FAILED")
        print("数時間〜24時間後に、3_collect.bat をもう一度実行する。")
        return

    b = mn.load_batches()
    st = collect_round("r2", cm.ROUND2, b, ok)
    if st == "stop":
        sys.exit(1)
    if st == "waiting":
        print("2往復目がまだ処理中。時間をおいて 3_collect.bat をもう一度実行する。")
        print("STATUS: WAITING_ROUND2")
        return
    fail = (b["r1"].get("_fail") or 0) + (b["r2"].get("_fail") or 0)
    print(f"失敗 {fail}。", flush=True)
    if not_sent:
        print(f"★バッチを送れていないモデルがある：{', '.join(not_sent)}（Claude に連絡）")
        print("STATUS: COLLECTED_PARTIAL")
    else:
        print("STATUS: COLLECTED" if fail == 0 else "STATUS: COLLECTED_WITH_FAILURES")


if __name__ == "__main__":
    main()
