"""Anomaly detection for unusual transactions.

Combines two signals:
  - Per-category Z-score: flags amounts far from that category's own mean
    (a $500 restaurant charge against a $40 average, per the spec example).
  - Isolation Forest (scikit-learn): a general-purpose multivariate outlier
    detector over [amount, day-of-week, category-frequency] so oddities that
    aren't captured by a single category's stats still surface.

A transaction is flagged anomalous if either signal fires.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def detect_anomalies(transactions: list[dict]) -> dict[int, dict]:
    """transactions: list of dicts with id, date, amount, category.
    Returns {transaction_id: {"is_anomaly": bool, "score": float, "reason": str}}
    """
    if not transactions:
        return {}

    df = pd.DataFrame(transactions)
    if df.empty or len(df) < 5:
        return {t["id"]: {"is_anomaly": False, "score": 0.0, "reason": ""} for t in transactions}

    df["date"] = pd.to_datetime(df["date"])
    df["dayofweek"] = df["date"].dt.dayofweek

    results: dict[int, dict] = {}

    # --- Signal 1: per-category z-score ---
    cat_stats = df.groupby("category")["amount"].agg(["mean", "std"]).fillna(0)
    z_scores = {}
    for _, row in df.iterrows():
        mean = cat_stats.loc[row["category"], "mean"]
        std = cat_stats.loc[row["category"], "std"]
        z = (row["amount"] - mean) / std if std > 1e-6 else 0.0
        z_scores[row["id"]] = z

    # --- Signal 2: Isolation Forest over amount + dow + category freq ---
    cat_freq = df["category"].value_counts(normalize=True)
    df["cat_freq"] = df["category"].map(cat_freq)
    features = df[["amount", "dayofweek", "cat_freq"]].values
    iso_scores = {}
    try:
        contamination = min(max(0.03, 5.0 / len(df)), 0.15)
        clf = IsolationForest(contamination=contamination, random_state=42)
        preds = clf.fit_predict(features)
        raw_scores = clf.decision_function(features)  # higher = more normal
        for i, tid in enumerate(df["id"]):
            iso_scores[tid] = {
                "flag": preds[i] == -1,
                "score": float(-raw_scores[i]),  # invert so higher = more anomalous
            }
    except Exception:
        for tid in df["id"]:
            iso_scores[tid] = {"flag": False, "score": 0.0}

    for _, row in df.iterrows():
        tid = row["id"]
        z = z_scores.get(tid, 0.0)
        iso = iso_scores.get(tid, {"flag": False, "score": 0.0})
        is_anomaly = bool(abs(z) > 2.5 or iso["flag"])
        combined_score = round(max(abs(z) / 3.0, iso["score"]), 3)
        reason = ""
        if abs(z) > 2.5:
            reason = f"{row['amount']:.2f} is unusually high for {row['category']}"
        elif iso["flag"]:
            reason = "Unusual pattern compared to your overall spending"
        results[tid] = {
            "is_anomaly": is_anomaly,
            "score": combined_score,
            "reason": reason,
        }

    return results
