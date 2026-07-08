"""
Natural language query engine for the dashboard chat box.

NOTE ON MODEL CHOICE: the spec suggested calling out to an LLM (Groq/OpenAI)
to translate free text into SQL. This sandbox has no API key configured and
no route to those providers, so this module uses a deterministic rule/regex
parser instead. It supports the two example queries from the spec ("How much
did I spend on X last month/week?" and "Show me my top N most expensive
Y") plus a handful of common variants, and returns a small structured result
the frontend can render as text + a mini chart.

If you deploy with an OPENAI_API_KEY or GROQ_API_KEY, replace `answer_query()`
with a call that asks the LLM to emit JSON matching the same
{intent, filters, ...} shape used internally here - the rest of the pipeline
(the pandas filtering logic) can stay as-is.
"""
from __future__ import annotations

import re
import datetime
import pandas as pd

TIME_PATTERNS = {
    "last month": 30,
    "this month": 30,
    "last week": 7,
    "this week": 7,
    "last 3 months": 90,
    "last quarter": 90,
    "last year": 365,
}


def _filter_by_time(df: pd.DataFrame, question: str) -> pd.DataFrame:
    q = question.lower()
    for phrase, days in TIME_PATTERNS.items():
        if phrase in q:
            cutoff = datetime.date.today() - datetime.timedelta(days=days)
            return df[df["date"] >= cutoff]
    return df


def _find_category_or_keyword(df: pd.DataFrame, question: str) -> tuple[pd.DataFrame, str | None]:
    q = question.lower()
    categories = df["category"].unique().tolist()
    for cat in categories:
        if cat.lower() in q:
            return df[df["category"].str.lower() == cat.lower()], cat
    # fall back to keyword match against description text
    words = re.findall(r"[a-zA-Z']+", q)
    stopwords = {"how", "much", "did", "i", "spend", "on", "last", "month",
                 "week", "show", "me", "my", "top", "most", "expensive", "the",
                 "a", "in", "of", "for", "this", "year", "quarter"}
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    if keywords:
        pattern = "|".join(re.escape(k) for k in keywords)
        mask = df["description"].str.lower().str.contains(pattern, regex=True)
        if mask.any():
            return df[mask], keywords[0]
    return df, None


def answer_query(question: str, transactions: list[dict]) -> dict:
    if not transactions:
        return {"answer": "You don't have any transactions yet.", "rows": []}

    df = pd.DataFrame(transactions)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    q = question.lower()

    time_filtered = _filter_by_time(df, q)

    top_n_match = re.search(r"top\s+(\d+)", q)
    if "expensive" in q or "biggest" in q or top_n_match:
        n = int(top_n_match.group(1)) if top_n_match else 5
        subset, matched_cat = _find_category_or_keyword(time_filtered, q)
        top = subset.sort_values("amount", ascending=False).head(n)
        label = matched_cat or "matching transactions"
        answer = (
            f"Here are your top {min(n, len(top))} most expensive "
            f"{label} entries."
            if len(top) else f"I couldn't find any transactions matching that."
        )
        rows = top[["date", "description", "amount", "category"]].to_dict("records")
        for r in rows:
            r["date"] = r["date"].isoformat()
        return {"answer": answer, "rows": rows}

    # default: "how much did I spend on X [timeframe]"
    subset, matched_cat = _find_category_or_keyword(time_filtered, q)
    total = float(subset["amount"].sum())
    count = len(subset)
    label = matched_cat or "those transactions"
    timeframe = "in that period"
    for phrase in TIME_PATTERNS:
        if phrase in q:
            timeframe = phrase
            break
    answer = (
        f"You spent ${total:,.2f} on {label} {timeframe} across {count} "
        f"transaction{'s' if count != 1 else ''}."
        if count else f"I couldn't find any spending on {label}."
    )
    rows = subset.sort_values("date", ascending=False).head(20)[
        ["date", "description", "amount", "category"]
    ].to_dict("records")
    for r in rows:
        r["date"] = r["date"].isoformat()
    return {"answer": answer, "rows": rows}
