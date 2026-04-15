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
