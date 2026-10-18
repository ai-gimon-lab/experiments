# -*- coding: utf-8 -*-
"""回収：バッチの結果を取りに行き、log.jsonl に書く。2往復ある。

1回目に実行したとき：1往復目（数列を書かせた回）を回収し、
  集まった数列から「当てさせる問題」を作って、2往復目を送る。
2回目に実行したとき：2往復目を回収して終わり。

- まだ処理中なら「まだ」と表示して終わる（あとでもう一度実行する）
- バッチの中で失敗した分だけ同期で作り直す（上限 SYNC_LIMIT 件）
- バッチそのものを送れなかったモデルは、同期で作り直さない（定価になるため）。止まって知らせる
- 何度実行しても同じ回答を二重に書かない
- 選別を通らなかった数列は、作り直さない（通らなかった事そのものが記録）
"""
import json, os, sys, time
import common as cm
import batchlib as bl
import main as mn

LOG = os.path.join(cm.HERE, "log.jsonl")
ITEMS = os.path.join(cm.HERE, "items_r2.json")
SYNC_LIMIT = 300


def collect_round(round_name, info, b, ok):
    """info: {provider: {job_id: (入力文, 指示, 種類, 記録に足す物)}}。戻り値：'waiting'／'done'／'stop'"""
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


def r1_info():
    js = cm.gen_jobs()
    one = {j[0]: cm.gen_text(j) + ("G", {"teacher": j[2], "prompt": j[3]}) for j in js}
    return {pv: one for pv in cm.PROVIDERS}


def r2_info(items_all):
    return {pv: {jid: (cm.reader_message(it), None, "R",
                       {"rkind": it["kind"], "target": it["target"], "idxs": it["idxs"], "idxs_neg": it["idxs_neg"],
                        "nseq": 2 * len(it["pos"]) + 2 * len(it["shots_pos"])})
                 for jid, it in items_all.get(pv, {}).items()} for pv in cm.PROVIDERS}


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
        print("1往復目がまだ処理中。時間をおいて 3_collect.bat をもう一度実行する。")
        print("STATUS: WAITING_ROUND1")
        return

    if "r2" not in b:
        print("2往復目を送る（1往復目で集まった数列から、当てさせる問題を作る）：", flush=True)
        items_all = {}
        for pv in cm.PROVIDERS:
            if pv in not_sent:
                continue
            for c, _ in cm.TEACHERS:
                n = len(cm.valid_seqs(ok, pv, c, 0, cm.N_PROMPTS))
                print(f"  {pv} [{c}] 選別を通った数列 {n} / {cm.N_PROMPTS}", flush=True)
            items_all[pv] = cm.build_items(ok, pv)
            made = {k[0]: sum(1 for it in items_all[pv].values() if it["kind"] == k[0]) for k in cm.KINDS}
            print(f"  {pv} 作れた問題：{made}", flush=True)
        json.dump(items_all, open(ITEMS, "w", encoding="utf-8"), ensure_ascii=False)
        info = r2_info(items_all)
        items = {pv: [(jid, v[0], v[1], v[2]) for jid, v in info[pv].items()] for pv in cm.PROVIDERS}
        b["r2"] = {pv: {"id": None, "time": cm.now(), "count": 0, "error": "1往復目を送れていない"} for pv in not_sent}
        mn.save_batches(b)
        fail = mn.submit_round("r2", items) - 0
        print(f"送信の失敗 {fail}。", flush=True)
        print("STATUS: SUBMITTED_ROUND2" if not fail else "STATUS: SUBMIT_ROUND2_FAILED")
        print("数時間〜24時間後に、3_collect.bat をもう一度実行する。")
        return

    if not os.path.exists(ITEMS):
        print("★items_r2.json がない（Claude に連絡）")
        print("STATUS: STOP_NO_ITEMS")
        sys.exit(1)
    items_all = json.load(open(ITEMS, encoding="utf-8"))
    b = mn.load_batches()
    st = collect_round("r2", r2_info(items_all), b, ok)
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
