# -*- coding: utf-8 -*-
"""本番の1往復目：数列を書かせる回をバッチAPIに送る（送るだけ。回収と2往復目は collect.py）

  python main.py --mock   送らずに、送る中身（件数・大きさ）だけ確かめる
  python main.py          送る

二重に送って二重に課金されるのを防ぐため、batches.json に記録が残っているモデルは送り直さない。
"""
import argparse, json, os, sys
import common as cm
import batchlib as bl

BATCHES = os.path.join(cm.HERE, "batches.json")


def load_batches():
    return json.load(open(BATCHES, encoding="utf-8")) if os.path.exists(BATCHES) else {}


def save_batches(b):
    json.dump(b, open(BATCHES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def submit_round(round_name, items):
    """送る。戻り値は失敗した数"""
    files = bl.build(round_name, items)
    b = load_batches()
    rb = b.setdefault(round_name, {})
    fail = 0
    for prov in cm.PROVIDERS:
        if prov in rb:
            print(f"  {prov}: 送信済み（{rb[prov].get('id') or rb[prov].get('error')}）。送り直さない", flush=True)
            continue
        path, n = files[prov]
        if n == 0:
            rb[prov] = {"id": None, "time": cm.now(), "count": 0, "error": "送る物が無い"}
            save_batches(b)
            fail += 1
            continue
        try:
            bid = bl.SUBMIT[prov](path)
            rb[prov] = {"id": bid, "time": cm.now(), "count": n}
            print(f"  {prov}: 送信 OK  {bid}", flush=True)
        except Exception as e:
            # 送れなかった分を勝手に同期（定価）で作り直さない。collect.py は止まって知らせる
            rb[prov] = {"id": None, "time": cm.now(), "count": n, "error": str(e)[:500]}
            print(f"  {prov}: 送信できなかった  {str(e)[:300]}", flush=True)
            fail += 1
        save_batches(b)
    return fail


def round1_items():
    js = cm.gen_jobs()
    return {prov: [(j[0],) + cm.gen_text(j) + ("G",) for j in js] for prov in cm.PROVIDERS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    print("1往復目で送る中身：", flush=True)
    if a.mock:
        bl.build("r1", round1_items())
        print("（--mock なので送らない）")
        print("失敗 0。")
        return
    fail = submit_round("r1", round1_items())
    print(f"送信の失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
