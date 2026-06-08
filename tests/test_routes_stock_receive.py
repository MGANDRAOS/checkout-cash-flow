import io
from datetime import date
from unittest.mock import patch

from models import db, StockItem, StockEvent, StockItemAlias

CATALOG = [
    {"code": "ALM330", "title": "ALMAZA BEER 330ML", "subgroup": "Beer"},
    {"code": "PEP1L", "title": "PEPSI 1L", "subgroup": "Soda"},
]


def _scan(client, lines):
    with patch("routes.stock.extract_invoice_lines", return_value=lines), \
         patch("routes.stock.load_catalog", return_value=CATALOG):
        return client.post("/api/stock/receive/scan",
                           data={"image": (io.BytesIO(b"\xff\xd8jpeg"), "inv.jpg")},
                           content_type="multipart/form-data")


def test_scan_returns_matched_lines(client):
    r = _scan(client, [{"raw_description": "ALMAZA 33", "qty": 24, "unit_cost": 1.5}])
    assert r.status_code == 200
    lines = r.get_json()["lines"]
    assert lines[0]["match"]["code"] == "ALM330"
    assert lines[0]["qty"] == 24


def test_scan_rejects_missing_image(client):
    r = client.post("/api/stock/receive/scan", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_confirm_adds_receive_to_tracked_item(client, app):
    client.post("/api/stock/add", json={"itm_code": "ALM330", "qty": 10, "title": "Almaza", "subgroup": "Beer"})
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "ALM330", "title": "Almaza", "subgroup": "Beer",
         "qty": 24, "unit_cost": 1.5, "raw_description": "ALMAZA 33"},
    ]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["received"] == 1
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="ALM330").one()
        recv = StockEvent.query.filter_by(stock_item_id=si.id, event_type="receive").all()
        assert len(recv) == 1
        assert recv[0].qty == 24
        assert recv[0].unit_cost_cents == 150
        assert recv[0].source == "invoice"
        assert recv[0].batch_id == body["batch_id"]
        assert StockItemAlias.query.filter_by(raw_description="ALMAZA 33").one().itm_code == "ALM330"


def test_confirm_creates_count_baseline_for_untracked_item(client, app):
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "PEP1L", "title": "Pepsi 1L", "subgroup": "Soda",
         "qty": 6, "unit_cost": 2.0, "raw_description": "PEPSI 1L"},
    ]})
    assert r.status_code == 200
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="PEP1L").one()
        evs = StockEvent.query.filter_by(stock_item_id=si.id).all()
        assert len(evs) == 1
        assert evs[0].event_type == "count"
        assert evs[0].qty == 6
        assert evs[0].unit_cost_cents == 200


def test_confirm_rejects_empty_lines(client):
    r = client.post("/api/stock/receive/confirm", json={"lines": []})
    assert r.status_code == 400


def test_undo_reverses_batch(client, app):
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "PEP1L", "title": "Pepsi", "subgroup": "Soda",
         "qty": 6, "unit_cost": 2.0, "raw_description": "PEPSI 1L"},
    ]})
    batch = r.get_json()["batch_id"]
    u = client.post("/api/stock/receive/undo", json={"batch_id": batch})
    assert u.status_code == 200
    with app.app_context():
        assert StockEvent.query.filter_by(batch_id=batch).count() == 0
        assert StockItem.query.filter_by(itm_code="PEP1L").count() == 0


def test_confirm_reactivates_inactive_item(client, app):
    # track then soft-remove ALM330
    client.post("/api/stock/add", json={"itm_code": "ALM330", "qty": 10, "title": "Almaza", "subgroup": "Beer"})
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    client.post("/api/stock/remove", json={"stock_item_id": sid})
    # receiving it again reactivates and adds a receive (not a new count baseline)
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "ALM330", "title": "Almaza", "subgroup": "Beer",
         "qty": 12, "unit_cost": 1.0, "raw_description": "ALMAZA 33"},
    ]})
    assert r.status_code == 200
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="ALM330").one()
        assert si.active is True
        recv = StockEvent.query.filter_by(stock_item_id=si.id, event_type="receive").all()
        assert len(recv) == 1 and recv[0].qty == 12
