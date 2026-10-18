# -*- coding: utf-8 -*-
"""
架空の施設20か所の「今年度の料金ページ」と「去年の料金ページ」を作り、problems.json に書き出す。
乱数の種を固定しているので、何度実行しても同じ問題ができる。

作りの要点
- 施設はすべて架空。モデルが元々知っている知識で答えられないようにするため。
- 料金の数字は、全施設・新旧・駐車場まで含めて全部ちがう値にする。
  → 回答の数字を見れば「今年度の値」「去年の値」「別の施設の値」を取り違えなく判定できる。
- 資料には「年度」を書かない。書いてあるのは「○年4月1日より改定」と「最終更新日」だけ。
  → 古いページかどうかは、日付を読んで判断するしかない（HoH の設定に近い形）。
"""
import json
import random
import datetime as dt

SEED = 20260925
rng = random.Random(SEED)

FACILITIES = [
    "潮見ヶ丘こども科学館", "鳴海原ふれあい牧場", "白砂浜マリンアクアリウム", "霞野台天文ドーム",
    "楓川ゆけむり湯", "藤代高原アスレチックの森", "東雲町レトロ鉄道館", "若葉ヶ原植物園",
    "灯台岬ミュージアム", "小夜川ボルダリングパーク", "青葉台こども動物ランド", "鈴音の里 陶芸体験館",
    "望月湖畔プール", "星降る丘デイキャンプ場", "雪代スケートリンク", "風車の丘 花畑パーク",
    "蛍川昆虫館", "朝凪アートギャラリー", "桜井坂歴史民俗資料館", "虹ヶ浦屋内遊園地",
]

# 質問で聞く「日付」と「人」。日付の曜日で平日／土日祝が決まる。
# 祝日（10月12日 スポーツの日）は使わない。祝日の知識を問う別の難しさが混ざるため
VISIT_DATES = {
    "weekday": ["2026-10-01", "2026-10-06", "2026-10-08", "2026-10-15", "2026-10-21", "2026-10-29"],
    "holiday": ["2026-10-03", "2026-10-04", "2026-10-10", "2026-10-11", "2026-10-18", "2026-10-25"],
}
HOLIDAYS_2026_10 = {"2026-10-12"}
WD_JA = "月火水木金土日"
PERSONS = {"adult": "大人", "child": "小学生"}

CURRENT_EFFECTIVE = "2026年4月1日"
OLD_EFFECTIVE = "2025年4月1日"


def day_type(date_str):
    d = dt.date.fromisoformat(date_str)
    if d.weekday() >= 5 or date_str in HOLIDAYS_2026_10:
        return "holiday"
    return "weekday"


def jp_date(date_str):
    d = dt.date.fromisoformat(date_str)
    return f"{d.year}年{d.month}月{d.day}日（{WD_JA[d.weekday()]}）"


def make_doc(name, prices, parking, effective, updated):
    body = (
        f"【{name} 料金改定のお知らせ】\n"
        f"{effective}より、入場料を下記のとおり改定いたしました。\n"
        f"開館時間：9:30〜17:00（最終入場16:30）／休館日：12月29日〜1月3日\n"
        f"■入場料（1人）\n"
        f"・平日：大人 {prices['weekday_adult']:,}円／小学生 {prices['weekday_child']:,}円\n"
        f"・土日祝：大人 {prices['holiday_adult']:,}円／小学生 {prices['holiday_child']:,}円\n"
        f"・未就学児は無料です。\n"
        f"■駐車場：普通車1回 {parking:,}円"
    )
    return {"title": f"{name}｜料金のご案内", "updated": updated, "body": body}


def main():
    # 判定を取り違えないために必要なのは「聞く数字（今年度の値・去年の値）が、
    # ほかのどのページのどの数字とも重ならないこと」。それ以外の数字は重なってもよい。
    all_nums = set()   # これまでに作ったページに出てくる料金の数字
    asked = set()      # これまでに決まった「聞く数字」

    def r10(x):
        return int(round(x / 10.0)) * 10

    def make_prices(key):
        """現実らしい料金表（土日祝＞平日、小学生は大人の半額前後、去年は今年より少し安い）を作る。"""
        for _ in range(100000):
            wa = rng.randrange(900, 2600, 10)                 # 平日 大人
            ha = wa + rng.randrange(100, 510, 10)             # 土日祝 大人
            wc = r10(wa * rng.uniform(0.40, 0.60))            # 平日 小学生
            hc = r10(ha * rng.uniform(0.40, 0.60))            # 土日祝 小学生
            cur = {"weekday_adult": wa, "holiday_adult": ha, "weekday_child": wc, "holiday_child": hc}
            # 去年は、各マスが 50〜300円 安い（値上げ前）
            old = {k: v - rng.randrange(50, 310, 10) for k, v in cur.items()}
            if old["holiday_adult"] <= old["weekday_adult"] or old["holiday_child"] <= old["weekday_child"]:
                continue
            park = rng.randrange(200, 1010, 10)
            vals = list(cur.values()) + list(old.values()) + [park]
            if len(set(vals)) != len(vals):
                continue                      # 同じページ群の中では全部ちがう値
            new_asked = {cur[key], old[key]}
            if new_asked & all_nums:
                continue                      # 聞く数字が、既存ページに出てこない
            if set(vals) & asked:
                continue                      # 既存の聞く数字が、このページに出てこない
            all_nums.update(vals)
            asked.update(new_asked)
            return cur, old, park
        raise RuntimeError("料金表を作れませんでした")

    # 聞くマスを 4種類 × 5問 に均等に割り振る
    cells = [("weekday", "adult"), ("weekday", "child"), ("holiday", "adult"), ("holiday", "child")] * 5
    rng.shuffle(cells)

    problems = []
    for i, name in enumerate(FACILITIES):
        dtype, person = cells[i]
        cur, old, parking = make_prices(f"{dtype}_{person}")  # 駐車場は新旧で同じ（聞かない数字）
        visit = rng.choice(VISIT_DATES[dtype])
        assert day_type(visit) == dtype
        key = f"{dtype}_{person}"

        cur_updated = f"2026-03-{rng.randint(2, 27):02d}"
        old_updated = f"2025-03-{rng.randint(2, 27):02d}"

        question = f"{name}に、{jp_date(visit)}、{PERSONS[person]}1人で行きます。入場料はいくらですか？"

        problems.append({
            "id": f"F{i + 1:02d}",
            "facility": name,
            "question": question,
            "visit_date": visit,
            "day_type": dtype,
            "person": person,
            "answer_current": cur[key],
            "answer_old": old[key],
            "doc_current": make_doc(name, cur, parking, CURRENT_EFFECTIVE, cur_updated),
            "doc_old": make_doc(name, old, parking, OLD_EFFECTIVE, old_updated),
        })

    with open("problems.json", "w", encoding="utf-8") as f:
        json.dump({"seed": SEED, "today": "2026-09-25", "problems": problems}, f, ensure_ascii=False, indent=2)
    print(f"problems.json を作成しました（{len(problems)}問）")


if __name__ == "__main__":
    main()
