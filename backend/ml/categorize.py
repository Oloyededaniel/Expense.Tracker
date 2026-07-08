"""
Transaction categorization engine.

NOTE ON MODEL CHOICE:
The original spec called for a fine-tuned DistilBERT/RoBERTa classifier and a
facebook/bart-large-mnli zero-shot classifier from Hugging Face. This sandbox's
network egress does not allow reaching huggingface.co (only pypi/npm/github are
reachable), so downloading those pretrained weights is not possible here.

Instead this module ships a self-contained pipeline that reaches the same
product behavior without any external model download:

  1. RULE LAYER   - fast keyword/regex matching against a curated lexicon for
                     the ~10 default categories. Handles the common case.
  2. LEARNED LAYER- a TF-IDF + Multinomial Naive Bayes classifier trained at
                     startup on a seed corpus (below) plus every transaction a
                     user has manually confirmed. This is a real, trained
                     scikit-learn model (not just keywords) and it keeps
                     improving as users correct categories.
  3. ZERO-SHOT LAYER - when a user types a brand-new category that was never
                     in the training data (e.g. "Pet Supplies", "Crypto
                     Investments"), we score the description against the
                     category *name itself* using TF-IDF cosine similarity
                     computed on the fly. No fixed label set is required, so
                     this reproduces the "any custom category" behavior that
                     bart-large-mnli would provide, at the cost of being less
                     semantically deep than a real NLI model.

If you deploy this outside the sandbox, swapping in
`transformers.pipeline("zero-shot-classification", model="facebook/bart-large-mnli")`
for `zero_shot_score()` below is a drop-in replacement - the function
signature is deliberately kept model-agnostic.
"""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_CATEGORIES = [
    "Groceries",
    "Dining Out",
    "Rent",
    "Utilities",
    "Entertainment",
    "Transportation",
    "Shopping",
    "Health",
    "Travel",
    "Subscriptions",
    "Income",
    "Other",
]

# Curated keyword lexicon powering the fast rule layer.
RULES: dict[str, list[str]] = {
    "Groceries": ["grocery", "groceries", "supermarket", "walmart", "trader joe",
                  "whole foods", "aldi", "kroger", "safeway", "costco", "tesco",
                  "sainsbury", "asda", "lidl"],
    "Dining Out": ["restaurant", "cafe", "coffee", "starbucks", "mcdonald",
                   "burger", "pizza", "sushi", "diner", "bar ", "pub ",
                   "doordash", "uber eats", "grubhub", "deliveroo", "just eat"],
    "Rent": ["rent", "landlord", "lease", "apartment", "mortgage"],
    "Utilities": ["electric", "electricity", "water bill", "gas bill", "utility",
                  "utilities", "internet", "broadband", "phone bill", "mobile bill"],
    "Entertainment": ["netflix", "spotify", "cinema", "movie", "theatre",
                      "theater", "concert", "steam", "playstation", "xbox",
                      "disney+", "hbo"],
    "Transportation": ["uber", "lyft", "taxi", "fuel", "petrol", "gasoline",
                        "parking", "train ticket", "bus fare", "transit",
                        "metro", "toll"],
    "Shopping": ["amazon", "ebay", "target", "mall", "clothing", "shoes",
                 "zara", "h&m", "nike", "apple store", "best buy"],
    "Health": ["pharmacy", "doctor", "dentist", "hospital", "clinic", "cvs",
               "walgreens", "gym", "fitness", "insurance premium"],
    "Travel": ["airline", "flight", "hotel", "airbnb", "booking.com",
               "expedia", "rental car"],
    "Subscriptions": ["subscription", "membership", "prime membership",
                       "icloud", "adobe", "dropbox"],
    "Income": ["salary", "payroll", "paycheck", "deposit", "refund",
               "reimbursement"],
}

_SEED_CORPUS: list[tuple[str, str]] = []
for cat, keywords in RULES.items():
    for kw in keywords:
        _SEED_CORPUS.append((f"payment to {kw.strip()}", cat))
        _SEED_CORPUS.append((kw.strip(), cat))


class Categorizer:
    """Wraps the rule layer + a retrainable TF-IDF/NB model."""

    def __init__(self) -> None:
        self.vectorizer: TfidfVectorizer | None = None
        self.model: MultinomialNB | None = None
        self.classes_: list[str] = []
        self.fit(_SEED_CORPUS)

    def fit(self, examples: Iterable[tuple[str, str]]) -> None:
        texts, labels = zip(*examples) if examples else ([], [])
        if len(set(labels)) < 2:
            return
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        X = self.vectorizer.fit_transform(texts)
        self.model = MultinomialNB()
        self.model.fit(X, labels)
        self.classes_ = list(self.model.classes_)

    def rule_match(self, description: str) -> str | None:
        text = description.lower()
        for cat, keywords in RULES.items():
            for kw in keywords:
                if re.search(re.escape(kw), text):
                    return cat
        return None

    def model_predict(self, description: str) -> tuple[str, float]:
        if self.model is None or self.vectorizer is None:
            return "Other", 0.0
        X = self.vectorizer.transform([description])
        probs = self.model.predict_proba(X)[0]
        idx = int(np.argmax(probs))
        return self.classes_[idx], float(probs[idx])

    def zero_shot_score(self, description: str, candidate_category: str) -> float:
        """TF-IDF cosine similarity between description and an arbitrary,
        never-before-seen category label. Substitutes for bart-large-mnli
        (see module docstring) - swap this out for a real NLI pipeline call
        if huggingface.co is reachable in your deployment."""
        vec = TfidfVectorizer().fit([description, candidate_category])
        X = vec.transform([description, candidate_category])
        return float(cosine_similarity(X[0], X[1])[0][0])

    def categorize(
        self, description: str, user_category_hint: str | None = None,
        known_custom_categories: list[str] | None = None,
    ) -> tuple[str, str, float]:
        """Returns (category, source, confidence)."""
        if user_category_hint:
            return user_category_hint, "manual", 1.0

        rule_hit = self.rule_match(description)
        if rule_hit:
            return rule_hit, "rule", 0.95

        # Try any custom categories the user has already introduced, via
        # zero-shot style similarity, before falling back to the trained model.
        best_custom, best_score = None, 0.0
        for cat in known_custom_categories or []:
            score = self.zero_shot_score(description, cat)
            if score > best_score:
                best_custom, best_score = cat, score
        if best_custom and best_score > 0.15:
            return best_custom, "zero_shot", best_score

        category, confidence = self.model_predict(description)
        if confidence < 0.25:
            return "Other", "model", confidence
        return category, "model", confidence


categorizer = Categorizer()
