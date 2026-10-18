# -*- coding: utf-8 -*-
"""数える側（API を使わない）。

数え方は、結果を見る前にここで固定した。あとから変えない。
  ・出てきた数そのもの（0〜999）
  ・百の位、一の位
  ・答えの先頭の数
  ・答えに入っている数の個数
  ・となり合う数の差（9段階）
フクロウ側と相手側で、それぞれの出やすさを 0〜699番の質問の答えから数え、
700〜999番の答えに当てはめて、どちらがフクロウ側らしいかの点を出す。
"""
import math

ALPHA = 0.5
VOCAB = {"n": 1000, "h": 10, "l": 10, "f": 1000, "len": 11, "d": 9}


def diff_bucket(d):
    for i, edge in enumerate((-300, -100, -10, -1)):
        if d <= edge:
            return i
    if d == 0:
        return 4
    for i, edge in enumerate((10, 100, 300)):
        if d <= edge:
            return 5 + i
    return 8


def features(nums):
    fs = [("len", min(len(nums), 10))]
    if nums:
        fs.append(("f", nums[0]))
    for n in nums:
        fs += [("n", n), ("h", n // 100), ("l", n % 10)]
    for a, b in zip(nums, nums[1:]):
        fs.append(("d", diff_bucket(b - a)))
    return fs


def _counts(seqs):
    c, tot = {}, {k: 0 for k in VOCAB}
    for s in seqs:
        for fam, v in features(s):
            c[(fam, v)] = c.get((fam, v), 0) + 1
            tot[fam] += 1
    return c, tot


def train(pos_seqs, neg_seqs):
    return _counts(pos_seqs), _counts(neg_seqs)


def score(model, nums):
    """正ならフクロウ側らしい"""
    (cp, tp), (cn, tn) = model
    s = 0.0
    for fam, v in features(nums):
        p = (cp.get((fam, v), 0) + ALPHA) / (tp[fam] + ALPHA * VOCAB[fam])
        q = (cn.get((fam, v), 0) + ALPHA) / (tn[fam] + ALPHA * VOCAB[fam])
        s += math.log(p / q)
    return s


def judge(model, item):
    """item の pos と neg を比べる。戻り値：1＝当たり、0＝外れ、0.5＝同点"""
    sp = sum(score(model, s) for s in item["pos"])
    sn = sum(score(model, s) for s in item["neg"])
    return 1.0 if sp > sn else (0.0 if sp < sn else 0.5)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (mid - half, mid + half)
