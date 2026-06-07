# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Checkout Cash Flow is a Flask web app for managing daily cash flow of a retail/checkout business. It connects to an external MSSQL POS database (read-only) for sales/item analytics and uses a local SQLite database for cash management (envelopes, expenses, payables, daily closings).

## Commands

```bash
# Run the app
python main.py

# Reset the local SQLite database (drops and recreates tables)
python reset_db.py

# Test MSSQL POS connection
python db_test.py

# Install dependencies
pip install -r requirements.txt
```

There is no test suite or linter configured.

## Architecture

### Dual Database Design
- **Local SQLite** (`instance/checkout.db`): Cash management data — envelopes, daily closings, expenses, payables, fixed bills, settings. Managed via Flask-SQLAlchemy models in `models.py`.
- **External MSSQL** (POS system): Read-only access to sales receipts, items, and inventory data. Connected via `pyodbc`. Connection config is in `.env` (MSSQL_* vars).

### Money Convention
All monetary values are stored as **integer cents** (`amount_cents`, `balance_cents`, etc.). Use `helpers.dollars_to_cents()` and `helpers.cents_to_dollars()` for conversion.

### Key Business Concepts
- **Envelopes**: Cash allocation buckets (BILLS, SPEND). Daily sales are split into envelopes via allocation rates (INVENTORY_RATE, OPS_RATE from env).
- **Daily Closings**: Record each day's total sales and how they're allocated across envelopes.
- **DailyPaidItem**: Manual spending entries with `paid_date` (when paid) vs `source_date` (which day's cash was used). Payment types are controlled via `PAID_ITEM_TYPES` list in `main.py`.
- **Payables**: Supplier bills with payment tracking. `Payable.refresh_status()` recalculates status after payment changes.
- **Business day window**: POS analytics use 07:00–05:00 next day as business day boundaries (see `helpers_intelligence.py`).

### Route Organization
- `main.py` (~1475 lines): App setup, dashboard, finance routes (payables, reconciliation, ledger, summary), closings, envelopes, expenses, settings, auth.
- `routes/` blueprints: Each handles a domain — `sales`, `intelligence`, `items`, `realtime`, `invoices`, `expenses`, `dead_items`, `reorder_radar`, `item_trends`, `items_explorer`, `ai`, `weather`, `analytics_assistant`.

### Helper Modules
- `helpers.py`: Core utilities — money conversion, envelope management, allocation logic, settings access.
- `helpers_intelligence.py`: MSSQL queries for POS analytics (KPIs, receipts, items, subgroups). All queries go through `_connect()` using pyodbc.
- `helpers_sales.py`: POS sales data (hourly, category, top/slow products, cumulative).
- `helpers_realtime.py`: Real-time POS data queries.
- `helpers_items.py`: Item catalog queries.
- `helpers_ai.py`: OpenAI-powered analytics assistant. Uses `execute_sql_readonly()` for safe read-only SQL execution against POS DB.

### Frontend
- Jinja2 templates in `templates/`, inheriting from `base.html`.
- Static assets in `static/` (CSS, JS, image assets).
- Finance module templates are in `templates/finance/`.

### Authentication
Simple session-based auth using `APP_USERNAME` and `APP_PASSWORD` from environment variables.

### Environment Variables
Key variables in `.env`: `DATABASE_URL`, `SECRET_KEY`, `CURRENCY`, `INVENTORY_RATE`, `OPS_RATE`, `APP_USERNAME`, `APP_PASSWORD`, `MSSQL_SERVER`, `MSSQL_DATABASE`, `MSSQL_USERNAME`, `MSSQL_PASSWORD`, `OPENAI_API_KEY`.

`config.py` validates a hardcoded `_REQUIRED_KEYS` list at **import time** and raises `RuntimeError` if any is missing/blank — so a missing var crashes the app on startup (→ 502 on IIS). Required keys also include `MSSQL_DRIVER`, `VISUAL_CROSSING_KEY`, `USD_EXCHANGE_RATE`, `MIN_TRACKING_DATE`, `LICENSE_SERVER_URL`, `SUPPORT_CONTACT`. Adding a new required key means every deployed `.env` must be updated or the app won't boot.

## Deployment & Operations (production)

The app runs on a **Windows IIS server** as a reverse proxy in front of a local waitress (WSGI) process. Public URL: **https://pos.agentico.me**.

### Dev → prod workflow
Test locally → `git commit` → `git push` → on the server `git pull` → restart waitress. No build step. If `requirements.txt` changed, also run `pip install -r requirements.txt` in the server venv (a missing new dep — e.g. `pynacl` — crashes startup → 502 on every page).

### Local dev (this machine, Windows)
- Repo: `C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow`
- venv python: `C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe` (has pyodbc, pynacl, etc. — the system Python on PATH does not)
- The worktree has no `.env`; copy the repo `.env` in to run/import, then remove it (it's a tracked file — see caveat below).

### Server layout (IIS host)
- App dir (git pull target): `C:\checkout-app` — contains `main.py`, `venv\`, `run_waitress.py`, `web.config`, `license\`, `server\`
- Server venv python: `C:\checkout-app\venv\Scripts\python.exe`
- Launcher: `C:\checkout-app\run_waitress.py` → serves `main.app` via waitress on **127.0.0.1:5000** (NOT tracked in git; edit on server directly). waitress default `threads=4`.
- IIS reverse proxy uses **ARR**; default `responseTimeout` ≈ **120s** → a backend hang past 120s yields a 502.
- `C:\checkout-app\web.config` is an ARR rewrite shim: it proxies `^(api/license|admin)` → `http://127.0.0.1:5001/` (a **separate license-server** process; check it's listening if `/admin` or license routes 502).
- IIS vdirs (`appcmd list vdir`): `checkout/` → `C:\checkout-app`, `pos/` → `C:\inetpub\pos-proxy`.
- IIS request logs: `C:\inetpub\logs\LogFiles\W3SVC2\` and `W3SVC3\` (files `u_exYYMMDD.log`). Other server apps live at `C:\checkout-ai-bot`, `C:\checkout-notifier`, `C:\checkout-telegram-notifier`.

### Diagnosing 502s (IIS)
A 502 means the upstream (waitress/license-server) crashed, hung, or isn't listening. In the IIS log, the trailing fields are `sc-status sc-substatus sc-win32-status time-taken(ms)`:
- `502 5 ...` (small time-taken) → process failed to start (missing dep / config / import crash). Reproduce with `C:\checkout-app\venv\Scripts\python.exe -c "import main"`.
- `502 3 ... 12002 ~120000` → **WinHTTP timeout under load** (`12002` = timeout, ~120000ms = ARR gave up). Backend was too slow / thread pool exhausted.
- Useful checks: `netstat -ano | findstr ":5000 :5001"` (are backends up?), `appcmd list site` / `appcmd list vdir`.

### Performance notes (POS query load)
- Every POS query across `helpers_intelligence`, `helpers_realtime`, `helpers_sales`, `helpers_items` shares the single `_connect()` in `helpers_intelligence.py`. `_connect()` sets a login timeout and a per-query timeout (`QUERY_TIMEOUT_SECONDS`, currently 30s) so a runaway query aborts instead of pinning a waitress worker thread until ARR's 120s timeout.
- The landing page (`/` → `intelligence.html`, `static/js/intelligence.js`) fires **12 API calls concurrently via `Promise.all`** on load; `/api/realtime/*` also polls. With few waitress threads + slow queries, this can exhaust the pool so even static files 502. Mitigations: keep analytics queries `@ttl_cache`'d (see `cache_utils.py`), keep the query timeout, and raise waitress `threads` in `run_waitress.py`.

### Git caveats
- `.env` **and** `routes/__pycache__/*.pyc` are **tracked in git** despite being in `.gitignore` (committed before the ignore rules). Don't `git commit -a` blindly — running the app rewrites the `.pyc` files, and touching `.env` risks committing a change that overwrites the server's local `.env` on pull. Stage specific files. (Tracked `.env` also means secrets are in git history — flagged for cleanup.)
