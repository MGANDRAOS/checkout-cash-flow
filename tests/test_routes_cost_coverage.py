import os
from unittest.mock import patch

import pytest
from flask import Flask

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE = {
    "coverage": {"active": 3014, "uncosted_active": 1064, "coverage_pct": 64.7},
    "at_risk": {"items": 2, "revenue": 44200000.0},
    "dormant_uncosted": 931,
    "rows": [
        {"item_code": "2838", "item": "Fantasia XL", "subgroup": "Chips",
         "qty": 316.0, "revenue": 31600000.0, "avg_price": 100000.0, "last_sold": "2026-06-15"},
        {"item_code": "2958", "item": "Reva Tissues", "subgroup": "Wipes",
         "qty": 126.0, "revenue": 12600000.0, "avg_price": 100000.0, "last_sold": "2026-06-14"},
    ],
    "meta": {"days": 90, "subgroup": None, "generated_for": "2026-06-16"},
}


@pytest.fixture
def client():
    app = Flask(__name__,
                template_folder=os.path.join(_REPO_ROOT, "templates"),
                static_folder=os.path.join(_REPO_ROOT, "static"))
    app.config["TESTING"] = True
    from routes.cost_coverage import cost_coverage_bp
    app.register_blueprint(cost_coverage_bp)
    return app.test_client()


def test_default_days_and_usd(client):
    with patch("routes.cost_coverage.get_cost_coverage", return_value=dict(_FAKE)) as m:
        r = client.get("/api/reports/cost-coverage")
    assert r.status_code == 200
    body = r.get_json()
    assert body["coverage"]["coverage_pct"] == 64.7
    assert len(body["rows"]) == 2
    # USD added by route (89000 from tests/conftest env)
    assert round(body["at_risk"]["revenue_usd"], 6) == round(44200000.0 / 89000.0, 6)
    # default days = 90 passed to helper
    assert m.call_args.kwargs.get("days") == 90 or m.call_args.args[0] == 90


def test_days_param_clamped(client):
    with patch("routes.cost_coverage.get_cost_coverage", return_value=dict(_FAKE)) as m:
        client.get("/api/reports/cost-coverage?days=99999")
    passed = m.call_args.kwargs.get("days", m.call_args.args[0] if m.call_args.args else None)
    assert passed == 730  # clamped to max


def test_csv_export_header_and_rows(client):
    with patch("routes.cost_coverage.get_cost_coverage", return_value=dict(_FAKE)):
        r = client.get("/api/reports/cost-coverage/export-csv?days=90")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    lines = [ln for ln in r.get_data(as_text=True).splitlines() if ln.strip()]
    assert lines[0] == "item_code,item,subgroup,units,revenue,avg_price,last_sold"
    assert any(ln.startswith("2838,Fantasia XL,Chips,") for ln in lines)
