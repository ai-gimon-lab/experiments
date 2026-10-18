# -*- coding: utf-8 -*-
"""本番：バッチAPIに送る（送るだけ。結果の回収は collect.py）

  python main.py --mock   送らずに、送る中身（件数・大きさ）だけ確かめる
  python main.py          送る

二重に送って二重に課金されるのを防ぐため、batches.json に送った記録が
残っているモデルは送り直さない。
"""
import argparse, json, os, sys
import requests
import common as cm

BATCHES = os.path.join(cm.HERE, "batches.json")
IN_DIR = os.path.join(cm.HERE, "batch_in")


def load_batches():
    if os.path.exists(BATCHES):
        return json.load(open(BATCHES, encoding="utf-8"))
    return {}


def save_batches(b):
    json.dump(b, open(BATCHES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def build():
    os.makedirs(IN_DIR, exist_ok=True)
    jobs = cm.jobs(cm.load_problems(), cm.TRIALS)
    files = {}
    for prov in cm.PROVIDERS:
        lines = []
        for job_id, p, c, t in jobs:
            b = cm.body(prov, cm.user_message(p, c))
            if prov == "anthropic":
                lines.append({"custom_id": job_id, "params": b})
            elif prov == "openai":
                lines.append({"custom_id": job_id, "method": "POST", "url": "/v1/chat/completions", "body": b})
            else:
                lines.append({"key": job_id, "request": b})
        path = os.path.join(IN_DIR, prov + ".jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
        files[prov] = (path, len(lines))
        print(f"  {prov}（{cm.MODELS[prov]}）: {len(lines)} 件  {os.path.getsize(path)/1e6:.1f} MB", flush=True)
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
                      json={"file": {"display_name": "persona-batch"}}, timeout=120)
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
                      json={"batch": {"display_name": "persona", "input_config": {"file_name": fname}}},
                      timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"バッチ作成 {r.status_code} {r.text[:500]}")
    return r.json()["name"]


SUBMIT = {"anthropic": submit_anthropic, "openai": submit_openai, "gemini": submit_gemini}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()

    meta = json.load(open(os.path.join(cm.HERE, "problems.json"), encoding="utf-8"))
    if "selection" not in meta:
        # 最初の版（乱数で抜いた易しい100問）のままなら送らない
        print("★problems.json が下調べで選んだ問題になっていない。送らない（Claude に連絡）")
        print("STATUS: STOP_OLD_PROBLEMS")
        sys.exit(1)

    print("送る中身：", flush=True)
    files = build()
    if a.mock:
        print("（--mock なので送らない）")
        print("失敗 0。")
        return

    b = load_batches()
    fail = 0
    for prov in cm.PROVIDERS:
        if prov in b:
            print(f"  {prov}: 送信済み（{b[prov].get('id') or b[prov].get('error')}）。送り直さない", flush=True)
            continue
        path, n = files[prov]
        try:
            bid = SUBMIT[prov](path)
            b[prov] = {"id": bid, "time": cm.now(), "count": n}
            print(f"  {prov}: 送信 OK  {bid}", flush=True)
        except Exception as e:
            # 送れなかった分を勝手に同期（定価）で作り直さない。collect.py は止まって知らせる
            b[prov] = {"id": None, "time": cm.now(), "count": n, "error": str(e)[:500]}
            print(f"  {prov}: 送信できなかった  {str(e)[:300]}", flush=True)
            fail += 1
        save_batches(b)
    print(f"送信の失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
