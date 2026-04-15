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
