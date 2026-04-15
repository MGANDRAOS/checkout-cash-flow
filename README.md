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
