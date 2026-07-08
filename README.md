# Ledger & Lens — Smart Expense Tracker with AI Insights

A full-stack expense tracker: FastAPI + SQLite backend, a dependency-free
vanilla HTML/JS + Chart.js frontend, and a real (if lightweight) ML stack for
categorization, forecasting, anomaly detection, and persona clustering.

## Read this first: three deliberate substitutions

Your spec named specific pretrained models (DistilBERT/RoBERTa, `facebook/bart-large-mnli`,
Prophet) and an LLM API (Groq/OpenAI) for the NL query box. This project was built
and tested inside a sandboxed environment whose network egress only reaches
pypi/npm/github — **not** `huggingface.co` or an LLM provider, and no API key was
configured. So rather than leaving those features as dead stubs, each one was
reimplemented with a real, working equivalent that you can swap out in production:

| Spec asked for | What's actually running | Where to swap it in |
|---|---|---|
| Fine-tuned DistilBERT/RoBERTa categorizer | TF-IDF + Multinomial Naive Bayes, trained at startup and retrained on every manual correction | `backend/ml/categorize.py` — `Categorizer.model_predict()` |
| `facebook/bart-large-mnli` zero-shot for custom categories | TF-IDF cosine similarity between the description and the category name, computed on the fly | `backend/ml/categorize.py` — `zero_shot_score()` |
| Prophet / ARIMA 30-day forecast | Linear trend (`numpy.polyfit`) + day-of-week seasonality + residual-based confidence band | `backend/ml/forecast.py` |
| Groq/OpenAI-powered NL query box | Deterministic regex/keyword parser over pandas | `backend/ml/nlquery.py` — `answer_query()` |

Anomaly detection (Z-score + **real** `sklearn.ensemble.IsolationForest`) and
persona clustering (**real** `sklearn.cluster.KMeans`) are exactly as specced —
those don't need external model downloads.

Every substitution is also documented as a code comment at the top of its
module, and the function signatures were kept model-agnostic so dropping in
the original heavier models later is a backend-only change, no frontend or
API contract changes required.

## Project structure

```
expense-tracker/
├── backend/
│   ├── main.py            # FastAPI app, all REST endpoints
│   ├── models.py          # SQLAlchemy models: users, transactions, insights
│   ├── schemas.py         # Pydantic request/response schemas
│   ├── database.py        # SQLite engine + session
│   ├── auth.py            # bcrypt hashing + JWT session tokens
│   ├── requirements.txt
│   └── ml/
│       ├── categorize.py  # rule layer + trained NB model + zero-shot fallback
│       ├── forecast.py    # 30-day forecast + riskiest-week detection
│       ├── anomaly.py     # Z-score + Isolation Forest
│       ├── persona.py     # KMeans spending persona
│       ├── budget.py      # income-aware budget recommendations
│       └── nlquery.py     # "Ask your ledger" chat parser
└── frontend/
    ├── index.html         # single-page app shell (vanilla JS, no build step)
    ├── app.js              # all frontend logic + Chart.js wiring
    ├── manifest.json       # PWA manifest
    ├── sw.js               # service worker (offline app shell)
    └── icon.svg
```

## Running it locally

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API is now live at `http://127.0.0.1:8000`. A SQLite file
(`expense_tracker.db`) is created automatically on first run. Interactive API
docs are at `http://127.0.0.1:8000/docs`.

Set a real secret in production:
```bash
export APP_SECRET_KEY="a-long-random-string"
```

### 2. Frontend

The frontend is plain static files — no npm install, no build step. Serve it
with any static file server, e.g.:

```bash
cd frontend
python3 -m http.server 5500
```

Then open `http://127.0.0.1:5500` in your browser. `app.js` is hardcoded to
call the backend at `http://127.0.0.1:8000` — change the `API_BASE` constant
at the top of `app.js` if you deploy the backend elsewhere.

### 3. Try it out

1. Sign up with a username, password, and monthly income (used for budget suggestions).
2. Add a few manual transactions, or upload a CSV with `date,description,amount` columns.
3. Try leaving the category blank on a transaction — the AI will categorize it.
4. Type a brand-new category name (like "Pet Supplies") on one transaction, then
   add a second transaction whose description overlaps with that category name
   but no category set — it should get zero-shot-matched to your custom category.
5. Visit **AI Insights** for the 30-day forecast, persona badge, and budget table.
6. Visit **Ask Your Ledger** and try "How much did I spend on coffee last month?"

## Known limitations (by design, given the substitutions above)

- The zero-shot TF-IDF similarity is much shallower than a real NLI model —
  it works well when the description and category share vocabulary, less
  well for purely semantic matches (e.g. "kibble" → "Pet Supplies" without
  the word "pet" appearing anywhere).
- The forecast model is intentionally simple (linear trend + weekday
  seasonality). It needs at least ~7 days of transaction history to produce
  a forecast, and accuracy improves with more history.
- The NL query box only understands a handful of question shapes ("how much
  did I spend on X [timeframe]", "top N most expensive"). It's a rule parser,
  not a language model.
- Auth is intentionally lightweight per the spec (no password reset, no email
  verification) — don't use this auth layer as-is for a real production app
  handling real financial data.

## Tech stack actually used

**Backend:** FastAPI (async), SQLAlchemy ORM, SQLite, PyJWT + passlib/bcrypt for auth.
**ML:** scikit-learn (TF-IDF, Naive Bayes, Isolation Forest, KMeans), pandas, numpy.
**Frontend:** Vanilla HTML/CSS/JS (chosen over React for a zero-build-step,
single-file-per-concern deliverable) + Chart.js via CDN, installable as a PWA.
# Expense.Tracker
