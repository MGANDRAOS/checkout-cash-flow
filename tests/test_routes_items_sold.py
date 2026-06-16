import os
from unittest.mock import patch

import pytest
from flask import Flask

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE = {
    "rows": [
        {"subgroup": "Beer", "item_code": "A", "item": "Almaza",
         "qty": 10.0, "revenue": 1000.0, "avg_price": 100.0, "txns": 7,
         "unit_cost": 60.0, "total_cost": 600.0, "profit": 400.0, "margin": 40.0, "share": 71.4},
        {"subgroup": "Soft", "item_code": "B", "item": "Cola",
         "qty": 40.0, "revenue": 400.0, "avg_price": 10.0, "txns": 20,
         "unit_cost": None, "total_cost": None, "profit": None, "margin": None, "share": 28.6},
    ],
    "totals": {"items": 2, "qty": 50.0, "revenue": 1400.0, "cost": 600.0,
               "profit": 400.0, "costed_revenue": 1000.0, "margin": 40.0, "uncosted_items": 1},
    "meta": {"start_date": "2026-06-01", "end_date": "2026-06-07",
             "subgroup": None, "days": 7},
}


@pytest.fixture
def client():
    app = Flask(__name__,
                template_folder=os.path.join(_REPO_ROOT, "templates"),
                static_folder=os.path.join(_REPO_ROOT, "static"))
    app.config["TESTING"] = True
    from routes.items_sold import items_sold_bp
    app.register_blueprint(items_sold_bp)
    return app.test_client()


def test_missing_dates_returns_400(client):
    r = client.get("/api/reports/items-sold")
    assert r.status_code == 400
    assert "required" in r.get_json()["error"]


def test_bad_date_format_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2026/06/01&end_date=2026-06-07")
    assert r.status_code == 400
    assert "YYYY-MM-DD" in r.get_json()["error"]


def test_start_after_end_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2026-06-07&end_date=2026-06-01")
    assert r.status_code == 400


def test_range_too_large_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2020-01-01&end_date=2026-06-07")
    assert r.status_code == 400
    assert "too large" in r.get_json()["error"].lower()


def test_happy_path_returns_rows_and_usd(client):
    with patch("routes.items_sold.get_items_sold_range", return_value=dict(_FAKE)) as m:
        r = client.get("/api/reports/items-sold?start_date=2026-06-01&end_date=2026-06-07")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["rows"]) == 2
    assert body["totals"]["revenue"] == 1400.0
    # USD added by the route (89000 from tests/conftest env)
    assert round(body["totals"]["revenue_usd"], 6) == round(1400.0 / 89000.0, 6)
    assert round(body["totals"]["profit_usd"], 6) == round(400.0 / 89000.0, 6)
    m.assert_called_once()


def test_csv_export_has_cost_profit_columns_and_total(client):
    with patch("routes.items_sold.get_items_sold_range", return_value=dict(_FAKE)):
        r = client.get("/api/reports/items-sold/export-csv?start_date=2026-06-01&end_date=2026-06-07")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0] == "subgroup,item_code,item,qty,unit_cost,avg_price,revenue,total_cost,profit,margin_pct,share_pct"
    # costed row carries cost/profit/margin
    assert any(ln.startswith("Beer,A,Almaza,") and "600" in ln and "400" in ln for ln in lines)
    # uncosted row leaves cost columns blank (no crash on None)
    assert any(ln.startswith("Soft,B,Cola,") for ln in lines)
    # TOTAL row includes profit
    total = [ln for ln in lines if ln.startswith("TOTAL")][0]
    assert "400" in total
