import csv
import io
import json
import datetime
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import models
import schemas
from database import engine, get_db
from auth import (
    hash_password, verify_password, create_access_token, get_current_user
)
from ml.categorize import categorizer, DEFAULT_CATEGORIES
from ml.forecast import forecast_next_30_days
from ml.anomaly import detect_anomalies
from ml.persona import classify_persona
from ml.budget import recommend_budgets
from ml.nlquery import answer_query

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Expense Tracker with AI Insights")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/signup", response_model=schemas.Token)
def signup(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    user = models.User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        monthly_income=payload.monthly_income,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.username)
    return {"access_token": token, "username": user.username}


@app.post("/api/auth/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user.username)
    return {"access_token": token, "username": user.username}


@app.get("/api/auth/me")
def me(current_user: models.User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "monthly_income": current_user.monthly_income,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_categories(db: Session, user_id: int) -> list[str]:
    rows = db.query(models.Transaction.category).filter(
        models.Transaction.user_id == user_id
    ).distinct().all()
    existing = {r[0] for r in rows}
    return [c for c in existing if c not in DEFAULT_CATEGORIES]


def _transactions_as_dicts(txns: list[models.Transaction]) -> list[dict]:
    return [
        {
            "id": t.id,
            "date": t.date,
            "description": t.description,
            "amount": t.amount,
            "category": t.category,
        }
        for t in txns
    ]


def _retrain_from_confirmed(db: Session, user_id: int):
    """Feed manually-confirmed categorizations back into the learned model
    so it improves over time for this deployment."""
    rows = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.category_source == "manual",
    ).all()
    if len(rows) >= 5:
        examples = [(r.description, r.category) for r in rows]
        categorizer.fit(examples)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@app.post("/api/transactions", response_model=schemas.TransactionOut)
def create_transaction(
    payload: schemas.TransactionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    known_custom = _user_categories(db, current_user.id)
    category, source, confidence = categorizer.categorize(
        payload.description, payload.category, known_custom
    )
    txn = models.Transaction(
        user_id=current_user.id,
        date=payload.date,
        description=payload.description,
        amount=payload.amount,
        category=category,
        category_source=source,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    background_tasks.add_task(_retrain_from_confirmed, db, current_user.id)
    return txn


@app.post("/api/transactions/upload-csv")
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    content = await file.read()
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    required = {"date", "description", "amount"}
    if not reader.fieldnames or not required.issubset(
        {f.strip().lower() for f in reader.fieldnames}
    ):
        raise HTTPException(
            status_code=400,
            detail="CSV must have columns: date, description, amount",
        )

    known_custom = _user_categories(db, current_user.id)
    created = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        try:
            norm = {k.strip().lower(): v for k, v in row.items()}
            date_val = datetime.datetime.strptime(norm["date"].strip(), "%Y-%m-%d").date()
            amount_val = float(norm["amount"])
            description = norm["description"].strip()
            hint = norm.get("category", "").strip() or None

            category, source, _ = categorizer.categorize(description, hint, known_custom)
            txn = models.Transaction(
                user_id=current_user.id,
                date=date_val,
                description=description,
                amount=abs(amount_val),
                category=category,
                category_source=source,
            )
            db.add(txn)
            created += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")

    db.commit()
    background_tasks.add_task(_retrain_from_confirmed, db, current_user.id)
    return {"created": created, "errors": errors}


@app.get("/api/transactions", response_model=list[schemas.TransactionOut])
def list_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).order_by(models.Transaction.date.desc()).all()

    anomalies = detect_anomalies(_transactions_as_dicts(txns))
    for t in txns:
        info = anomalies.get(t.id)
        if info:
            t.is_anomaly = int(info["is_anomaly"])
            t.anomaly_score = info["score"]
    db.commit()
    return txns


@app.patch("/api/transactions/{txn_id}/category", response_model=schemas.TransactionOut)
def update_category(
    txn_id: int,
    payload: schemas.CategoryOverride,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txn = db.query(models.Transaction).filter(
        models.Transaction.id == txn_id, models.Transaction.user_id == current_user.id
    ).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.category = payload.category
    txn.category_source = "manual"
    db.commit()
    db.refresh(txn)
    _retrain_from_confirmed(db, current_user.id)
    return txn


@app.delete("/api/transactions/{txn_id}")
def delete_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txn = db.query(models.Transaction).filter(
        models.Transaction.id == txn_id, models.Transaction.user_id == current_user.id
    ).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(txn)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@app.get("/api/insights/summary")
def summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).all()
    if not txns:
        return {
            "total_spent": 0, "category_totals": {}, "monthly_trend": [],
            "current_month_total": 0,
        }

    today = datetime.date.today()
    category_totals = defaultdict(float)
    monthly_totals = defaultdict(float)
    current_month_total = 0.0

    for t in txns:
        category_totals[t.category] += t.amount
        month_key = t.date.strftime("%Y-%m")
        monthly_totals[month_key] += t.amount
        if t.date.year == today.year and t.date.month == today.month:
            current_month_total += t.amount

    monthly_trend = [
        {"month": k, "total": round(v, 2)}
        for k, v in sorted(monthly_totals.items())
    ]

    return {
        "total_spent": round(sum(category_totals.values()), 2),
        "category_totals": {k: round(v, 2) for k, v in category_totals.items()},
        "monthly_trend": monthly_trend,
        "current_month_total": round(current_month_total, 2),
    }


@app.get("/api/insights/forecast")
def forecast(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).all()
    return forecast_next_30_days(_transactions_as_dicts(txns))


@app.get("/api/insights/persona")
def persona(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).all()
    category_totals = defaultdict(float)
    for t in txns:
        category_totals[t.category] += t.amount
    return classify_persona(category_totals)


@app.get("/api/insights/budget")
def budget(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).all()
    if not txns:
        return []
    dates = [t.date for t in txns]
    span_months = max(
        (max(dates).year - min(dates).year) * 12 + (max(dates).month - min(dates).month) + 1,
        1,
    )
    category_totals = defaultdict(float)
    for t in txns:
        category_totals[t.category] += t.amount
    category_avg = {k: v / span_months for k, v in category_totals.items()}
    return recommend_budgets(current_user.monthly_income, category_avg)


@app.get("/api/insights/heatmap")
def heatmap(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id,
        models.Transaction.date >= datetime.date(year, month, 1),
    ).all()
    daily_totals = defaultdict(float)
    for t in txns:
        if t.date.year == year and t.date.month == month:
            daily_totals[t.date.day] += t.amount
    return {"year": year, "month": month, "daily_totals": daily_totals}


@app.post("/api/insights/ask")
def ask(
    payload: schemas.NLQuery,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).all()
    return answer_query(payload.question, _transactions_as_dicts(txns))


@app.get("/api/categories")
def categories(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    custom = _user_categories(db, current_user.id)
    return {"default": DEFAULT_CATEGORIES, "custom": custom}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the vanilla frontend from the same process (single-service deploy).
# Must be registered last so /api/* routes keep priority.
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
