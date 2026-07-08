"""Smart budget recommendations.

Blends two signals: general personal-finance guardrails (percentage of
income by category, loosely inspired by the 50/30/20 rule) and the user's
own trailing 3-month average per category, so the recommendation is
personalized rather than generic.
"""
from __future__ import annotations

# Suggested ceiling as a fraction of monthly income, per category.
INCOME_GUARDRAILS = {
    "Rent": 0.30,
    "Groceries": 0.12,
    "Dining Out": 0.06,
    "Utilities": 0.08,
    "Entertainment": 0.05,
    "Transportation": 0.10,
    "Shopping": 0.06,
    "Health": 0.05,
    "Travel": 0.05,
    "Subscriptions": 0.03,
}


def recommend_budgets(monthly_income: float, category_monthly_avg: dict[str, float]) -> list[dict]:
    recommendations = []
    for category, avg_spend in category_monthly_avg.items():
        if category in ("Income", "Other"):
            continue
        guardrail_pct = INCOME_GUARDRAILS.get(category, 0.04)
        guardrail_amount = monthly_income * guardrail_pct if monthly_income > 0 else None

        if guardrail_amount is not None:
            # personalized recommendation: midpoint between guardrail and
            # actual recent average, nudged toward the guardrail if the user
            # is overspending relative to income.
            recommended = round((guardrail_amount * 0.6 + avg_spend * 0.4), 2)
        else:
            recommended = round(avg_spend * 0.9, 2)

        over_guardrail = guardrail_amount is not None and avg_spend > guardrail_amount
        recommendations.append({
            "category": category,
            "current_avg_monthly": round(avg_spend, 2),
            "recommended_budget": recommended,
            "income_guardrail": round(guardrail_amount, 2) if guardrail_amount else None,
            "note": (
                f"Your {category} spending is above the typical guardrail for "
                f"your income - consider trimming toward ${recommended:,.0f}/month."
                if over_guardrail else
                f"You're within a healthy range for {category}."
            ),
        })
    return sorted(recommendations, key=lambda r: -r["current_avg_monthly"])
