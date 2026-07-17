import csv
import io
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


class TestExport:
    def test_missing_lines_is_400(self, client):
        r = client.post("/api/supplier-reorder/export", json={})
        assert r.status_code == 400
        body = r.get_json()
        assert body["ok"] is False

    def test_empty_lines_is_400(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": []})
        assert r.status_code == 400
        body = r.get_json()
        assert body["ok"] is False

    def test_valid_lines_returns_csv_with_correct_rows_and_totals(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "Box4Less", "name": "Weidmann 50cl", "qty": 5, "unit_price_usd_cents": 91},
            {"supplier": "Nice Food", "name": "Almaza NRB 25cl", "qty": 3, "unit_price_usd_cents": 63},
        ]})
        assert r.status_code == 200
        assert r.content_type.startswith("text/csv")
        assert r.headers.get("Content-Disposition") == 'attachment; filename="supplier_orders.csv"'

        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        assert rows[0] == ["supplier", "item", "qty", "unit_price_usd", "line_total_usd"]
        assert rows[1] == ["Box4Less", "Weidmann 50cl", "5", "0.91", "4.55"]
        assert rows[2] == ["Nice Food", "Almaza NRB 25cl", "3", "0.63", "1.89"]
        assert rows[3] == []
        assert rows[4] == ["Box4Less", "TOTAL", "", "", "4.55"]
        assert rows[5] == ["Nice Food", "TOTAL", "", "", "1.89"]
        assert len(rows) == 6

    def test_non_numeric_qty_is_skipped_without_crashing(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "Box4Less", "name": "Bad Row", "qty": "N/A", "unit_price_usd_cents": 91},
            {"supplier": "Box4Less", "name": "Good Row", "qty": 2, "unit_price_usd_cents": 100},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        item_rows = [row for row in rows if len(row) >= 2 and row[1] not in ("item", "TOTAL")]
        names = [row[1] for row in item_rows]
        assert "Bad Row" not in names
        assert "Good Row" in names

    def test_non_numeric_unit_price_is_skipped_without_crashing(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "Box4Less", "name": "Bad Row", "qty": 2, "unit_price_usd_cents": "N/A"},
            {"supplier": "Box4Less", "name": "Good Row", "qty": 2, "unit_price_usd_cents": 100},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        item_rows = [row for row in rows if len(row) >= 2 and row[1] not in ("item", "TOTAL")]
        names = [row[1] for row in item_rows]
        assert "Bad Row" not in names
        assert "Good Row" in names

    def test_zero_or_negative_qty_is_skipped(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "Box4Less", "name": "Zero Qty", "qty": 0, "unit_price_usd_cents": 91},
            {"supplier": "Box4Less", "name": "Negative Qty", "qty": -1, "unit_price_usd_cents": 91},
            {"supplier": "Box4Less", "name": "Good Row", "qty": 1, "unit_price_usd_cents": 91},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        item_rows = [row for row in rows if len(row) >= 2 and row[1] not in ("item", "TOTAL")]
        names = [row[1] for row in item_rows]
        assert names == ["Good Row"]

    def test_multiple_lines_same_supplier_sum_into_one_total_row(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "Box4Less", "name": "Item A", "qty": 2, "unit_price_usd_cents": 100},
            {"supplier": "Box4Less", "name": "Item B", "qty": 3, "unit_price_usd_cents": 200},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        total_rows = [row for row in rows if len(row) >= 2 and row[1] == "TOTAL"]
        assert total_rows == [["Box4Less", "TOTAL", "", "", "8.00"]]

    def test_non_dict_line_item_is_skipped_without_crashing(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            "not-a-dict",
            123,
            None,
            {"supplier": "Box4Less", "name": "Good Row", "qty": 2, "unit_price_usd_cents": 100},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        item_rows = [row for row in rows if len(row) >= 2 and row[1] not in ("item", "TOTAL")]
        assert item_rows == [["Box4Less", "Good Row", "2", "1.00", "2.00"]]
        total_rows = [row for row in rows if len(row) >= 2 and row[1] == "TOTAL"]
        assert total_rows == [["Box4Less", "TOTAL", "", "", "2.00"]]

    def test_formula_injection_in_name_and_supplier_is_neutralized(self, client):
        r = client.post("/api/supplier-reorder/export", json={"lines": [
            {"supplier": "=cmd|'/c calc'!A1", "name": "+SUM(1+1)", "qty": 1, "unit_price_usd_cents": 100},
            {"supplier": "-2+3", "name": "@evil()", "qty": 1, "unit_price_usd_cents": 100},
        ]})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        item_rows = [row for row in rows if len(row) >= 2 and row[1] not in ("item",) and row[1] != "TOTAL"]
        assert item_rows[0][0] == " =cmd|'/c calc'!A1"
        assert item_rows[0][1] == " +SUM(1+1)"
        assert item_rows[1][0] == " -2+3"
        assert item_rows[1][1] == " @evil()"
        total_rows = [row for row in rows if len(row) >= 2 and row[1] == "TOTAL"]
        supplier_totals = {row[0] for row in total_rows}
        assert " =cmd|'/c calc'!A1" in supplier_totals
        assert " -2+3" in supplier_totals


class TestItemCreate:
    def _supplier(self, client, name="Box4Less"):
        from models import Supplier
        with client.application.app_context():
            s = Supplier(name=name, active=True)
            _db.session.add(s)
            _db.session.commit()
            return s.id

    def test_valid_payload_creates_item_and_persists(self, client):
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "name": "Almaza Can 33cl",
            "category": "beer", "unit_price_usd": "1.50",
        })
        assert r.status_code in (200, 201)
        body = r.get_json()
        assert body["ok"] is True
        assert isinstance(body["id"], int)

        from models import SupplierItem
        with client.application.app_context():
            item = _db.session.get(SupplierItem, body["id"])
            assert item is not None
            assert item.supplier_id == supplier_id
            assert item.name == "Almaza Can 33cl"
            assert item.unit_price_usd_cents == 150
            assert item.active is True

    def test_category_is_trimmed_and_uppercased(self, client):
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "name": "Test Item",
            "category": "  beer  ", "unit_price_usd": "1.00",
        })
        body = r.get_json()
        from models import SupplierItem
        with client.application.app_context():
            item = _db.session.get(SupplierItem, body["id"])
            assert item.category == "BEER"

    def test_missing_supplier_id_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        r = client.post("/api/supplier-reorder/item", json={
            "name": "Test Item", "unit_price_usd": "1.00",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_non_numeric_supplier_id_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": "not-a-number", "name": "Test Item", "unit_price_usd": "1.00",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_missing_unit_price_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "name": "Test Item",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_non_numeric_unit_price_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "name": "Test Item", "unit_price_usd": "not-a-number",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_empty_name_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "name": "   ", "unit_price_usd": "1.00",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_missing_name_is_400_and_creates_nothing(self, client):
        from models import SupplierItem
        supplier_id = self._supplier(client)
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": supplier_id, "unit_price_usd": "1.00",
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0

    def test_nonexistent_supplier_id_is_404_and_creates_nothing(self, client):
        from models import SupplierItem
        r = client.post("/api/supplier-reorder/item", json={
            "supplier_id": 999999, "name": "Test Item", "unit_price_usd": "1.00",
        })
        assert r.status_code == 404
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            assert _db.session.query(SupplierItem).count() == 0


class TestItemUpdate:
    def _item(self, client, **overrides):
        from models import Supplier, SupplierItem
        with client.application.app_context():
            s = Supplier(name="Box4Less", active=True)
            _db.session.add(s)
            _db.session.commit()
            defaults = dict(
                supplier_id=s.id, name="Almaza Can 33cl", category="BEER",
                format_label="33cl can", unit_price_usd_cents=150, active=True,
            )
            defaults.update(overrides)
            item = SupplierItem(**defaults)
            _db.session.add(item)
            _db.session.commit()
            return item.id

    def test_updating_price_only_leaves_other_fields_unchanged(self, client):
        from models import SupplierItem
        item_id = self._item(client)
        r = client.put(f"/api/supplier-reorder/item/{item_id}", json={"unit_price_usd": "2.25"})
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}
        with client.application.app_context():
            item = _db.session.get(SupplierItem, item_id)
            assert item.unit_price_usd_cents == 225
            assert item.name == "Almaza Can 33cl"
            assert item.category == "BEER"
            assert item.format_label == "33cl can"

    def test_updating_category_normalizes_it(self, client):
        from models import SupplierItem
        item_id = self._item(client)
        r = client.put(f"/api/supplier-reorder/item/{item_id}", json={"category": "  dairy  "})
        assert r.status_code == 200
        with client.application.app_context():
            item = _db.session.get(SupplierItem, item_id)
            assert item.category == "DAIRY"

    def test_nonexistent_item_id_is_404(self, client):
        r = client.put("/api/supplier-reorder/item/999999", json={"unit_price_usd": "2.25"})
        assert r.status_code == 404
        assert r.get_json()["ok"] is False

    def test_non_numeric_unit_price_is_400_and_price_unchanged(self, client):
        from models import SupplierItem
        item_id = self._item(client)
        r = client.put(f"/api/supplier-reorder/item/{item_id}", json={"unit_price_usd": "not-a-number"})
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        with client.application.app_context():
            item = _db.session.get(SupplierItem, item_id)
            assert item.unit_price_usd_cents == 150


class TestItemDeactivate:
    def _item(self, client):
        from models import Supplier, SupplierItem
        with client.application.app_context():
            s = Supplier(name="Box4Less", active=True)
            _db.session.add(s)
            _db.session.commit()
            item = SupplierItem(
                supplier_id=s.id, name="Almaza Can 33cl", category="BEER",
                format_label="33cl can", unit_price_usd_cents=150, active=True,
            )
            _db.session.add(item)
            _db.session.commit()
            return item.id

    def test_deactivates_an_active_item(self, client):
        from models import SupplierItem
        item_id = self._item(client)
        r = client.post(f"/api/supplier-reorder/item/{item_id}/deactivate")
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}
        with client.application.app_context():
            item = _db.session.get(SupplierItem, item_id)
            assert item.active is False

    def test_nonexistent_item_id_is_404(self, client):
        r = client.post("/api/supplier-reorder/item/999999/deactivate")
        assert r.status_code == 404
        assert r.get_json()["ok"] is False
