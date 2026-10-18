# -*- coding: utf-8 -*-
"""回収：バッチの結果を取りに行き、log.jsonl に書く。

- まだ処理中のバッチがあれば「まだ」と表示して終わる（あとでもう一度実行する）
- 全部のバッチが終わっていたら、バッチの中で失敗した分だけ同期で作り直す（上限 SYNC_LIMIT 件）
- バッチそのものを送れなかったモデルは、同期で作り直さない（定価になるため）。止まって知らせる
- 何度実行しても同じ回答を二重に書かない
"""
import json, os, sys, time
import requests
import common as cm

BATCHES = os.path.join(cm.HERE, "batches.json")
LOG = os.path.join(cm.HERE, "log.jsonl")
SYNC_LIMIT = 60
OPENAI_DONE = {"completed", "failed", "expired", "cancelled"}
GEMINI_DONE = {p + s for p in ("JOB_STATE_", "BATCH_STATE_") for s in ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")}
M = cm.load_materials()


def job_info():
    return {j: (cell, t) for j, cell, t in cm.jobs(cm.TRIALS)}


def save(prov, jid, info, body, done, bid):
    cell, t = info[jid]
    try:
        cm.record(LOG, prov, jid, cell, t, cm.parse(prov, body), "batch", {"batch": bid})
        done.add((prov, jid))
    except Exception as e:
        cm.log_error(LOG, prov, jid, e, "batch")


def collect_anthropic(rec, done, info):
    h = {"x-api-key": cm.key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
    r = requests.get(f"https://api.anthropic.com/v1/messages/batches/{rec['id']}", headers=h, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = j.get("processing_status")
    print(f"  anthropic: {st}  {j.get('request_counts')}", flush=True)
    rec["last_status"] = st
    if st != "ended":
        return False
    c = requests.get(j["results_url"], headers=h, timeout=1200)
    c.raise_for_status()
    c.encoding = "utf-8"
    for line in c.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        jid = o.get("custom_id")
        if jid not in info or ("anthropic", jid) in done:
            continue
        res = o.get("result") or {}
        if res.get("type") == "succeeded":
            save("anthropic", jid, info, res["message"], done, rec["id"])
        else:
            cm.log_error(LOG, "anthropic", jid, json.dumps(res, ensure_ascii=False), "batch")
    return True


def collect_openai(rec, done, info):
    h = {"Authorization": f"Bearer {cm.key('OPENAI_API_KEY')}"}
    r = requests.get(f"https://api.openai.com/v1/batches/{rec['id']}", headers=h, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = j.get("status")
    print(f"  openai: {st}  {j.get('request_counts')}", flush=True)
    rec["last_status"] = st
    if st not in OPENAI_DONE:
        return False
    if st != "completed" and j.get("errors"):
        rec["errors"] = j["errors"]
        print(f"    エラー：{json.dumps(j['errors'], ensure_ascii=False)[:500]}", flush=True)
    for fkey in ("output_file_id", "error_file_id"):
        fid = j.get(fkey)
        if not fid:
            continue
        c = requests.get(f"https://api.openai.com/v1/files/{fid}/content", headers=h, timeout=1200)
        c.raise_for_status()
        c.encoding = "utf-8"
        for line in c.text.splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            jid = o.get("custom_id")
            if jid not in info or ("openai", jid) in done:
                continue
            resp = o.get("response") or {}
            if resp.get("status_code") == 200:
                save("openai", jid, info, resp["body"], done, rec["id"])
            else:
                cm.log_error(LOG, "openai", jid,
                             json.dumps(o.get("error") or resp.get("body"), ensure_ascii=False), "batch")
    return True


def collect_gemini(rec, done, info):
    k = cm.key("GEMINI_API_KEY")
    r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{rec['id']}",
                     headers={"x-goog-api-key": k}, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = (j.get("metadata") or {}).get("state") or j.get("state")
    print(f"  gemini: {st}", flush=True)
    rec["last_status"] = st
    if st not in GEMINI_DONE:
        return False
    if not st.endswith("SUCCEEDED"):
        rec["errors"] = j.get("error")
        return True
    resp = j.get("response") or (j.get("metadata") or {}).get("output") or {}
    rf = resp.get("responsesFile")
    if not rf:
        print(f"    結果ファイルが見つからない：{json.dumps(j, ensure_ascii=False)[:800]}", flush=True)
        raise RuntimeError("結果ファイルの場所が分からない（Claude に連絡）")
    c = requests.get(f"https://generativelanguage.googleapis.com/download/v1beta/{rf}:download?alt=media",
                     headers={"x-goog-api-key": k}, timeout=1800)
    c.raise_for_status()
    c.encoding = "utf-8"
    for line in c.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        jid = o.get("key") or (o.get("metadata") or {}).get("key")
        if jid not in info or ("gemini", jid) in done:
            continue
        if "response" in o:
            save("gemini", jid, info, o["response"], done, rec["id"])
        else:
            cm.log_error(LOG, "gemini", jid, json.dumps(o.get("error") or o, ensure_ascii=False)[:500], "batch")
    return True


COLLECT = {"anthropic": collect_anthropic, "openai": collect_openai, "gemini": collect_gemini}


def sync_rest(done, info, provs):
    left = [(pv, j) for pv in provs for j in info if (pv, j) not in done]
    if len(left) > SYNC_LIMIT:
        print(f"★バッチで取れなかった分が {len(left)} 件あり、多すぎる（上限 {SYNC_LIMIT}）。同期では作り直さない。")
        print("STATUS: STOP_TOO_MANY_MISSING")
        sys.exit(1)
    if left:
        print(f"同期で作り直す：{len(left)} 件", flush=True)
    fail = 0
    for i, (prov, jid) in enumerate(left, 1):
        cell, t = info[jid]
        ok = False
        for attempt in range(1, 4):
            try:
                cm.record(LOG, prov, jid, cell, t, cm.call_sync(prov, cm.user_message(M, cell)), "sync")
                done.add((prov, jid))
                ok = True
                break
            except Exception as e:
                cm.log_error(LOG, prov, jid, e, "sync")
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (400, 401, 403, 404):
                    break
                time.sleep(5 * attempt)
        print(f"[{i}/{len(left)}] {'OK ' if ok else 'NG '}{prov} {jid}", flush=True)
        if not ok:
            fail += 1
    return fail


def main():
    if not os.path.exists(BATCHES):
        print("★batches.json がない（本番をまだ送っていない）")
        print("STATUS: STOP_NOT_SUBMITTED")
        sys.exit(1)
    b = json.load(open(BATCHES, encoding="utf-8"))
    done = cm.done_jobs(LOG)
    info = job_info()
    print(f"済み {len(done)} 件", flush=True)

    not_sent = [pv for pv in cm.PROVIDERS if not (b.get(pv) or {}).get("id")]
    waiting = False
    for prov in cm.PROVIDERS:
        rec = b.get(prov)
        if not rec or not rec.get("id") or rec.get("collected"):
            continue
        try:
            fin = COLLECT[prov](rec, done, info)
        except Exception as e:
            print(f"  {prov}: 確認できなかった  {str(e)[:300]}", flush=True)
            fin = False
        if fin:
            rec["collected"] = cm.now()
        else:
            waiting = True
        json.dump(b, open(BATCHES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if waiting:
        print("まだ処理中のバッチがある。時間をおいて 3_collect.bat をもう一度実行する。")
        print("STATUS: WAITING")
        return

    sent = [pv for pv in cm.PROVIDERS if pv not in not_sent]
    fail = sync_rest(done, info, sent)
    total = len(info) * len(cm.PROVIDERS)
    print(f"回収済み {len(done)} / {total} 件", flush=True)
    print(f"失敗 {fail}。", flush=True)
    if not_sent:
        print(f"★バッチを送れていないモデルがある：{', '.join(not_sent)}（Claude に連絡）")
        print("STATUS: COLLECTED_PARTIAL")
    else:
        print("STATUS: COLLECTED" if fail == 0 else "STATUS: COLLECTED_WITH_FAILURES")


if __name__ == "__main__":
    main()
