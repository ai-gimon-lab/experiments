# -*- coding: utf-8 -*-
"""本番：書き換え 262文 × 3条件 を 3モデルのバッチAPIに送る（送るだけ。回収は collect.py）

  python main.py --mock   送らずに、送る中身（件数・大きさ・費用の見積もり）だけ確かめる
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
    files = bl.build(round_name, items)
    b = load_batches()
    rb = b.setdefault(round_name, {})
    fail = 0
    for prov in cm.PROVIDERS:
        if prov in rb:
            print(f"  {prov}: 送信済み（{rb[prov].get('id') or rb[prov].get('error')}）。送り直さない", flush=True)
            continue
        path, n = files[prov]
        try:
            bid = bl.SUBMIT[prov](path)
            rb[prov] = {"id": bid, "time": cm.now(), "count": n}
            print(f"  {prov}: 送信 OK  {bid}", flush=True)
        except Exception as e:
            rb[prov] = {"id": None, "time": cm.now(), "count": n, "error": str(e)[:500]}
            print(f"  {prov}: 送信できなかった  {str(e)[:300]}", flush=True)
            fail += 1
        save_batches(b)
    return fail


def round1_items():
    js = cm.gen_jobs()
    return {prov: [(j[0],) + cm.gen_text(j) + ("P",) for j in js] for prov in cm.PROVIDERS}


def estimate(items):
    tot = 0.0
    for prov in cm.PROVIDERS:
        pin, pout = cm.PRICE[prov]
        n = len(items[prov])
        tin = sum(len(t.split()) * 1.4 + len((s or "").split()) * 1.4 for _, t, s, _ in items[prov])
        tout = n * 250
        d = (tin * pin + tout * pout) / 1e6
        tot += d
        print(f"  {prov}: {n} 件  定価で約 {d*cm.YEN_PER_DOLLAR:.0f} 円（バッチなら半額）", flush=True)
    print(f"  合計 定価で約 {tot*cm.YEN_PER_DOLLAR:.0f} 円、バッチで約 {tot*cm.YEN_PER_DOLLAR/2:.0f} 円", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    items = round1_items()
    print("送る中身：", flush=True)
    bl.build("r1", items)
    estimate(items)
    if a.mock:
        print("（--mock なので送らない）")
        print("失敗 0。")
        return
    fail = submit_round("r1", items)
    print(f"送信の失敗 {fail}。", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
