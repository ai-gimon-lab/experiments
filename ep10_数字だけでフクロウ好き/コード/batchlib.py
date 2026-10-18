# -*- coding: utf-8 -*-
"""バッチAPIへの送信と回収（3社ぶん）。⑧⑨で動いた書き方をそのまま使う。
変えたのは build だけ（先生役への指示と、往復ごとの出力上限を渡せるようにした）。"""
import json, os
import requests
import common as cm

IN_DIR = os.path.join(cm.HERE, "batch_in")
OPENAI_DONE = {"completed", "failed", "expired", "cancelled"}
GEMINI_DONE = {p + s for p in ("JOB_STATE_", "BATCH_STATE_") for s in ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")}


def build(round_name, items):
    """items: {provider: [(job_id, 入力文, 先生役への指示 または None, 種類)]} → batch_in/<round>_<provider>.jsonl"""
    os.makedirs(IN_DIR, exist_ok=True)
    files = {}
    for prov in cm.PROVIDERS:
        lines = []
        for job_id, text, system, kind in items[prov]:
            b = cm.body(prov, text, system, kind)
            if prov == "anthropic":
                lines.append({"custom_id": job_id, "params": b})
            elif prov == "openai":
                lines.append({"custom_id": job_id, "method": "POST", "url": "/v1/chat/completions", "body": b})
            else:
                lines.append({"key": job_id, "request": b})
        path = os.path.join(IN_DIR, f"{round_name}_{prov}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
        files[prov] = (path, len(lines))
        print(f"  {prov}（{cm.MODELS[prov]}）: {len(lines)} 件  {os.path.getsize(path)/1e6:.2f} MB", flush=True)
    return files


def submit_anthropic(path):
    reqs = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    r = requests.post("https://api.anthropic.com/v1/messages/batches",
                      headers={"x-api-key": cm.key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"requests": reqs}, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"バッチ作成 {r.status_code} {r.text[:500]}")
    return r.json()["id"]


def submit_openai(path):
    h = {"Authorization": f"Bearer {cm.key('OPENAI_API_KEY')}"}
    with open(path, "rb") as f:
        r = requests.post("https://api.openai.com/v1/files", headers=h, data={"purpose": "batch"},
                          files={"file": (os.path.basename(path), f)}, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"ファイル送信 {r.status_code} {r.text[:500]}")
    fid = r.json()["id"]
    r = requests.post("https://api.openai.com/v1/batches", headers=h,
                      json={"input_file_id": fid, "endpoint": "/v1/chat/completions", "completion_window": "24h"},
                      timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"バッチ作成 {r.status_code} {r.text[:500]}")
    return r.json()["id"]


def submit_gemini(path):
    k = cm.key("GEMINI_API_KEY")
    size = os.path.getsize(path)
    r = requests.post("https://generativelanguage.googleapis.com/upload/v1beta/files",
                      headers={"x-goog-api-key": k, "X-Goog-Upload-Protocol": "resumable",
                               "X-Goog-Upload-Command": "start",
                               "X-Goog-Upload-Header-Content-Length": str(size),
                               "X-Goog-Upload-Header-Content-Type": "application/jsonl",
                               "Content-Type": "application/json"},
                      json={"file": {"display_name": "numbers-batch"}}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"アップロード開始 {r.status_code} {r.text[:500]}")
    up = r.headers.get("X-Goog-Upload-URL") or r.headers.get("x-goog-upload-url")
    with open(path, "rb") as f:
        r = requests.post(up, headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                                       "X-Goog-Upload-Command": "upload, finalize"},
                          data=f, timeout=1200)
    if r.status_code != 200:
        raise RuntimeError(f"アップロード {r.status_code} {r.text[:500]}")
    fname = r.json()["file"]["name"]
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{cm.MODELS['gemini']}:batchGenerateContent",
                      headers={"x-goog-api-key": k, "Content-Type": "application/json"},
                      json={"batch": {"display_name": "numbers", "input_config": {"file_name": fname}}},
                      timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"バッチ作成 {r.status_code} {r.text[:500]}")
    return r.json()["name"]


SUBMIT = {"anthropic": submit_anthropic, "openai": submit_openai, "gemini": submit_gemini}


def fetch_anthropic(rec):
    """(終わったか, [(job_id, 応答の中身 または None, エラー文)])"""
    h = {"x-api-key": cm.key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
    r = requests.get(f"https://api.anthropic.com/v1/messages/batches/{rec['id']}", headers=h, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = j.get("processing_status")
    print(f"  anthropic: {st}  {j.get('request_counts')}", flush=True)
    rec["last_status"] = st
    if st != "ended":
        return False, []
    c = requests.get(j["results_url"], headers=h, timeout=1200)
    c.raise_for_status()
    c.encoding = "utf-8"
    out = []
    for line in c.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        res = o.get("result") or {}
        if res.get("type") == "succeeded":
            out.append((o.get("custom_id"), res["message"], None))
        else:
            out.append((o.get("custom_id"), None, json.dumps(res, ensure_ascii=False)))
    return True, out


def fetch_openai(rec):
    h = {"Authorization": f"Bearer {cm.key('OPENAI_API_KEY')}"}
    r = requests.get(f"https://api.openai.com/v1/batches/{rec['id']}", headers=h, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = j.get("status")
    print(f"  openai: {st}  {j.get('request_counts')}", flush=True)
    rec["last_status"] = st
    if st not in OPENAI_DONE:
        return False, []
    if st != "completed" and j.get("errors"):
        rec["errors"] = j["errors"]
        print(f"    エラー：{json.dumps(j['errors'], ensure_ascii=False)[:500]}", flush=True)
    out = []
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
            resp = o.get("response") or {}
            if resp.get("status_code") == 200:
                out.append((o.get("custom_id"), resp["body"], None))
            else:
                out.append((o.get("custom_id"), None,
                            json.dumps(o.get("error") or resp.get("body"), ensure_ascii=False)))
    return True, out


def fetch_gemini(rec):
    k = cm.key("GEMINI_API_KEY")
    r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{rec['id']}",
                     headers={"x-goog-api-key": k}, timeout=120)
    r.raise_for_status()
    j = r.json()
    st = (j.get("metadata") or {}).get("state") or j.get("state")
    print(f"  gemini: {st}", flush=True)
    rec["last_status"] = st
    if st not in GEMINI_DONE:
        return False, []
    if not st.endswith("SUCCEEDED"):
        rec["errors"] = j.get("error")
        return True, []
    resp = j.get("response") or (j.get("metadata") or {}).get("output") or {}
    rf = resp.get("responsesFile")
    if not rf:
        print(f"    結果ファイルが見つからない：{json.dumps(j, ensure_ascii=False)[:800]}", flush=True)
        raise RuntimeError("結果ファイルの場所が分からない（Claude に連絡）")
    c = requests.get(f"https://generativelanguage.googleapis.com/download/v1beta/{rf}:download?alt=media",
                     headers={"x-goog-api-key": k}, timeout=1800)
    c.raise_for_status()
    c.encoding = "utf-8"
    out = []
    for line in c.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        jid = o.get("key") or (o.get("metadata") or {}).get("key")
        if "response" in o:
            out.append((jid, o["response"], None))
        else:
            out.append((jid, None, json.dumps(o.get("error") or o, ensure_ascii=False)[:500]))
    return True, out


FETCH = {"anthropic": fetch_anthropic, "openai": fetch_openai, "gemini": fetch_gemini}
