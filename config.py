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
