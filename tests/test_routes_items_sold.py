import os
from unittest.mock import patch

import pytest
from flask import Flask

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE = {
    "rows": [
        {"subgroup": "Beer", "item_code": "A", "item": "Almaza",
         "qty": 10.0, "revenue": 300.0, "avg_price": 30.0, "txns": 7, "share": 75.0},
        {"subgroup": "Soft", "item_code": "B", "item": "Cola",
         "qty": 40.0, "revenue": 100.0, "avg_price": 2.5, "txns": 20, "share": 25.0},
    ],
    "totals": {"items": 2, "qty": 50.0, "revenue": 400.0},
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
    assert body["totals"]["revenue"] == 400.0
    # USD added by the route (89000 from tests/conftest env)
    assert round(body["totals"]["revenue_usd"], 6) == round(400.0 / 89000.0, 6)
    m.assert_called_once()


def test_csv_export_has_header_and_total(client):
    with patch("routes.items_sold.get_items_sold_range", return_value=dict(_FAKE)):
        r = client.get("/api/reports/items-sold/export-csv?start_date=2026-06-01&end_date=2026-06-07")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    assert "subgroup,item_code,item,qty,avg_price,revenue,share_pct" in text
    assert "Almaza" in text
    assert "TOTAL" in text
