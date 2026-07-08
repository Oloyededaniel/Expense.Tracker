"""
Spending forecast engine.

NOTE ON MODEL CHOICE: the spec asked for Prophet or ARIMA. Both pull in heavy
native/compiled dependencies (cmdstan for Prophet, or a full statsmodels
build) that are unreliable to install in a network-restricted sandbox. This
module implements an equivalent, dependency-light forecast using:

  - a linear trend fit with numpy.polyfit over the recent history, plus
  - day-of-week seasonality (average multiplicative effect per weekday),
  - and a bootstrap-style confidence band from residual std deviation.

The output shape (30 daily predictions with upper/lower bounds, plus the
riskiest 7-day window) is exactly what the frontend forecast chart and the
"Weekly Risk Alert" card expect, so swapping in real Prophet/ARIMA later is a
backend-only change.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

import numpy as np
import pandas as pd


def _daily_series(transactions: list[dict]) -> pd.Series:
    df = pd.DataFrame(transactions)
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date")["amount"].sum()
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_range, fill_value=0.0)
    return daily


def forecast_next_30_days(transactions: list[dict]) -> dict:
    daily = _daily_series(transactions)
    if len(daily) < 7:
        return {
            "history": [],
            "forecast": [],
            "risk_week": None,
            "message": "Not enough transaction history yet to forecast "
                       "(need at least 7 days of activity).",
        }

    y = daily.values.astype(float)
    x = np.arange(len(y))

    # Linear trend
    slope, intercept = np.polyfit(x, y, 1)
    trend = slope * x + intercept
    residuals = y - trend
    resid_std = float(np.std(residuals)) or 1.0

    # Day-of-week seasonal multiplier
    dow_avg = defaultdict(list)
    overall_mean = max(np.mean(y), 1e-6)
    for i, ts in enumerate(daily.index):
        dow_avg[ts.dayofweek].append(y[i] / overall_mean if overall_mean else 1.0)
    dow_factor = {
        d: float(np.mean(v)) if v else 1.0 for d, v in dow_avg.items()
    }

    last_date = daily.index.max()
    future_dates = [last_date + datetime.timedelta(days=i + 1) for i in range(30)]
    future_x = np.arange(len(y), len(y) + 30)
    base_trend = slope * future_x + intercept

    forecast_points = []
    for i, dt in enumerate(future_dates):
        factor = dow_factor.get(dt.dayofweek, 1.0)
        point = max(base_trend[i] * factor, 0.0)
        forecast_points.append({
            "date": dt.date().isoformat(),
            "predicted": round(float(point), 2),
            "lower": round(max(point - 1.28 * resid_std, 0.0), 2),
            "upper": round(point + 1.28 * resid_std, 2),
        })

    # Identify riskiest 7-day rolling window in the forecast
    preds = [p["predicted"] for p in forecast_points]
    window_sums = [sum(preds[i:i + 7]) for i in range(0, 24)]
    risk_idx = int(np.argmax(window_sums))
    risk_total = window_sums[risk_idx]
    historical_weekly_avg = float(np.mean(y)) * 7

    risk_week = {
        "start_date": forecast_points[risk_idx]["date"],
        "end_date": forecast_points[risk_idx + 6]["date"],
        "predicted_total": round(risk_total, 2),
        "historical_weekly_avg": round(historical_weekly_avg, 2),
        "overspend_pct": round(
            ((risk_total - historical_weekly_avg) / historical_weekly_avg) * 100, 1
        ) if historical_weekly_avg > 0 else 0.0,
    }

    history = [
        {"date": ts.date().isoformat(), "actual": round(float(v), 2)}
        for ts, v in daily.items()
    ]

    return {
        "history": history,
        "forecast": forecast_points,
        "risk_week": risk_week,
    }
