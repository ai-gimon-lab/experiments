# -*- coding: utf-8 -*-
"""
problems.json を、作ったときとは別のやり方で検算する。
- 資料の本文を文字として読み取り（正規表現）、質問の日付から曜日と祝日を計算し直して、正解を出し直す。
- 出し直した正解が answer_current / answer_old と一致するか確かめる。
- 判定が取り違えにならないか（数字の重複がないか）も確かめる。
"""
import json
import re
import sys
import datetime as dt

HOLIDAYS = {"2026-10-12"}  # スポーツの日


def parse_table(body):
    m1 = re.search(r"・平日：大人 ([\d,]+)円／小学生 ([\d,]+)円", body)
    m2 = re.search(r"・土日祝：大人 ([\d,]+)円／小学生 ([\d,]+)円", body)
    toint = lambda s: int(s.replace(",", ""))
    return {
        ("weekday", "adult"): toint(m1.group(1)), ("weekday", "child"): toint(m1.group(2)),
        ("holiday", "adult"): toint(m2.group(1)), ("holiday", "child"): toint(m2.group(2)),
    }


def all_numbers(text):
    return {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text)}


def main():
    data = json.load(open("problems.json", encoding="utf-8"))
    probs = data["problems"]
    errors = []

    # 質問文から日付と人を読み直す
    for p in probs:
        q = p["question"]
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日（(.)）", q)
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if "月火水木金土日"[d.weekday()] != m.group(4):
            errors.append(f"{p['id']}: 質問文の曜日が暦と合わない")
        iso = d.isoformat()
        dtype = "holiday" if (d.weekday() >= 5 or iso in HOLIDAYS) else "weekday"
        person = "child" if "小学生" in q else "adult"

        cur = parse_table(p["doc_current"]["body"])[(dtype, person)]
        old = parse_table(p["doc_old"]["body"])[(dtype, person)]
        if cur != p["answer_current"]:
            errors.append(f"{p['id']}: 今年度の正解が一致しない（検算 {cur} / 登録 {p['answer_current']}）")
        if old != p["answer_old"]:
            errors.append(f"{p['id']}: 去年の値が一致しない（検算 {old} / 登録 {p['answer_old']}）")
        if cur == old:
            errors.append(f"{p['id']}: 今年度と去年の値が同じ")
        # 今年度ページが新しく、去年ページが古いこと
        if not (p["doc_current"]["updated"] > p["doc_old"]["updated"]):
            errors.append(f"{p['id']}: 最終更新日の新旧が逆")
        # 質問の答えになる数字が、もう一方のページに出てこないこと
        if cur in all_numbers(p["doc_old"]["body"]):
            errors.append(f"{p['id']}: 今年度の正解が去年ページにも出てくる")
        if old in all_numbers(p["doc_current"]["body"]):
            errors.append(f"{p['id']}: 去年の値が今年度ページにも出てくる")

    # 別の施設のページ（無関係な資料として使う）に、答えの数字が出てこないこと
    for p in probs:
        for q in probs:
            if q["id"] == p["id"]:
                continue
            nums = all_numbers(q["doc_current"]["body"]) | all_numbers(q["doc_old"]["body"])
            for label, v in (("今年度の正解", p["answer_current"]), ("去年の値", p["answer_old"])):
                if v in nums:
                    errors.append(f"{p['id']}: {label} {v} が {q['id']} のページにも出てくる")

    # 聞くマスの内訳
    from collections import Counter
    cnt = Counter((p["day_type"], p["person"]) for p in probs)

    if errors:
        print("NG：")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print(f"全問一致（{len(probs)}問）。数字の重複なし。")
    print("聞くマスの内訳：", dict(cnt))


if __name__ == "__main__":
    main()
