# Codebase Hardening — Design Spec

**Date:** 2026-04-15
**Status:** Draft, pending user approval
**Sub-project:** #1 of 7 in the productization roadmap
**Owner:** Majd Andraos

## Context

The reporting dashboard is currently a single-tenant Flask app tailored to one POS shop. We are productizing it for sale to other shop owners running the same POS system, delivered as a Windows on-prem installer ($1,200 upfront + $300/year maintenance, ed25519-signed license file, 6h heartbeat, silent auto-update — see roadmap).

Sub-project #1 is the prerequisite for every other productization sub-project. It removes obstacles that would make the current code unsafe or nonsensical to ship to a third party: hardcoded production credentials, ~1,200 lines of accounting/finance code that is not part of the sellable product, and fallback values that mask misconfiguration.

## Goals

- Zero secrets in source code. No hardcoded MSSQL credentials, no plaintext passwords anywhere in the repo.
- App fails fast with a clear error on startup if any required secret is missing — never silently falls back to a default.
- Finance/accounting surface removed except for `/finance/summary` (rebranded in the UI as "Sales vs Spending") and its companion `POST /finance/summary/add-paid-item` handler.
- `main.py` shrinks from ~1,475 lines to ~400 lines — app bootstrap, auth, blueprint registration, and the surviving Sales vs Spending route only.
- Local SQLite retained but only for the `DailyPaidItem` and `AppSetting` models.
- Ship a `.env.template` documenting every configurable key so the future installer wizard knows what to populate.

## Non-goals

These are out of scope for this sub-project; each has its own spec in the roadmap:

- License server, heartbeat endpoint, admin dashboard (sub-project #2).
- License-client code inside the app, hardware fingerprinting, activation-key entry (sub-project #3).
- Auto-update client (sub-project #4).
- MSI packaging (sub-project #5).
- First-run onboarding wizard (sub-project #6).
- Telemetry and crash reporting (sub-project #7).
- Refactoring the existing `_connect()` pyodbc pattern beyond parameterizing it.
- Changing any reporting query, dashboard UI, or visualization.
- Migration path for shops already using finance features (not a concern — this is productization for new customers).

## Units of change

### Files modified

- **`helpers_intelligence.py:16-45`** — `_conn_str()` reads `MSSQL_DRIVER`, `MSSQL_SERVER`, `MSSQL_DATABASE`, `MSSQL_USERNAME`, `MSSQL_PASSWORD` from env with no fallbacks for the three secrets. Strip the commented-out alternative `_conn_str` block. Delegates missing-key detection to `config.py`.
- **`main.py`** — At top: `from dotenv import load_dotenv; load_dotenv()` before any other app code, then `import config` (which validates on import). Delete routes in the range roughly lines 219–1408 covering `/finance/payables`, `/finance/payables/<id>/payment`, `/finance/ledger`, `/finance/reconciliation`, daily close, `/bills`, fixed-bills endpoints, `/closings`, `/envelopes`, `/reports`, `/expenses`, `/pay-bill/<id>`, `/fixed-collections`, `/mark-fixed-collected`, `/reports/fixed-coverage`, `/void-closing/<id>`, `/edit-closing/<id>`. Keep `GET /finance/summary` and `POST /finance/summary/add-paid-item`. Delete the `/` dashboard route entirely; the `intelligence` blueprint already defines `/` at the app root, so removing `main.py`'s `dashboard()` lets the blueprint's `intelligence_home` serve the root without a redirect or route conflict. Remove `register_blueprint(invoices_bp)` and the matching import. Keep `/login`, `/logout`, `require_login`, and surviving imports.
- **`models.py`** — Delete classes `Envelope`, `EnvelopeTransaction`, `DailyClosing`, `FixedBill`. Keep `DailyPaidItem` and `AppSetting`.
- **`helpers.py`** — Delete envelope/bill helper functions (`ensure_default_envelopes`, `post_envelope_tx`). If the surviving route still uses `dollars_to_cents` / `cents_to_dollars` / `days_in_month`, keep those; otherwise delete the file entirely. Verify by grepping callers after route deletions.
- **`helpers_weather.py`** — Add fail-fast guard: if `VC_API_KEY` is missing, raise at import via `config.py`.
- **`helpers_ai.py`** — Add fail-fast guard: if `OPENAI_API_KEY` is missing, raise at import via `config.py`.
- **`reset_db.py`** — Update to only create tables for surviving models.
- **`templates/base.html`** — Remove nav items for Finance, Bills, Closings, Envelopes, Expenses, Invoices, Fixed Collections, Reports. Add or relocate a "Sales vs Spending" nav item under the Reports menu pointing to `/finance/summary`.
- **`templates/finance/summary.html`** — Update page title, breadcrumbs, and any "Finance" copy to "Sales vs Spending". URL unchanged.
- **`requirements.txt`** — Add `python-dotenv`.
- **`README.md`** — Document setup: copy `.env.template` → `.env`, populate values, run the app.

### Files deleted

- `routes/invoices.py`
- `routes/expenses.py`
- `db_test.py` (dev scratchpad with hardcoded `localhost,1433` credentials; unused at runtime)
- `templates/bills.html`
- `templates/closings.html`
- `templates/envelopes.html`
- `templates/expenses.html`
- `templates/fixed_collections.html`
- `templates/invoices.html`
- `templates/dashboard.html`
- `templates/reports.html`

### Files created

- **`config.py`** — One-screen module loaded once at app bootstrap. On import: reads every required env var, validates each is non-empty, raises `RuntimeError` with a formatted multi-line error listing all missing keys. Exposes validated constants as module attributes (`MSSQL_SERVER`, `USD_EXCHANGE_RATE`, `CURRENCY`, `MIN_TRACKING_DATE`, etc.) so existing code can `from config import USD_EXCHANGE_RATE` instead of re-reading env. Existing `os.getenv` call sites elsewhere in the code stay as-is for optional values.
- **`.env.template`** — Canonical list of every configurable key (see below). Committed to the repo.

## `.env.template` contents

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

`USD_EXCHANGE_RATE`, `CURRENCY`, and `MIN_TRACKING_DATE` are moved out of the hardcoded `main.py` constants at lines 78–90 so each shop can set its own locale and exchange rate. Optional keys (currently only `DATABASE_URL`) may be blank; the app uses a documented default.

## Fail-fast validation

On app startup, `config.py` runs a validator that iterates the required-keys list. If any are missing or empty-string, it formats and prints:

```
FATAL: Required configuration missing:
  - MSSQL_PASSWORD
  - OPENAI_API_KEY

Copy .env.template to .env and fill in all values, then restart.
```

It then `sys.exit(1)`. No partial operation. No fallback. This is the property that makes the app safely shippable — no installer can accidentally deploy with placeholder credentials.

The validator runs once at import time. `config.py` is imported immediately after `load_dotenv()` in `main.py`, before any other module that might transitively open a database connection.

## Units, interfaces, and dependencies

- **`config.py`** — one purpose: load, validate, expose config values. Depends only on `os` and `python-dotenv`. Everything else in the app depends on it (directly or via re-reading env for optional values).
- **`helpers_intelligence._conn_str()`** — one purpose: build the MSSQL connection string. Depends on `config.py`. Inputs: none (reads validated config). Output: a connection string. Can be tested by mocking `config`.
- **`helpers_intelligence._connect()`** — one purpose: open a pyodbc connection. Depends on `_conn_str()`. Unchanged in this sub-project.
- **`main.py`** post-hardening — one purpose: app bootstrap, auth, blueprint registration, and the single Sales vs Spending route. Depends on `config`, `models`, `dotenv`, all blueprint modules. Consumers: Flask app server.
- **Surviving finance/summary route** — one purpose: render Sales (from POS) vs Spending (from `DailyPaidItem`) over a date range. Depends on `config` for currency/locale constants, `helpers_intelligence` for POS reads, `models.DailyPaidItem` for local writes.

Each unit can be changed without breaking others because the interfaces are narrow: config is a frozen module of constants; `_conn_str` returns a string; blueprint routes have thin HTTP contracts.

## Testing

### Automated

- **`tests/test_config.py`** — new. Cases:
  - All required keys present → `import config` succeeds and exposes values.
  - Any required key missing or blank → `RuntimeError` raised with that key's name in the message.
  - Optional key absent → falls back to documented default.
- **Existing tests unchanged** — `tests/test_pos_dates.py`, `tests/test_cache_utils.py` remain green. Full suite runs with a temporary `.env` populated with dummy values via `conftest.py`.

### Manual

After deletions, start the app and verify:
- `GET /` → renders the intelligence dashboard (served by `intelligence_bp`).
- `GET /sales`, `GET /reports/item-trends`, `GET /reports/dead-items`, `GET /items/explorer`, `GET /items`, `GET /reorder-radar` — all render.
- `GET /finance/summary` — renders with "Sales vs Spending" title; data loads.
- `POST /finance/summary/add-paid-item` — adds a paid item and redirects.
- Nav bar in `base.html` has no Finance/Bills/Closings/Envelopes/Expenses/Invoices/Fixed Collections items.
- Removing any single required env var from `.env` and restarting → app exits with the formatted error naming that key.

### Safety check

Before the final commit, run:

```
grep -rniE "password=|api_key=|pwd=|server=[^$]" --include="*.py" .
```

Expected output: only env-var *reads* (`os.getenv(...)`, references to `config.MSSQL_...`). No literal values.

## Risks and mitigations

- **Template or helper references a deleted model and crashes at request time rather than startup.** Mitigation: after the deletion pass, grep for the deleted class names (`Envelope`, `EnvelopeTransaction`, `DailyClosing`, `FixedBill`) across both `.py` and `.html` and remove any stragglers.
- **`DailyPaidItem` has a foreign key to a model being deleted.** Mitigation: verified during exploration — `DailyPaidItem` is standalone. Re-verify during implementation.
- **Dev environment breaks because `.env` isn't populated.** This is by design. The error message explains the fix. Document in README.
- **A deleted route is referenced by `url_for` in a surviving template.** Mitigation: grep surviving templates for `url_for('...')` calls matching deleted endpoint names.
- **A constant moved from `main.py` to `config.py` (e.g., `MIN_TRACKING_DATE`) isn't available where it's imported.** Mitigation: audit the imports in the finance/summary route; change `from main import MIN_TRACKING_DATE` style imports to `from config import MIN_TRACKING_DATE`.

## Rollback

The entire sub-project is one branch. If post-merge issues surface, revert the branch. No data migration is performed, so there is nothing to un-migrate.

## Acceptance criteria

Sub-project #1 is done when all of the following are true:

1. `grep -rniE "password=|api_key=|pwd=" --include="*.py" .` returns no literal values.
2. Removing any required env var from `.env` causes the app to exit on startup with a formatted error naming the missing key.
3. The nav bar has no finance-section items except "Sales vs Spending" under Reports.
4. `GET /finance/summary` renders with the new title; `POST /finance/summary/add-paid-item` works.
5. `main.py` is under 450 lines.
6. `models.py` contains only `DailyPaidItem` and `AppSetting`.
7. `python -m pytest` passes, including the new `test_config.py`.
8. `.env.template` is committed; `README.md` documents the setup flow.
