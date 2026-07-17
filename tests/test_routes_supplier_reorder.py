import os
from unittest.mock import patch

import pytest
from flask import Flask

from models import db as _db

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE_UNMATCHED = [
    {"id": 1, "name": "Almaza Can 33cl", "supplier": "Box4Less", "category": "Beer",
     "unit_price_usd_cents": 150,
     "candidates": [{"code": "ALM330", "title": "Almaza 330", "subgroup": "Beer", "score": 0.92}]},
    {"id": 2, "name": "Cheese Block", "supplier": "Nice Food", "category": "Dairy",
     "unit_price_usd_cents": 499, "candidates": []},
]


@pytest.fixture
def client():
    app = Flask(__name__,
                template_folder=os.path.join(_REPO_ROOT, "templates"),
                static_folder=os.path.join(_REPO_ROOT, "static"))
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    _db.init_app(app)
    import models  # noqa: F401 - registers model classes on db.metadata before create_all
    from routes.supplier_reorder import supplier_reorder_bp
    app.register_blueprint(supplier_reorder_bp)
    # base.html's sidebar nav calls url_for('items.items_home') and
    # url_for('reorder_radar.reorder_radar_page') unconditionally, so those two
    # blueprints must also be registered for the page template to render at all.
    # They are not exercised functionally by any test in this file.
    from routes.items import items_bp
    from routes.reorder_radar import reorder_radar_bp
    app.register_blueprint(items_bp)
    app.register_blueprint(reorder_radar_bp)
    with app.app_context():
        _db.create_all()
    return app.test_client()


def test_match_page_renders(client):
    r = client.get("/supplier-reorder/match")
    assert r.status_code == 200
    assert b'id="supMatchList"' in r.data


def test_unmatched_returns_wrapped_items(client):
    with patch("routes.supplier_reorder.unmatched_items", return_value=list(_FAKE_UNMATCHED)) as m:
        r = client.get("/api/supplier-reorder/match/unmatched")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"items": _FAKE_UNMATCHED}
    m.assert_called_once_with()


class TestConfirm:
    def test_valid_body_calls_set_match_and_returns_ok(self, client):
        with patch("routes.supplier_reorder.set_match", return_value=True) as m:
            r = client.post("/api/supplier-reorder/match/confirm",
                             json={"supplier_item_id": 42, "itm_code": " ALM330 "})
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}
        m.assert_called_once_with(42, "ALM330")

    def test_missing_supplier_item_id_is_400_and_does_not_call_set_match(self, client):
        with patch("routes.supplier_reorder.set_match") as m:
            r = client.post("/api/supplier-reorder/match/confirm", json={"itm_code": "ALM330"})
        assert r.status_code == 400
        body = r.get_json()
        assert body["ok"] is False
        m.assert_not_called()

    def test_non_numeric_supplier_item_id_is_400_and_does_not_call_set_match(self, client):
        with patch("routes.supplier_reorder.set_match") as m:
            r = client.post("/api/supplier-reorder/match/confirm",
                             json={"supplier_item_id": "not-a-number", "itm_code": "ALM330"})
        assert r.status_code == 400
        body = r.get_json()
        assert body["ok"] is False
        m.assert_not_called()

    def test_item_not_found_is_404(self, client):
        with patch("routes.supplier_reorder.set_match", return_value=False) as m:
            r = client.post("/api/supplier-reorder/match/confirm",
                             json={"supplier_item_id": 999, "itm_code": "ALM330"})
        assert r.status_code == 404
        body = r.get_json()
        assert body["ok"] is False
        m.assert_called_once_with(999, "ALM330")

    def test_itm_code_omitted_passes_none_clear_match(self, client):
        with patch("routes.supplier_reorder.set_match", return_value=True) as m:
            r = client.post("/api/supplier-reorder/match/confirm",
                             json={"supplier_item_id": 7})
        assert r.status_code == 200
        m.assert_called_once_with(7, None)

    def test_itm_code_empty_string_passes_none_clear_match(self, client):
        with patch("routes.supplier_reorder.set_match", return_value=True) as m:
            r = client.post("/api/supplier-reorder/match/confirm",
                             json={"supplier_item_id": 7, "itm_code": ""})
        assert r.status_code == 200
        m.assert_called_once_with(7, None)


def test_supplier_reorder_page_renders(client):
    r = client.get("/supplier-reorder")
    assert r.status_code == 200
    assert b'id="supplierReorder"' in r.data
    assert b'data-currency=' in r.data


_FAKE_REORDER_NOW = {
    "items": [{"itm_code": "ALM330", "name": "Almaza 330", "qty": 24,
               "unit_price_usd_cents": 150, "supplier": "Box4Less"}],
    "live_unavailable": False,
    "totals_by_supplier_cents": {"Box4Less": 3600},
    "unpriced_count": 0,
}


def test_reorder_now_passthrough(client):
    with patch("routes.supplier_reorder.reorder_now", return_value=dict(_FAKE_REORDER_NOW)) as m:
        r = client.get("/api/supplier-reorder/reorder-now")
    assert r.status_code == 200
    assert r.get_json() == _FAKE_REORDER_NOW
    m.assert_called_once_with()


_FAKE_CATALOG = {"items": [], "total": 0, "page": 1, "page_size": 30}


class TestCatalog:
    def test_forwards_query_params(self, client):
        with patch("routes.supplier_reorder.browse_catalog", return_value=dict(_FAKE_CATALOG)) as m:
            r = client.get("/api/supplier-reorder/catalog?q=beer&category=ENERGY&page=2")
        assert r.status_code == 200
        m.assert_called_once_with(q="beer", category="ENERGY", page=2)

    def test_defaults_when_no_params(self, client):
        with patch("routes.supplier_reorder.browse_catalog", return_value=dict(_FAKE_CATALOG)) as m:
            r = client.get("/api/supplier-reorder/catalog")
        assert r.status_code == 200
        m.assert_called_once_with(q="", category="", page=1)

    def test_page_zero_is_clamped_to_one(self, client):
        with patch("routes.supplier_reorder.browse_catalog", return_value=dict(_FAKE_CATALOG)) as m:
            client.get("/api/supplier-reorder/catalog?page=0")
        m.assert_called_once_with(q="", category="", page=1)

    def test_negative_page_is_clamped_to_one(self, client):
        with patch("routes.supplier_reorder.browse_catalog", return_value=dict(_FAKE_CATALOG)) as m:
            client.get("/api/supplier-reorder/catalog?page=-5")
        m.assert_called_once_with(q="", category="", page=1)

    def test_non_numeric_page_falls_back_to_one(self, client):
        with patch("routes.supplier_reorder.browse_catalog", return_value=dict(_FAKE_CATALOG)) as m:
            client.get("/api/supplier-reorder/catalog?page=notanumber")
        m.assert_called_once_with(q="", category="", page=1)


def test_categories_wrapped(client):
    with patch("routes.supplier_reorder.list_categories", return_value=["Beer", "Dairy"]) as m:
        r = client.get("/api/supplier-reorder/categories")
    assert r.status_code == 200
    assert r.get_json() == {"categories": ["Beer", "Dairy"]}
    m.assert_called_once_with()


def test_suppliers_endpoint_returns_only_active_sorted_by_name(client):
    from models import Supplier
    with client.application.app_context():
        _db.session.add_all([
            Supplier(name="Zephyr Foods", active=True),
            Supplier(name="Box4Less", active=True),
            Supplier(name="Retired Supplier", active=False),
        ])
        _db.session.commit()

    r = client.get("/api/supplier-reorder/suppliers")
    assert r.status_code == 200
    body = r.get_json()
    names = [s["name"] for s in body["suppliers"]]
    assert names == ["Box4Less", "Zephyr Foods"]
    assert all(set(s.keys()) == {"id", "name"} for s in body["suppliers"])
