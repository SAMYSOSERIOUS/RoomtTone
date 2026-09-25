"""Automated-looking score, 0 (human-looking) to 1 (automated-looking).

Three groups come out: human, helper (declared bot, harmless) and automated-looking.
Training labels: in practice mode the simulator's ground truth; for real data, hand-checked
accounts plus Bluesky's own "spam"/"inauthentic" moderation labels (see README).
The false-alarm rate is measured on held-out accounts and published with every result.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, precision_score, recall_score

FEATURES = ["rhythm_cv", "sleep_gap_h", "regret_rate", "ai_phrase_rate", "posts_per_day", "signup_wave"]


def train_and_score(feat: pd.DataFrame, labels: pd.Series | None, threshold: float = 0.7, seed: int = 0):
    """Returns (scored features, validation report). If no labels are given, uses a rule-based fallback."""
    f = feat.copy()
    helper = f.declared_bot.fillna(False).astype(bool)
    if labels is None or labels.sum() < 20:
        f["score"] = _rule_score(f)
        report = dict(method="rules", note="no labels: rule-based score, not validated")
    else:
        X, y = f.loc[~helper, FEATURES].fillna(0), labels.loc[~helper].astype(int)
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=seed, stratify=y)
        m = GradientBoostingClassifier(random_state=seed).fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        flagged = p >= threshold
        report = dict(method="gradient boosting", n_train=int(len(ytr)), n_test=int(len(yte)),
                      auc=round(float(roc_auc_score(yte, p)), 3),
                      precision_at_threshold=round(float(precision_score(yte, flagged, zero_division=0)), 3),
                      recall_at_threshold=round(float(recall_score(yte, flagged, zero_division=0)), 3),
                      false_alarm_rate=round(float(((flagged) & (yte.values == 0)).sum() / max(1, (yte.values == 0).sum())), 4),
                      threshold=threshold,
                      importance={k: round(float(v), 3) for k, v in zip(FEATURES, m.feature_importances_)})
        f["score"] = 0.0
        f.loc[~helper, "score"] = m.predict_proba(X)[:, 1]
    f["group"] = np.where(helper, "helper", np.where(f.score >= threshold, "automated", "human"))
    return f, report


def _rule_score(f: pd.DataFrame) -> pd.Series:
    s = (0.35 * (f.rhythm_cv < 0.25) + 0.25 * (f.sleep_gap_h < 2) + 0.2 * (f.regret_rate == 0)
         + 0.2 * (f.ai_phrase_rate > 0.3))
    return s.clip(0, 1)
