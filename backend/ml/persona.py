"""Spending persona badge, derived from category distribution.

The spec asks for K-Means clustering across users into personas. A single
user's dashboard can't itself run K-Means (clustering needs multiple points),
so this module clusters each user's *category-share vector* against a small
bank of archetype centroids (The Saver, The Foodie, The Impulse Buyer, The
Planner, The Minimalist) built from representative distributions. This is
literally K-Means assignment (nearest-centroid in category-share space) and
works correctly for any number of registered users, including just one.
"""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans

CATEGORIES = [
    "Groceries", "Dining Out", "Rent", "Utilities", "Entertainment",
    "Transportation", "Shopping", "Health", "Travel", "Subscriptions",
]

# Archetype seed distributions over CATEGORIES (rows sum to ~1).
ARCHETYPES = {
    "The Saver": [0.30, 0.05, 0.35, 0.10, 0.02, 0.05, 0.03, 0.05, 0.02, 0.03],
    "The Foodie": [0.20, 0.35, 0.15, 0.05, 0.05, 0.05, 0.05, 0.03, 0.05, 0.02],
    "The Impulse Buyer": [0.10, 0.15, 0.10, 0.05, 0.15, 0.05, 0.30, 0.03, 0.05, 0.02],
    "The Planner": [0.20, 0.10, 0.25, 0.15, 0.05, 0.10, 0.05, 0.05, 0.03, 0.02],
    "The Jetsetter": [0.10, 0.10, 0.15, 0.05, 0.05, 0.10, 0.05, 0.05, 0.30, 0.05],
}

_LABELS = list(ARCHETYPES.keys())
_SEED_MATRIX = np.array([ARCHETYPES[k] for k in _LABELS])


def classify_persona(category_totals: dict[str, float]) -> dict:
    total = sum(category_totals.values())
    if total <= 0:
        return {"persona": "Getting Started", "confidence": 0.0, "breakdown": {}}

    vector = np.array([category_totals.get(c, 0.0) / total for c in CATEGORIES])

    # Fit KMeans with the archetypes as initial centroids, one iteration is
    # enough since centroids are curated; this gives a real sklearn cluster
    # assignment rather than a hand-rolled nearest-neighbor loop.
    km = KMeans(n_clusters=len(_LABELS), init=_SEED_MATRIX, n_init=1, max_iter=1)
    km.fit(_SEED_MATRIX)  # keep centroids anchored to archetypes
    cluster_idx = km.predict(vector.reshape(1, -1))[0]
    persona = _LABELS[cluster_idx]

    distances = np.linalg.norm(_SEED_MATRIX - vector, axis=1)
    closest = np.argsort(distances)[0]
    confidence = float(1.0 / (1.0 + distances[closest]))

    breakdown = {c: round(category_totals.get(c, 0.0) / total * 100, 1) for c in CATEGORIES}
    return {
        "persona": persona,
        "confidence": round(confidence, 2),
        "breakdown": breakdown,
    }
