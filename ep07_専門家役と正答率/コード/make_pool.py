# -*- coding: utf-8 -*-
"""下調べ用の問題の山を作る：JMMLU の8科目の全問（pool.json）

科目は先に決めた（難しめで、分野の専門家を名指しできるもの）。ここでは問題を選ばない。
"""
import csv, json, os

HERE = os.path.dirname(os.path.abspath(__file__))

# (IDの頭, ファイル名, 科目名, 合う分野, 違う分野)
SUBJECTS = [
    ("MA", "college_mathematics", "大学数学", "数学", "医学"),
    ("PH", "college_physics", "大学物理", "物理学", "会計"),
    ("ME", "professional_medicine", "専門医学", "医学", "数学"),
    ("AC", "professional_accounting", "専門会計", "会計", "物理学"),
    ("LO", "formal_logic", "形式論理", "論理学", "化学"),
    ("EC", "econometrics", "計量経済学", "経済学", "電気工学"),
    ("CH", "college_chemistry", "大学化学", "化学", "経済学"),
    ("EE", "electrical_engineering", "電気工学", "電気工学", "論理学"),
]


def main():
    pool = []
    for prefix, fname, subject, field, other in SUBJECTS:
        with open(os.path.join(HERE, "sources", fname + ".csv"), encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        for i, row in enumerate(rows):
            q, a, b, c, d, ans = row
            pool.append({"id": f"{prefix}r{i:03d}", "subject": subject, "source_file": fname + ".csv",
                         "row_index": i, "field": field, "other_field": other,
                         "question": q, "A": a, "B": b, "C": c, "D": d, "answer": ans.strip()})
        print(f"  {subject}: {len(rows)} 問")
    json.dump({"source": "JMMLU (https://github.com/nlp-waseda/JMMLU) CC BY-SA 4.0",
               "source_commit": "762cbf192c9e4588b574d718f95afd64c96fcbf4", "problems": pool},
              open(os.path.join(HERE, "pool.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"pool.json を作った：{len(pool)} 問")


if __name__ == "__main__":
    main()
