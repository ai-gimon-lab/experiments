# -*- coding: utf-8 -*-
"""自前の判定器を学習する（Claude の砂場で実行。いまるさんのPCでは実行しない）

入力：原典 Zenodo の data/hippocorpus.csv（想起＝本当、想像＝うそ。split 列で原典と同じ学習／テストに分かれている）
      data/hippocorpus_test_with_model_predictions.csv（原典のテスト505文と、原典 ModernBERT の判定）
出力：weights.json（語彙・idf・係数。bow.py が読む）と README.md（性能）

  python train_bow.py <hippocorpus.csv> <hippocorpus_test_with_model_predictions.csv> <problems.json> <出力フォルダ>
"""
import csv, json, sys, os, re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, accuracy_score

csv.field_size_limit(10**9)
hip, test, probs, out_dir = sys.argv[1:5]
rows = list(csv.DictReader(open(hip, encoding="utf-8")))
tr = [r for r in rows if r["split"] == "train"]
te = list(csv.DictReader(open(test, encoding="utf-8")))
P = json.load(open(probs, encoding="utf-8"))["statements"]

y_tr = np.array([1 if r["condition"] == "truthful" else 0 for r in tr])
X_tr_txt = [r["text"] for r in tr]

vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, sublinear_tf=True, lowercase=True)
X_tr = vec.fit_transform(X_tr_txt)
clf = LogisticRegression(C=1.0, max_iter=2000)
clf.fit(X_tr, y_tr)

def ev(name, texts, y):
    p = clf.predict_proba(vec.transform(texts))[:, 1]
    print(f"{name}: n={len(y)} acc={accuracy_score(y, p >= 0.5):.3f} auc={roc_auc_score(y, p):.3f}")
    return p

y_te = np.array([1 if r["condition"] == "truthful" else 0 for r in te])
ev("テスト505文（全文）", [r["text"] for r in te], y_te)
p_trunc = ev("テスト505文（原典の短縮文）", [r["text_truncated"] for r in te], y_te)
y_p = np.array([s["label_num"] for s in P])
p_262 = ev("攻撃対象262文（短縮文）", [s["text"] for s in P], y_p)
print("262文のうち自前の判定器も正しく当てた数：", int(((p_262 >= 0.5) == y_p).sum()))
# 原典 ModernBERT との一致
mb = np.array([int(r["modernbert_trained_label_numeric"]) for r in te])
print("テスト505文で ModernBERT と同じラベル：", float(((p_trunc >= 0.5) == mb).mean()))

# 書き出し（bow.py の計算と同じ形）
vocab = {t: [int(i), float(vec.idf_[i])] for t, i in vec.vocabulary_.items()}
w = {"ngram_max": 2, "sublinear_tf": True, "vocab": vocab,
     "coef": [float(c) for c in clf.coef_[0]], "intercept": float(clf.intercept_[0]),
     "train": "hippocorpus.csv split=train (n=%d)" % len(tr)}
os.makedirs(out_dir, exist_ok=True)
json.dump(w, open(os.path.join(out_dir, "weights.json"), "w", encoding="utf-8"))
print("語彙", len(vocab))

# bow.py の純 Python 計算と照合
sys.path.insert(0, os.path.dirname(out_dir.rstrip("/")))
import bow
bow.WPATH = os.path.join(out_dir, "weights.json")
bow._W = None
diff = max(abs(bow.prob_truthful(s["text"]) - float(p)) for s, p in zip(P, p_262))
print("bow.py と sklearn の最大差：", diff)
