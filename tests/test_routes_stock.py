from datetime import date
from unittest.mock import patch

from models import db, StockItem, StockEvent


def _add(client, itm_code="ALM330", qty=22, title="Almaza 330", subgroup="Beer", threshold=6):
    return client.post("/api/stock/add", json={
        "itm_code": itm_code, "qty": qty, "title": title,
        "subgroup": subgroup, "threshold": threshold,
    })


def test_add_creates_item_and_count_event(client, app):
    r = _add(client)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="ALM330").one()
        assert si.alert_threshold == 6
        assert si.title == "Almaza 330"
        evs = StockEvent.query.filter_by(stock_item_id=si.id).all()
        assert len(evs) == 1
        assert evs[0].event_type == "count"
        assert evs[0].qty == 22
        assert evs[0].event_date == date.today()


def test_list_computes_live_from_mocked_sales(client):
    _add(client, qty=22, threshold=6)
    with patch("routes.stock.units_sold_since", return_value={"ALM330": 4.0}):
        r = client.get("/api/stock/list")
    assert r.status_code == 200
    rows = r.get_json()["items"]
    assert len(rows) == 1
    assert rows[0]["live"] == 18
    assert rows[0]["status"] == "ok"


def test_list_marks_low_and_out_and_sorts_them_first(client):
    _add(client, itm_code="A", qty=10, threshold=3)
    _add(client, itm_code="B", qty=5, threshold=3)
    _add(client, itm_code="C", qty=50, threshold=3)
    sold = {"A": 9.0, "B": 5.0, "C": 1.0}
    with patch("routes.stock.units_sold_since", return_value=sold):
        rows = client.get("/api/stock/list").get_json()["items"]
    statuses = [r["status"] for r in rows]
    assert statuses[0] == "out"
    assert statuses[1] == "low"
    assert statuses[2] == "ok"


def test_set_count_adds_new_baseline(client, app):
    _add(client, qty=22, threshold=6)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    r = client.post("/api/stock/set-count", json={"stock_item_id": sid, "qty": 30})
    assert r.status_code == 200
    with app.app_context():
        evs = StockEvent.query.filter_by(stock_item_id=sid, event_type="count").all()
        assert len(evs) == 2
        assert sorted(e.qty for e in evs) == [22, 30]


def test_set_threshold_updates(client, app):
    _add(client, qty=22, threshold=6)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    r = client.post("/api/stock/set-threshold", json={"stock_item_id": sid, "threshold": 12})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(StockItem, sid).alert_threshold == 12


def test_set_threshold_rejects_negative(client, app):
    _add(client, qty=22, threshold=6)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    r = client.post("/api/stock/set-threshold", json={"stock_item_id": sid, "threshold": -2})
    assert r.status_code == 400


def test_remove_soft_deletes(client, app):
    _add(client, qty=22)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    r = client.post("/api/stock/remove", json={"stock_item_id": sid})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(StockItem, sid).active is False
    with patch("routes.stock.units_sold_since", return_value={}):
        rows = client.get("/api/stock/list").get_json()["items"]
    assert rows == []


def test_alerts_returns_only_low_and_out(client):
    _add(client, itm_code="A", qty=10, threshold=3)
    _add(client, itm_code="B", qty=5, threshold=3)
    _add(client, itm_code="C", qty=50, threshold=3)
    sold = {"A": 9.0, "B": 5.0, "C": 1.0}
    with patch("routes.stock.units_sold_since", return_value=sold):
        body = client.get("/api/stock/alerts").get_json()
    assert body["count"] == 2
    assert {r["itm_code"] for r in body["items"]} == {"A", "B"}


def test_add_rejects_bad_qty(client):
    r = client.post("/api/stock/add", json={"itm_code": "X", "qty": "abc"})
    assert r.status_code == 400


def test_add_reactivates_existing(client, app):
    _add(client, qty=22, threshold=6)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    client.post("/api/stock/remove", json={"stock_item_id": sid})
    _add(client, qty=40, threshold=8)  # re-add same code
    with app.app_context():
        si = db.session.get(StockItem, sid)
        assert si.active is True
        assert si.alert_threshold == 8
        # second count event recorded
        evs = StockEvent.query.filter_by(stock_item_id=sid, event_type="count").all()
        assert len(evs) == 2


def test_list_degrades_when_pos_unavailable(client):
    _add(client, qty=22, threshold=6)
    with patch("routes.stock.units_sold_since", side_effect=RuntimeError("pos down")):
        body = client.get("/api/stock/list").get_json()
    assert body["live_unavailable"] is True
    assert body["items"][0]["status"] == "unknown"


def test_add_rejects_negative_qty(client):
    r = client.post("/api/stock/add", json={"itm_code": "X", "qty": -5})
    assert r.status_code == 400


def test_set_count_rejects_negative_qty(client, app):
    _add(client, qty=22)
    with app.app_context():
        sid = StockItem.query.filter_by(itm_code="ALM330").one().id
    r = client.post("/api/stock/set-count", json={"stock_item_id": sid, "qty": -1})
    assert r.status_code == 400


def test_search_marks_tracked_items(client):
    _add(client, itm_code="ALM330", qty=22)
    fake = {"items": [
        {"code": "ALM330", "title": "Almaza 330", "subgroup": "Beer"},
        {"code": "PEPSI1L", "title": "Pepsi 1L", "subgroup": "Soda"},
    ], "total": 2, "page": 1, "page_size": 25}
    with patch("routes.stock.list_items", return_value=fake):
        items = client.get("/api/stock/search?q=a").get_json()["items"]
    by_code = {it["code"]: it["tracked"] for it in items}
    assert by_code["ALM330"] is True
    assert by_code["PEPSI1L"] is False
