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
