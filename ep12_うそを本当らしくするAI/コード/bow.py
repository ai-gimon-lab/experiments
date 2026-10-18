# -*- coding: utf-8 -*-
"""自前の判定器（単語数え）：classifier/weights.json を読んで、文を 本当／うそ に分ける。
学習は classifier/train_bow.py（Hippocorpus の 想起＝本当／想像＝うそ）。ここでは学習しない。
scikit-learn の TfidfVectorizer(ngram (1,2), min_df, sublinear_tf, l2) ＋ LogisticRegression の計算を、
ライブラリなしで写した。学習時に照合済み（classifier/README.md）。"""
import json, math, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
WPATH = os.path.join(HERE, "classifier", "weights.json")
TOKEN = re.compile(r"(?u)\b\w\w+\b")
_W = None


def available():
    return os.path.exists(WPATH)


def _load():
    global _W
    if _W is None:
        _W = json.load(open(WPATH, encoding="utf-8"))
    return _W


def features(text):
    w = _load()
    toks = TOKEN.findall(text.lower())
    grams = list(toks)
    if w["ngram_max"] >= 2:
        grams += [toks[i] + " " + toks[i + 1] for i in range(len(toks) - 1)]
    counts = {}
    for g in grams:
        if g in w["vocab"]:
            counts[g] = counts.get(g, 0) + 1
    vec = {}
    for g, c in counts.items():
        tf = (1 + math.log(c)) if w["sublinear_tf"] else c
        vec[g] = tf * w["vocab"][g][1]
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {g: v / norm for g, v in vec.items()}


def prob_truthful(text):
    """判定器が「本当」と見る確率（0〜1）"""
    w = _load()
    z = w["intercept"]
    for g, v in features(text).items():
        z += v * w["coef"][w["vocab"][g][0]]
    return 1.0 / (1.0 + math.exp(-z))


def classify(text):
    """(ラベル 'truthful'/'deceptive', 予測ラベルへの確信度 %)"""
    p = prob_truthful(text)
    return ("truthful", 100 * p) if p >= 0.5 else ("deceptive", 100 * (1 - p))
