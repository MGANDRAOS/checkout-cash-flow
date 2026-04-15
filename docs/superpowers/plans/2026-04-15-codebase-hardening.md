# Codebase Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove hardcoded credentials, excise all finance/accounting surface (except `/finance/summary`, rebranded as "Sales vs Spending"), and centralize configuration in a single `.env` file with fail-fast validation — so the codebase becomes safe to ship as an on-prem installer.

**Architecture:** Introduce one new module, `config.py`, that reads `.env` at import time, validates every required key, and exposes validated constants. Migrate all code that currently uses `os.getenv(...)` with fallback defaults for secrets to import from `config`. Rewrite `main.py` to drop ~1,100 lines of finance routes and all references to deleted models. Delete the corresponding routes, templates, and models. No reporting query or dashboard UI changes.

**Tech Stack:** Python 3, Flask 3, Flask-SQLAlchemy, python-dotenv (already in requirements), pyodbc (for MSSQL), pytest (existing test harness).

**Spec:** [docs/superpowers/specs/2026-04-15-codebase-hardening-design.md](../specs/2026-04-15-codebase-hardening-design.md)

---

## Task 1: Add test environment fixture

The current `conftest.py` is empty. New tests for `config.py` will import the module, which validates env vars at import time. Without a fixture setting those vars first, every test suite run will fail. Populate dummy values before any import.

**Files:**
- Modify: `conftest.py`

- [ ] **Step 1: Replace `conftest.py` with dummy-env fixture**

Write this exact content to `conftest.py`:

```python
"""
Global pytest fixtures.

Populates required environment variables with dummy values BEFORE any test
module is imported. Required because `config.py` validates env vars on import
and many modules transitively import `config`.
"""
import os

_DUMMY_ENV = {
    "MSSQL_DRIVER": "ODBC Driver 17 for SQL Server",
    "MSSQL_SERVER": "test.example.com,1433",
    "MSSQL_DATABASE": "TESTDB",
    "MSSQL_USERNAME": "test_user",
    "MSSQL_PASSWORD": "test_password",
    "SECRET_KEY": "test-secret-key",
    "APP_USERNAME": "admin",
    "APP_PASSWORD": "admin-password",
    "VISUAL_CROSSING_KEY": "test-vc-key",
    "OPENAI_API_KEY": "test-openai-key",
    "USD_EXCHANGE_RATE": "89000",
    "CURRENCY": "LBP",
    "MIN_TRACKING_DATE": "2026-04-11",
}

for key, value in _DUMMY_ENV.items():
    os.environ.setdefault(key, value)
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest -v`
Expected: all tests in `tests/test_pos_dates.py` and `tests/test_cache_utils.py` pass; no import errors.

- [ ] **Step 3: Commit**

```bash
git add conftest.py
git commit -m "test: seed dummy env vars in conftest for upcoming config module"
```

---

## Task 2: Create `config.py` with fail-fast validation (TDD)

`config.py` is the single source of truth for required environment values. On import it validates all required keys, raising `RuntimeError` with a clear multi-line message if any are missing. It exposes validated values as module attributes.

**Files:**
- Create: `tests/test_config.py`
- Create: `config.py`

- [ ] **Step 1: Write the failing test**

Write this exact content to `tests/test_config.py`:

```python
"""Tests for config.py — env validation and value exposure."""
import importlib
import os
import sys
from datetime import date

import pytest


def _reload_config():
    """Force a fresh import of config so current env is re-read."""
    if "config" in sys.modules:
        del sys.modules["config"]
    return importlib.import_module("config")


def test_all_required_present_loads_successfully(monkeypatch):
    """With every required key set, config imports and exposes values."""
    cfg = _reload_config()
    assert cfg.MSSQL_SERVER == "test.example.com,1433"
    assert cfg.MSSQL_DATABASE == "TESTDB"
    assert cfg.MSSQL_USERNAME == "test_user"
    assert cfg.MSSQL_PASSWORD == "test_password"
    assert cfg.SECRET_KEY == "test-secret-key"
    assert cfg.USD_EXCHANGE_RATE == 89000.0
    assert cfg.CURRENCY == "LBP"
    assert cfg.MIN_TRACKING_DATE == date(2026, 4, 11)


def test_missing_mssql_password_raises(monkeypatch):
    """A missing required secret raises RuntimeError naming that key."""
    monkeypatch.delenv("MSSQL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        _reload_config()
    assert "MSSQL_PASSWORD" in str(exc_info.value)


def test_missing_openai_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        _reload_config()
    assert "OPENAI_API_KEY" in str(exc_info.value)


def test_blank_required_value_raises(monkeypatch):
    """Empty-string is treated the same as missing."""
    monkeypatch.setenv("MSSQL_SERVER", "")
    with pytest.raises(RuntimeError) as exc_info:
        _reload_config()
    assert "MSSQL_SERVER" in str(exc_info.value)


def test_multiple_missing_keys_listed_together(monkeypatch):
    """All missing keys are reported at once, not one at a time."""
    monkeypatch.delenv("MSSQL_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        _reload_config()
    msg = str(exc_info.value)
    assert "MSSQL_PASSWORD" in msg
    assert "SECRET_KEY" in msg


def test_paid_item_types_is_list(monkeypatch):
    cfg = _reload_config()
    assert isinstance(cfg.PAID_ITEM_TYPES, list)
    assert "Generator" in cfg.PAID_ITEM_TYPES
    assert "Restock" in cfg.PAID_ITEM_TYPES


def test_database_url_optional_has_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cfg = _reload_config()
    assert cfg.DATABASE_URL.startswith("sqlite:")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Create `config.py`**

Write this exact content to `config.py`:

```python
"""
Centralized configuration loader.

Reads environment variables (from .env via python-dotenv, loaded in main.py
before this module is imported) and validates every required key. Raises
RuntimeError at import time if any required secret is missing or blank, so
the app fails fast on startup rather than silently running with defaults.

All validated values are exposed as module attributes. Optional values fall
back to documented defaults.
"""
import os
import sys
from datetime import date, datetime
from typing import List

_REQUIRED_KEYS: List[str] = [
    "MSSQL_DRIVER",
    "MSSQL_SERVER",
    "MSSQL_DATABASE",
    "MSSQL_USERNAME",
    "MSSQL_PASSWORD",
    "SECRET_KEY",
    "APP_USERNAME",
    "APP_PASSWORD",
    "VISUAL_CROSSING_KEY",
    "OPENAI_API_KEY",
    "USD_EXCHANGE_RATE",
    "CURRENCY",
    "MIN_TRACKING_DATE",
]


def _validate_required() -> None:
    missing = [k for k in _REQUIRED_KEYS if not os.getenv(k, "").strip()]
    if missing:
        lines = ["FATAL: Required configuration missing:"]
        lines.extend(f"  - {k}" for k in missing)
        lines.append("")
        lines.append("Copy .env.template to .env and fill in all values, then restart.")
        raise RuntimeError("\n".join(lines))


_validate_required()


# ---- MSSQL ----
MSSQL_DRIVER = os.environ["MSSQL_DRIVER"]
MSSQL_SERVER = os.environ["MSSQL_SERVER"]
MSSQL_DATABASE = os.environ["MSSQL_DATABASE"]
MSSQL_USERNAME = os.environ["MSSQL_USERNAME"]
MSSQL_PASSWORD = os.environ["MSSQL_PASSWORD"]

# ---- Flask ----
SECRET_KEY = os.environ["SECRET_KEY"]
APP_USERNAME = os.environ["APP_USERNAME"]
APP_PASSWORD = os.environ["APP_PASSWORD"]

# ---- Third-party APIs ----
VISUAL_CROSSING_KEY = os.environ["VISUAL_CROSSING_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# ---- Locale ----
USD_EXCHANGE_RATE: float = float(os.environ["USD_EXCHANGE_RATE"])
CURRENCY: str = os.environ["CURRENCY"]
MIN_TRACKING_DATE: date = datetime.strptime(
    os.environ["MIN_TRACKING_DATE"], "%Y-%m-%d"
).date()

# ---- Optional ----
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///checkout.db")

# ---- Business constants ----
# Controlled payment types for manual paid items in the Sales vs Spending page.
PAID_ITEM_TYPES: List[str] = [
    "Generator",
    "EDL",
    "Wifi",
    "Restock",
    "Salary",
    "Other",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config.py with fail-fast env validation"
```

---

## Task 3: Migrate `helpers_intelligence._conn_str()` to use config

Replace the hardcoded credential defaults in `_conn_str()` with imports from `config`. Strip the commented-out alternative block.

**Files:**
- Modify: `helpers_intelligence.py:15-45`

- [ ] **Step 1: Replace the connection block**

Open `helpers_intelligence.py`. Replace lines 15 through 45 (from the `# ---------- Connection ----------` header through the `def _connect():` definition inclusive) with exactly:

```python
# ---------- Connection ----------
import config


def _conn_str() -> str:
    return (
        f"Driver={{{config.MSSQL_DRIVER}}};"
        f"Server={config.MSSQL_SERVER};"
        f"Database={config.MSSQL_DATABASE};"
        f"Uid={config.MSSQL_USERNAME};"
        f"Pwd={config.MSSQL_PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
    )


def _connect():
    return pyodbc.connect(_conn_str())
```

Also delete the now-unused `import os` at the top of the file **only if** no other call in `helpers_intelligence.py` uses `os.` — run `grep -n "os\." helpers_intelligence.py` first; if it returns any hits other than the line you're deleting, leave the import alone.

- [ ] **Step 2: Verify no hardcoded secrets remain in helpers_intelligence.py**

Run: `grep -niE "password|pwd=|uid=|andr@o" helpers_intelligence.py`
Expected: no output (no matches).

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add helpers_intelligence.py
git commit -m "refactor: _conn_str reads MSSQL creds from config, no fallbacks"
```

---

## Task 4: Fail-fast guards in helpers_weather and helpers_ai

These modules currently read `VC_API_KEY` and `OPENAI_API_KEY` via `os.getenv` with no default. Because `config.py` already validates these, importing `config` at the top of each module ensures the app refuses to start if either is missing. Switch the reads to come from `config`.

**Files:**
- Modify: `helpers_weather.py:1-15`
- Modify: `helpers_ai.py:1-15`

- [ ] **Step 1: Update helpers_weather.py**

Open `helpers_weather.py`. Find the line:

```python
VC_API_KEY = os.getenv("VISUAL_CROSSING_KEY")  # store in .env or environment
```

Replace it with:

```python
import config
VC_API_KEY = config.VISUAL_CROSSING_KEY
```

- [ ] **Step 2: Update helpers_ai.py**

Open `helpers_ai.py`. Find the line:

```python
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

Replace it with:

```python
import config
client = OpenAI(api_key=config.OPENAI_API_KEY)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add helpers_weather.py helpers_ai.py
git commit -m "refactor: weather and ai helpers read API keys from config"
```

---

## Task 5: Create `.env.template` and update README

The template documents every key the app needs. It is committed so customers (and the future installer wizard) know exactly what to populate.

**Files:**
- Create: `.env.template`
- Modify: `README.md`

- [ ] **Step 1: Create `.env.template`**

Write this exact content to `.env.template`:

```
# --- MSSQL / POS database (required) ---
MSSQL_DRIVER=ODBC Driver 17 for SQL Server
MSSQL_SERVER=
MSSQL_DATABASE=
MSSQL_USERNAME=
MSSQL_PASSWORD=

# --- Flask app (required) ---
SECRET_KEY=
APP_USERNAME=
APP_PASSWORD=

# --- Local SQLite (optional; defaults to sqlite:///checkout.db) ---
DATABASE_URL=

# --- Third-party APIs (required) ---
VISUAL_CROSSING_KEY=
OPENAI_API_KEY=

# --- Locale / currency (required) ---
USD_EXCHANGE_RATE=
CURRENCY=LBP
MIN_TRACKING_DATE=2026-04-11
```

- [ ] **Step 2: Replace README.md**

Write this exact content to `README.md`:

```markdown
# Checkout Cash Flow — Reporting Dashboard

POS reporting dashboard (Flask + MSSQL) for a single retail shop.

## Setup

1. Install Python 3.11+ and the ODBC Driver 17 for SQL Server.
2. Create and activate a virtualenv.
3. `pip install -r requirements.txt`
4. `cp .env.template .env` and fill in every value. The app will refuse to
   start if any required key is missing or blank.
5. `python main.py`

## Configuration

All secrets and per-shop settings live in `.env`. See `.env.template` for
the canonical list of keys. Missing or blank required keys cause a startup
error listing the offending keys.

## Tests

`python -m pytest`
```

- [ ] **Step 3: Commit**

```bash
git add .env.template README.md
git commit -m "docs: add .env.template and setup instructions"
```

---

## Task 6: Rewrite `main.py`

Delete all finance routes except `/finance/summary` and `POST /finance/summary/add-paid-item`. Delete the root `/` dashboard route so the intelligence blueprint serves root. Migrate constants to `config`. Drop imports of deleted models and helpers. Remove `invoices_bp` registration.

Because `main.py` is 1,475 lines and the edits span ~20 routes, this task rewrites the file in one `Write`. The post-hardening file is ~140 lines.

**Files:**
- Modify: `main.py` (rewrite)

- [ ] **Step 1: Write the replacement main.py**

Write this exact content to `main.py` (overwrites the existing file):

```python
"""
Application entry point.

Loads .env, validates config (via import of config.py), wires up SQLAlchemy,
registers blueprints, and defines only the auth + Sales-vs-Spending routes.
All other finance/accounting surface has been removed.
"""
import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# load_dotenv BEFORE config import so config sees the populated env
load_dotenv()

import config  # noqa: E402  (import-after-load_dotenv is intentional)

from models import db, DailyPaidItem  # noqa: E402

from routes.intelligence import intelligence_bp  # noqa: E402
from routes.items import items_bp
from routes.sales import sales_bp
from routes.ai import ai_bp
from routes.weather import weather_bp
from routes.analytics_assistant import bp as analytics_assistant_bp
from routes.realtime import realtime_bp
from routes.item_trends import item_trends_bp
from routes.items_explorer import items_explorer_bp
from routes.dead_items import dead_items_bp
from routes.reorder_radar import reorder_radar_bp

from helpers_intelligence import (
    get_pos_sales_total_by_range,
    get_pos_sales_daily_by_range,
)


# ───────────────────────────────
# Flask app
# ───────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


@app.context_processor
def inject_request():
    return dict(request=request)


# ───────────────────────────────
# Sales vs Spending (surviving finance route, rebranded)
# ───────────────────────────────
@app.route("/finance/summary")
def finance_summary():
    """
    Sales vs Spending report.

    - Sales are read live from POS (via helpers_intelligence).
    - Spending is locally-entered DailyPaidItem rows.
    - Remaining = Sales - Spending (per source business day).
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    default_from = today - timedelta(days=today.weekday())
    default_to = today

    from_str = request.args.get("from_date", default_from.isoformat()).strip()
    to_str = request.args.get("to_date", default_to.isoformat()).strip()

    try:
        from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
        to_date = datetime.strptime(to_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date range. Reset to current week.", "warning")
        from_date, to_date = default_from, default_to
        from_str, to_str = from_date.isoformat(), to_date.isoformat()

    if from_date > to_date:
        flash("From date cannot be after To date. Reset to current week.", "warning")
        from_date, to_date = default_from, default_to
        from_str, to_str = from_date.isoformat(), to_date.isoformat()

    if from_date < config.MIN_TRACKING_DATE:
        from_date = config.MIN_TRACKING_DATE
        from_str = from_date.isoformat()
        flash(
            f"Start date adjusted to tracking start ({config.MIN_TRACKING_DATE.isoformat()}).",
            "warning",
        )

    if to_date < config.MIN_TRACKING_DATE:
        to_date = config.MIN_TRACKING_DATE
        to_str = to_date.isoformat()

    total_sales_lbp = float(get_pos_sales_total_by_range(from_date, to_date) or 0.0)

    paid_items = db.session.execute(
        db.select(DailyPaidItem)
        .where(DailyPaidItem.source_date >= from_date)
        .where(DailyPaidItem.source_date <= to_date)
        .order_by(DailyPaidItem.paid_date.desc(), DailyPaidItem.created_at.desc())
    ).scalars().all()

    total_spending_lbp = sum((item.amount_cents or 0) / 100 for item in paid_items)
    total_profit_lbp = total_sales_lbp - total_spending_lbp

    total_sales_usd = total_sales_lbp / config.USD_EXCHANGE_RATE
    total_spending_usd = total_spending_lbp / config.USD_EXCHANGE_RATE
    total_profit_usd = total_profit_lbp / config.USD_EXCHANGE_RATE

    sales_daily_rows = get_pos_sales_daily_by_range(from_date, to_date)

    sales_by_day = {
        row["biz_date"]: float(row["sales_lbp"] or 0.0)
        for row in sales_daily_rows
    }

    spending_by_day: dict[str, float] = {}
    for item in paid_items:
        day_key = item.source_date.isoformat()
        spending_by_day[day_key] = spending_by_day.get(day_key, 0.0) + (
            (item.amount_cents or 0) / 100
        )

    all_days = sorted(
        set(list(sales_by_day.keys()) + list(spending_by_day.keys())),
        reverse=True,
    )

    daily_rows = []
    for day_key in all_days:
        biz_date_obj = datetime.strptime(day_key, "%Y-%m-%d").date()
        sales_lbp = sales_by_day.get(day_key, 0.0)
        used_lbp = spending_by_day.get(day_key, 0.0)
        remaining_lbp = sales_lbp - used_lbp
        daily_rows.append({
            "biz_date": day_key,
            "day_name": biz_date_obj.strftime("%A"),
            "display_date": biz_date_obj.strftime("%A, %Y-%m-%d"),
            "sales_lbp": sales_lbp,
            "used_lbp": used_lbp,
            "remaining_lbp": remaining_lbp,
            "sales_usd": sales_lbp / config.USD_EXCHANGE_RATE,
            "used_usd": used_lbp / config.USD_EXCHANGE_RATE,
            "remaining_usd": remaining_lbp / config.USD_EXCHANGE_RATE,
        })

    default_paid_date_str = today.isoformat()
    default_source_date_str = (today - timedelta(days=1)).isoformat()

    return render_template(
        "finance/summary.html",
        today=today,
        yesterday=yesterday,
        from_date=from_date,
        to_date=to_date,
        from_str=from_str,
        to_str=to_str,
        paid_items=paid_items,
        daily_rows=daily_rows,
        total_sales_lbp=total_sales_lbp,
        total_spending_lbp=total_spending_lbp,
        total_profit_lbp=total_profit_lbp,
        total_sales_usd=total_sales_usd,
        total_spending_usd=total_spending_usd,
        total_profit_usd=total_profit_usd,
        usd_exchange_rate=config.USD_EXCHANGE_RATE,
        paid_item_types=config.PAID_ITEM_TYPES,
        default_paid_date_str=default_paid_date_str,
        default_source_date_str=default_source_date_str,
        currency=config.CURRENCY,
    )


@app.post("/finance/summary/add-paid-item")
def finance_summary_add_paid_item():
    """Add a manual paid item for the Sales vs Spending page."""
    try:
        paid_date = datetime.strptime(request.form["paid_date"], "%Y-%m-%d").date()
        source_date = datetime.strptime(request.form["source_date"], "%Y-%m-%d").date()
        title = request.form["title"].strip()
        amount_lbp_raw = request.form.get("amount_lbp", "").strip()
        amount_usd_raw = request.form.get("amount_usd", "").strip()
        amount_lbp = 0.0

        if amount_usd_raw:
            amount_usd = float(amount_usd_raw)
            if amount_usd <= 0:
                raise ValueError("USD amount must be greater than zero.")
            amount_lbp = amount_usd * config.USD_EXCHANGE_RATE
        elif amount_lbp_raw:
            amount_lbp = float(amount_lbp_raw)
            if amount_lbp <= 0:
                raise ValueError("LBP amount must be greater than zero.")
        else:
            raise ValueError("Please enter either LBP or USD amount.")

        payment_type = request.form.get("payment_type", "").strip()
        notes = request.form.get("notes", "").strip() or None

        if not title:
            raise ValueError("Title is required.")
        if payment_type not in config.PAID_ITEM_TYPES:
            raise ValueError("Invalid payment type selected.")

        paid_item = DailyPaidItem(
            paid_date=paid_date,
            source_date=source_date,
            title=title,
            amount_cents=int(round(amount_lbp * 100)),
            payment_type=payment_type,
            notes=notes,
        )
        db.session.add(paid_item)
        db.session.commit()
        flash("Paid item added successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Could not add paid item: {e}", "danger")

    from_str = request.form.get("from_date_redirect", "").strip()
    to_str = request.form.get("to_date_redirect", "").strip()
    if from_str and to_str:
        return redirect(url_for("finance_summary", from_date=from_str, to_date=to_str))
    return redirect(url_for("finance_summary"))


# ───────────────────────────────
# Auth
# ───────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == config.APP_USERNAME and password == config.APP_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ───────────────────────────────
# Blueprints
# ───────────────────────────────
app.register_blueprint(intelligence_bp)
app.register_blueprint(items_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(analytics_assistant_bp)
app.register_blueprint(realtime_bp)
app.register_blueprint(item_trends_bp)
app.register_blueprint(items_explorer_bp)
app.register_blueprint(dead_items_bp)
app.register_blueprint(reorder_radar_bp)


@app.before_request
def require_login():
    allowed_routes = ["login", "static"]
    if request.endpoint not in allowed_routes:
        if not session.get("logged_in"):
            return redirect(url_for("login"))


# ───────────────────────────────
# Entry
# ───────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=os.getenv("FLASK_ENV") == "development")
```

- [ ] **Step 2: Verify line count and imports**

Run: `wc -l main.py && grep -n "^from\|^import" main.py`
Expected: `main.py` is under 300 lines; imports reference only `config`, `models.db`, `models.DailyPaidItem`, and the surviving route blueprints (no `Envelope`, `FixedBill`, `DailyClosing`, `invoices`, `expenses`).

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass. (The `main.py` rewrite is not directly covered by tests, but its imports must resolve.)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: slim main.py; drop all finance routes except /finance/summary"
```

---

## Task 7: Delete invoice/expense blueprint files

These files are no longer referenced by `main.py`. Delete them so the surface matches the spec.

**Files:**
- Delete: `routes/invoices.py`
- Delete: `routes/expenses.py`

- [ ] **Step 1: Delete the files**

Run:

```bash
rm routes/invoices.py routes/expenses.py
```

- [ ] **Step 2: Verify no stray imports**

Run: `grep -rn "routes.invoices\|routes.expenses\|invoices_bp\|expenses_bp" --include="*.py" .`
Expected: no output.

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A routes/
git commit -m "chore: remove invoices and expenses blueprints"
```

---

## Task 8: Delete finance templates

Remove templates that are no longer referenced by any route. Keep `templates/finance/summary.html` (to be rebranded in the next task).

**Files:**
- Delete: `templates/bills.html`
- Delete: `templates/closings.html`
- Delete: `templates/envelopes.html`
- Delete: `templates/expenses.html`
- Delete: `templates/fixed_collections.html`
- Delete: `templates/invoices.html`
- Delete: `templates/dashboard.html`
- Delete: `templates/reports.html`

- [ ] **Step 1: Delete the templates**

Run:

```bash
rm templates/bills.html templates/closings.html templates/envelopes.html \
   templates/expenses.html templates/fixed_collections.html templates/invoices.html \
   templates/dashboard.html templates/reports.html
```

- [ ] **Step 2: Verify no surviving code references them**

Run: `grep -rnE "render_template\([\"'](bills|closings|envelopes|expenses|fixed_collections|invoices|dashboard|reports)\.html" --include="*.py" .`
Expected: no output.

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A templates/
git commit -m "chore: remove orphaned finance templates"
```

---

## Task 9: Update `templates/base.html` navigation

Remove nav links that point to deleted routes. Rename the "Acounting" (sic) link to "Sales vs Spending". Remove the Settings link (the `/settings` route was deleted with the other finance routes).

**Files:**
- Modify: `templates/base.html:57-130`

- [ ] **Step 1: Replace the Invoices nav block**

Open `templates/base.html`. Find lines around 104-108:

```html
            <a href="/invoices"
                class="sidebar-link {% if request.path.startswith('/invoices') %}bg-primary text-white{% endif %}">
                <i class="bi bi-receipt"></i> Invoices
            </a>
```

Delete those four lines entirely.

- [ ] **Step 2: Rename the Acounting link to Sales vs Spending**

Find lines around 114-117:

```html
            <a href="/finance/summary"
                class="sidebar-link {% if request.path.startswith('/finance') %}bg-primary text-white{% endif %}">
                <i class="bi bi-cash-stack"></i> Acounting
            </a>
```

Replace with:

```html
            <a href="/finance/summary"
                class="sidebar-link {% if request.path.startswith('/finance') %}bg-primary text-white{% endif %}">
                <i class="bi bi-cash-stack"></i> Sales vs Spending
            </a>
```

- [ ] **Step 3: Remove the Settings link**

Find lines around 120-125:

```html
            <!-- Settings -->
            <div class="px-3 mb-2 text-uppercase text-secondary small fw-semibold">System</div>

            <a href="/settings"
                class="sidebar-link {% if request.path.startswith('/settings') %}bg-primary text-white{% endif %}">
                <i class="bi bi-gear"></i> Settings
            </a>
```

Replace with (System section kept, but Settings link removed):

```html
            <!-- System -->
            <div class="px-3 mb-2 text-uppercase text-secondary small fw-semibold">System</div>
```

- [ ] **Step 4: Verify the nav is clean**

Run: `grep -niE "invoices|settings|bills|closings|envelopes|expenses|fixed-collections|Acounting" templates/base.html`
Expected: no output (case-insensitive).

- [ ] **Step 5: Commit**

```bash
git add templates/base.html
git commit -m "refactor(ui): prune nav of deleted finance routes; rename Acounting to Sales vs Spending"
```

---

## Task 10: Rebrand `templates/finance/summary.html`

Update the page title, headings, and any visible "Finance" copy to "Sales vs Spending". URL unchanged.

**Files:**
- Modify: `templates/finance/summary.html`

- [ ] **Step 1: Find visible "Finance" strings**

Run: `grep -niE "finance|accounting" templates/finance/summary.html`
Expected: some matches in `<title>`, headings, breadcrumbs.

- [ ] **Step 2: Replace each user-visible occurrence**

For each match that appears inside `<title>`, `<h1>`-`<h6>`, `<a>` link text, `<button>` text, or a breadcrumb `<li>`, replace "Finance" with "Sales vs Spending" and "Accounting" with "Sales vs Spending". Do NOT rename any template variable, Jinja block name, route reference, or CSS class.

Typical patterns to replace:
- `<title>Finance Summary</title>` → `<title>Sales vs Spending</title>`
- `<h1>Finance Summary</h1>` → `<h1>Sales vs Spending</h1>`
- breadcrumb `<li>Finance</li>` → `<li>Sales vs Spending</li>`

Leave `url_for(...)` calls, form `action="..."` URLs, and the `/finance/summary` path untouched.

- [ ] **Step 3: Verify**

Run: `grep -niE "\bfinance\b" templates/finance/summary.html`
Expected: only hits inside `action="/finance/summary/add-paid-item"` or `url_for('finance_summary')` (route references, NOT user-visible text).

- [ ] **Step 4: Commit**

```bash
git add templates/finance/summary.html
git commit -m "refactor(ui): rebrand Finance Summary page as Sales vs Spending"
```

---

## Task 11: Trim `models.py` to surviving models

Delete every model except `DailyPaidItem` and `AppSetting`.

**Files:**
- Modify: `models.py`

- [ ] **Step 1: Delete the nine unused model classes**

Open `models.py`. Locate and delete these class blocks entirely (from the `class NAME(db.Model):` line through the last method/property of that class):

- `class Envelope(db.Model):`
- `class EnvelopeTransaction(db.Model):`
- `class DailyClosing(db.Model):`
- `class FixedBill(db.Model):`
- `class FixedCollection(db.Model):`
- `class Expense(db.Model):`
- `class Supplier(db.Model):`
- `class Payable(db.Model):`
- `class PayablePayment(db.Model):`

Keep:
- The top-of-file imports and `db = SQLAlchemy()` line.
- `class AppSetting(db.Model):`
- `class DailyPaidItem(db.Model):`

- [ ] **Step 2: Verify only two model classes remain**

Run: `grep -c "^class " models.py`
Expected: `2`.

Run: `grep "^class " models.py`
Expected exactly:
```
class AppSetting(db.Model):
class DailyPaidItem(db.Model):
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "refactor: drop unused finance models; keep DailyPaidItem + AppSetting"
```

---

## Task 12: Trim `helpers.py`

Delete envelope/bill/allocation helpers. Keep only what the surviving app uses.

**Files:**
- Modify or delete: `helpers.py`

- [ ] **Step 1: Check what's still called**

Run: `grep -rnE "from helpers import|import helpers" --include="*.py" .`
Expected: any references are in the surviving code paths.

For each symbol named in those `from helpers import (...)` lines, check whether the name is one of these (all deleted):
`ensure_default_envelopes, post_envelope_tx, compute_allocation, current_month_target_cents, get_setting, set_setting, get_sales_overview_data, ensure_default_settings, dynamic_bills_pct, get_float_setting`

If yes, delete that import line (the code that called it was already removed in Task 6).

- [ ] **Step 2: Delete the file if no imports remain, else trim**

Run: `grep -rnE "from helpers import|import helpers " --include="*.py" .`

- If output is empty: `rm helpers.py` — nothing imports it.
- If output is non-empty: open `helpers.py` and delete every function except those still named in surviving imports. At minimum, delete `ensure_default_envelopes`, `post_envelope_tx`, `compute_allocation`, `current_month_target_cents`, `get_sales_overview_data`, `ensure_default_settings`, `dynamic_bills_pct`, `get_float_setting`. Keep `dollars_to_cents`, `cents_to_dollars`, `days_in_month` only if still imported; else delete them too.

- [ ] **Step 3: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A helpers.py
git commit -m "refactor: remove finance helpers from helpers.py"
```

---

## Task 13: Update `reset_db.py`; delete `db_test.py`

`reset_db.py` currently creates tables for all nine deleted models. `db_test.py` is a dev scratchpad with a hardcoded `Server=localhost,1433` string — delete it.

**Files:**
- Modify: `reset_db.py`
- Delete: `db_test.py`

- [ ] **Step 1: Inspect reset_db.py**

Run: `cat reset_db.py`

- [ ] **Step 2: Rewrite reset_db.py**

Write this exact content to `reset_db.py`:

```python
"""
Reset the local SQLite database.

Drops and recreates the tables for the two surviving models
(AppSetting, DailyPaidItem).
"""
from main import app, db

if __name__ == "__main__":
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Local SQLite reset: AppSetting, DailyPaidItem.")
```

- [ ] **Step 3: Delete db_test.py**

Run: `rm db_test.py`

- [ ] **Step 4: Verify no hardcoded server string remains**

Run: `grep -rniE "server=[a-z0-9]|localhost,1433|155\.117\.44\.163" --include="*.py" .`
Expected: no output.

- [ ] **Step 5: Run tests**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add reset_db.py
git rm db_test.py
git commit -m "chore: slim reset_db.py; delete db_test.py scratchpad"
```

---

## Task 14: Final verification

End-to-end safety check before the branch is considered done.

**Files:** (read-only verification)

- [ ] **Step 1: Grep for hardcoded secrets across the repo**

Run:

```bash
grep -rniE "password\s*=\s*[\"'][^\"']+[\"']|api_key\s*=\s*[\"'][^\"']+[\"']|pwd=[a-z0-9]|uid=[a-z0-9]|andr@o" --include="*.py" .
```

Expected: no output (any remaining match is a real hardcoded secret that must be fixed).

- [ ] **Step 2: Grep for references to deleted model classes**

Run:

```bash
grep -rnE "\b(Envelope|EnvelopeTransaction|DailyClosing|FixedBill|FixedCollection|Expense|Supplier|Payable|PayablePayment)\b" --include="*.py" --include="*.html" .
```

Expected: no output (any match means a stale reference that will blow up at request time).

- [ ] **Step 3: Grep for references to deleted routes**

Run:

```bash
grep -rnE "url_for\([\"'](dashboard|finance_home|finance_payables|finance_ledger|finance_reconciliation|daily_close|bills|fixed_bills|set_custom_start|delete_fixed_bill|toggle_fixed_bill|void_closing|edit_closing|closings|envelope_view|reports|settings|expenses|pay_bill|fixed_collections|mark_fixed_collected|fixed_coverage_report)[\"']" --include="*.html" --include="*.py" .
```

Expected: no output.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest -v`
Expected: all tests pass (including the 7 new `test_config.py` tests).

- [ ] **Step 5: Manual smoke test**

Populate a real `.env` (copy `.env.template` and fill in working values), then run:

```bash
python main.py
```

In a browser, hit each URL and confirm a 200 response (or the correct redirect to `/login`):

- `/login` → renders login form
- After logging in:
  - `/` → intelligence dashboard renders
  - `/sales` → renders
  - `/items` → renders
  - `/items/explorer` → renders
  - `/reports/item-trends` → renders
  - `/reports/dead-items` → renders
  - `/reorder-radar` → renders
  - `/finance/summary` → renders with "Sales vs Spending" title; submitting the add-paid-item form stores a row and redirects back
- Confirm the nav sidebar has no Invoices, Bills, Closings, Envelopes, Expenses, Fixed Collections, or Settings links; contains "Sales vs Spending" under the finance-adjacent section.

- [ ] **Step 6: Missing-env fail-fast check**

Temporarily comment out `MSSQL_PASSWORD` in `.env`, then run `python main.py`.
Expected: the app exits immediately with a message beginning `FATAL: Required configuration missing:` and listing `MSSQL_PASSWORD`.

Restore the value.

- [ ] **Step 7: Final commit (only if any clean-up needed)**

If all checks pass without changes, no commit needed. If any check required a fix, commit it:

```bash
git add -A
git commit -m "fix: final hardening cleanup"
```

---

## Acceptance criteria (from spec)

- [x] Tasks 1–14 complete.
- [x] Task 14 Step 1 grep returns no output.
- [x] Task 14 Step 2 grep returns no output.
- [x] Task 14 Step 3 grep returns no output.
- [x] Task 14 Step 4 pytest passes.
- [x] Task 14 Step 5 smoke test: all listed URLs render; nav is clean.
- [x] Task 14 Step 6 fail-fast error reproduces when any required env var is missing.
- [x] `main.py` is under 450 lines.
- [x] `models.py` contains only `AppSetting` and `DailyPaidItem`.
- [x] `.env.template` is committed.
- [x] `README.md` documents the setup flow.
