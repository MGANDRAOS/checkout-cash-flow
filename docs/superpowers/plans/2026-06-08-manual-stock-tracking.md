# Manual Stock Tracking (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner hand-enter on-hand stock for items and watch it draw down live from POS sales, with near-out-of-stock alerts — all in local SQLite, never touching the POS stock field.

**Architecture:** A ledger of `StockEvent` rows (`count` + future `receive`) under a `StockItem` registry in local SQLite. Live stock is *derived*: `latest count qty + receives-after − net units sold since the count's business day`. Units-sold come from ONE batched, `ttl_cache`'d POS query for the whole tracked list. A `stock_bp` blueprint serves a search/add page and the deduction APIs.

**Tech Stack:** Flask, Flask-SQLAlchemy (local SQLite), pyodbc (read-only POS via existing `helpers_intelligence._connect`), pytest, Jinja2 + Bootstrap (existing `base.html`).

**Run tests with the venv python:** `C:\checkout-app` is prod; locally use
`"C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest`.
All `pytest` commands below assume that interpreter. Scope to the app suite with
`tests/ test_*.py` (the `server/` suite is a separate project).

---

## File Structure

- **Create** `helpers_stock.py` — pure live-stock math + the batched POS units-sold query. No Flask, no local-DB writes.
- **Create** `routes/stock.py` — `stock_bp` blueprint: page + JSON APIs. Owns local-DB CRUD via models.
- **Create** `templates/stock.html` — add panel + tracked table (extends `base.html`).
- **Create** `tests/conftest.py` — Flask test-app + client fixtures bound to in-memory SQLite.
- **Create** `tests/test_models_stock.py`, `tests/test_helpers_stock.py`, `tests/test_routes_stock.py`.
- **Modify** `models.py` — add `StockItem`, `StockEvent`.
- **Modify** `main.py` — import + register `stock_bp`.
- **Modify** `templates/base.html` — sidebar nav link.

Conventions confirmed from the codebase:
- Models live in `models.py` and use the shared `db` instance (no per-model `db` import).
- Blueprints use `@bp.get/.post`, parse `request.args`/JSON, return `jsonify(...)` (see `routes/dead_items.py`).
- Auth is automatic via `main.py`'s global `@app.before_request require_login()` — new routes need NO decorator.
- Business-day boundary for sales is 08:00 via `pos_dates.biz_date_range_8h`.
- Settings via `models.get_setting`/`set_setting`.
- TTL caching via `cache_utils.ttl_cache`.

---

## Task 1: Data models + test fixtures

**Files:**
- Modify: `models.py` (append after `DailyPaidItem`)
- Create: `tests/conftest.py`
- Test: `tests/test_models_stock.py`

- [ ] **Step 1: Write the test-app fixtures**

Create `tests/conftest.py`:

```python
"""Flask test-app + client fixtures bound to an in-memory SQLite DB.

Lives under tests/ so it does NOT apply to the separate server/ suite.
The root conftest.py already populates dummy env vars for config import.
"""
import pytest
from flask import Flask

from models import db as _db


@pytest.fixture
def app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    _db.init_app(app)

    # Import here so model classes are registered on db.metadata before create_all.
    import models  # noqa: F401
    from routes.stock import stock_bp
    app.register_blueprint(stock_bp)

    with app.app_context():
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 2: Write the failing model test**

Create `tests/test_models_stock.py`:

```python
from datetime import date, datetime

from models import db, StockItem, StockEvent


def test_create_stock_item_defaults(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", subgroup="Beer",
                       alert_threshold=6)
        db.session.add(si)
        db.session.commit()

        got = StockItem.query.filter_by(itm_code="ALM330").one()
        assert got.id is not None
        assert got.active is True
        assert got.alert_threshold == 6
        assert isinstance(got.created_at, datetime)


def test_create_stock_event_and_relationship(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", subgroup="Beer",
                       alert_threshold=6)
        db.session.add(si)
        db.session.flush()

        ev = StockEvent(stock_item_id=si.id, event_type="count", qty=22.0,
                        event_date=date(2026, 6, 8), source="manual")
        db.session.add(ev)
        db.session.commit()

        rows = StockEvent.query.filter_by(stock_item_id=si.id).all()
        assert len(rows) == 1
        assert rows[0].event_type == "count"
        assert rows[0].qty == 22.0
        assert rows[0].source == "manual"
        assert rows[0].invoice_id is None
        assert isinstance(rows[0].created_at, datetime)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_models_stock.py -v`
Expected: FAIL — `ImportError: cannot import name 'StockItem' from 'models'`.

- [ ] **Step 4: Implement the models**

Append to `models.py` (after the `DailyPaidItem` class):

```python
class StockItem(db.Model):
    """An item whose on-hand stock is tracked manually (local-only).

    POS is never written for stock. `title`/`subgroup` are cached POS snapshots
    captured when the item is added, so the list renders without a POS hit.
    """
    __tablename__ = "stock_items"

    id = db.Column(db.Integer, primary_key=True)
    itm_code = db.Column(db.String(128), nullable=False, unique=True, index=True)
    title = db.Column(db.String(255), nullable=False, default="")
    subgroup = db.Column(db.String(255), nullable=False, default="")
    alert_threshold = db.Column(db.Integer, nullable=False, default=5)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    events = db.relationship("StockEvent", backref="item",
                             cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<StockItem {self.itm_code} thr={self.alert_threshold}>"


class StockEvent(db.Model):
    """A ledger entry for a tracked item.

    event_type 'count'   -> qty is the ABSOLUTE on-hand as of event_date (manual).
    event_type 'receive' -> qty is a +DELTA received on event_date (Phase 2: invoices).
    Live stock = latest count qty + receives after it - net units sold since it.
    """
    __tablename__ = "stock_events"

    id = db.Column(db.Integer, primary_key=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"),
                              nullable=False, index=True)
    event_type = db.Column(db.String(16), nullable=False)   # 'count' | 'receive'
    qty = db.Column(db.Float, nullable=False)
    event_date = db.Column(db.Date, nullable=False, index=True)
    source = db.Column(db.String(16), nullable=False, default="manual")  # 'manual' | 'invoice'
    invoice_id = db.Column(db.Integer, nullable=True)  # Phase 2 seam
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<StockEvent item={self.stock_item_id} {self.event_type} qty={self.qty} {self.event_date}>"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_models_stock.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add models.py tests/conftest.py tests/test_models_stock.py
git commit -m "feat(stock): StockItem + StockEvent ledger models"
```

---

## Task 2: Live-stock math (`helpers_stock.py`)

Pure functions over already-loaded event rows. No DB, no POS. `event`/`StockEvent`
objects only need attributes `event_type`, `qty`, `event_date`, `created_at`.

**Files:**
- Create: `helpers_stock.py`
- Test: `tests/test_helpers_stock.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_helpers_stock.py`:

```python
from datetime import date, datetime
from types import SimpleNamespace

from helpers_stock import latest_count, receives_after, status_for, compute_live


def _ev(event_type, qty, event_date, created_at):
    return SimpleNamespace(event_type=event_type, qty=qty,
                           event_date=event_date, created_at=created_at)


def test_latest_count_picks_newest_by_date_then_created_at():
    a = _ev("count", 10, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    b = _ev("count", 22, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    c = _ev("count", 30, date(2026, 6, 8), datetime(2026, 6, 8, 9))  # same day, later
    assert latest_count([a, b, c]) is c
    assert latest_count([]) is None


def test_status_boundaries():
    assert status_for(0, 5) == "out"
    assert status_for(-3, 5) == "out"
    assert status_for(5, 5) == "low"
    assert status_for(1, 5) == "low"
    assert status_for(6, 5) == "ok"


def test_compute_live_count_only_deducts_sales():
    # Almaza: counted 22 today, sold 4 -> 18
    ev = _ev("count", 22, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    info = compute_live([ev], sold_units=4, threshold=6)
    assert info["live"] == 18
    assert info["status"] == "ok"
    assert info["q0"] == 22
    assert info["d0"] == date(2026, 6, 8)
    assert info["has_baseline"] is True


def test_compute_live_net_of_returns_adds_back():
    ev = _ev("count", 10, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    # net sold negative => a return => stock goes UP
    info = compute_live([ev], sold_units=-2, threshold=5)
    assert info["live"] == 12


def test_compute_live_includes_receives_after_count():
    count = _ev("count", 6, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    recv = _ev("receive", 24, date(2026, 6, 5), datetime(2026, 6, 5, 10))
    info = compute_live([count, recv], sold_units=10, threshold=5)
    # 6 + 24 - 10 = 20
    assert info["live"] == 20
    assert info["receives"] == 24


def test_compute_live_ignores_receives_before_latest_count():
    old_recv = _ev("receive", 100, date(2026, 5, 1), datetime(2026, 5, 1, 10))
    count = _ev("count", 8, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    info = compute_live([old_recv, count], sold_units=3, threshold=5)
    # receive predates the count baseline -> ignored. 8 - 3 = 5 (low)
    assert info["live"] == 5
    assert info["status"] == "low"
    assert info["receives"] == 0


def test_compute_live_no_baseline():
    info = compute_live([], sold_units=0, threshold=5)
    assert info["has_baseline"] is False
    assert info["live"] is None
    assert info["status"] == "unknown"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_helpers_stock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helpers_stock'`.

- [ ] **Step 3: Implement the pure math**

Create `helpers_stock.py`:

```python
"""Live stock math + batched POS units-sold query.

Pure-Python live computation (no DB/POS) plus ONE cached POS round-trip that
returns net units sold per item since each item's baseline business day.
POS is read-only and is NEVER used for stock levels (its stock field is unusable).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


def latest_count(events: Iterable) -> Optional[object]:
    """Return the 'count' event with the greatest (event_date, created_at), or None."""
    counts = [e for e in events if e.event_type == "count"]
    if not counts:
        return None
    return max(counts, key=lambda e: (e.event_date, e.created_at))


def receives_after(events: Iterable, count_event) -> float:
    """Sum 'receive' deltas strictly after the baseline count event."""
    total = 0.0
    for e in events:
        if e.event_type != "receive":
            continue
        after = e.event_date > count_event.event_date or (
            e.event_date == count_event.event_date
            and e.created_at > count_event.created_at
        )
        if after:
            total += e.qty
    return total


def status_for(live: float, threshold: float) -> str:
    """Out (<=0), Low (<=threshold), else OK."""
    if live <= 0:
        return "out"
    if live <= threshold:
        return "low"
    return "ok"


def compute_live(events: Iterable, sold_units: float, threshold: float) -> dict:
    """Derive live stock for one item from its ledger + net units sold since baseline.

    live = q0 + receives_after - sold_units
    `events` is the full event list for the item; `sold_units` is the net units sold
    since the latest count's business day (queried separately, may be 0/negative).
    """
    events = list(events)
    c = latest_count(events)
    if c is None:
        return {"live": None, "status": "unknown", "q0": None, "d0": None,
                "receives": 0.0, "sold": 0.0, "has_baseline": False}
    r = receives_after(events, c)
    sold = sold_units or 0.0
    live = c.qty + r - sold
    return {"live": live, "status": status_for(live, threshold), "q0": c.qty,
            "d0": c.event_date, "receives": r, "sold": sold, "has_baseline": True}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_helpers_stock.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add helpers_stock.py tests/test_helpers_stock.py
git commit -m "feat(stock): pure live-stock computation"
```

---

## Task 3: Batched POS units-sold query

Add the query builder (pure, testable) + the cached executor to `helpers_stock.py`.

**Files:**
- Modify: `helpers_stock.py`
- Test: `tests/test_helpers_stock.py` (append)

- [ ] **Step 1: Write the failing builder test**

Append to `tests/test_helpers_stock.py`:

```python
from datetime import datetime as _dt
from helpers_stock import build_units_sold_query


def test_build_units_sold_query_param_shape():
    pairs = (("ALM330", _dt(2026, 6, 8, 8)), ("PEPSI1L", _dt(2026, 6, 7, 8)))
    sql, params = build_units_sold_query(pairs)
    # one (?,?) values row per pair
    assert sql.count("(?, ?)") == 2
    # params are flattened code, start, code, start (positional)
    assert params == ["ALM330", _dt(2026, 6, 8, 8), "PEPSI1L", _dt(2026, 6, 7, 8)]
    assert "HISTORIC_RECEIPT_CONTENTS" in sql
    assert "SUM(c.ITM_QUANTITY)" in sql
    assert "r.RCPT_DATE >= v.win_start" in sql


def test_build_units_sold_query_empty():
    sql, params = build_units_sold_query(())
    assert sql == ""
    assert params == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_helpers_stock.py::test_build_units_sold_query_param_shape -v`
Expected: FAIL — `cannot import name 'build_units_sold_query'`.

- [ ] **Step 3: Implement builder + cached executor**

Append to `helpers_stock.py`:

```python
from cache_utils import ttl_cache


def build_units_sold_query(pairs: Tuple[Tuple[str, object], ...]):
    """Build the batched units-sold SQL + positional params for (itm_code, win_start) pairs.

    Returns ("", []) for no pairs. Each pair contributes one VALUES row; the join
    keeps RCPT_DATE sargable (>= per-item window start). Net SUM (returns subtract).
    """
    if not pairs:
        return "", []
    values_rows = ",".join(["(?, ?)"] * len(pairs))
    params: List[object] = []
    for code, start in pairs:
        params.append(str(code))
        params.append(start)
    sql = f"""
        SET NOCOUNT ON;
        SELECT v.itm_code AS itm_code, SUM(c.ITM_QUANTITY) AS sold
        FROM (VALUES {values_rows}) AS v(itm_code, win_start)
        JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.ITM_CODE = v.itm_code
        JOIN dbo.HISTORIC_RECEIPT r
          ON r.RCPT_ID = c.RCPT_ID AND r.RCPT_DATE >= v.win_start
        GROUP BY v.itm_code;
    """
    return sql, params


@ttl_cache(seconds=45)
def units_sold_since(pairs: Tuple[Tuple[str, object], ...]) -> Dict[str, float]:
    """Net units sold per item since each item's baseline business-day start.

    ONE batched POS round-trip (read-only). `pairs` MUST be a sorted tuple so the
    ttl_cache key is stable across reloads. Returns {} for no pairs. Missing items
    (no sales) simply won't appear in the dict -> treated as 0 by callers.
    """
    sql, params = build_units_sold_query(pairs)
    if not sql:
        return {}
    from helpers_intelligence import _connect  # lazy: avoids pyodbc import at module load
    out: Dict[str, float] = {}
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(sql, params)
        for row in cur.fetchall():
            out[str(row.itm_code)] = float(row.sold or 0.0)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_helpers_stock.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add helpers_stock.py tests/test_helpers_stock.py
git commit -m "feat(stock): batched cached POS units-sold query"
```

---

## Task 4: Routes blueprint (`routes/stock.py`)

**Files:**
- Create: `routes/stock.py`
- Modify: `main.py` (import + register, next to other blueprints)
- Test: `tests/test_routes_stock.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/test_routes_stock.py`:

```python
import json
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
    # 4 sold today -> live 18
    with patch("routes.stock.units_sold_since", return_value={"ALM330": 4.0}):
        r = client.get("/api/stock/list")
    assert r.status_code == 200
    rows = r.get_json()["items"]
    assert len(rows) == 1
    assert rows[0]["live"] == 18
    assert rows[0]["status"] == "ok"


def test_list_marks_low_and_out_and_sorts_them_first(client):
    _add(client, itm_code="A", qty=10, threshold=3)   # 10-9=1 -> low
    _add(client, itm_code="B", qty=5, threshold=3)    # 5-5=0 -> out
    _add(client, itm_code="C", qty=50, threshold=3)   # 50-1=49 -> ok
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


def test_list_degrades_when_pos_unavailable(client):
    _add(client, qty=22, threshold=6)
    with patch("routes.stock.units_sold_since", side_effect=RuntimeError("pos down")):
        body = client.get("/api/stock/list").get_json()
    assert body["live_unavailable"] is True
    assert body["items"][0]["status"] == "unknown"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_routes_stock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes.stock'` (collection error).

- [ ] **Step 3: Implement the blueprint**

Create `routes/stock.py`:

```python
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, render_template, request

from models import db, StockItem, StockEvent, get_setting
from helpers_stock import units_sold_since, compute_live, latest_count
from pos_dates import biz_date_range_8h
from helpers_items import list_items, list_subgroups

stock_bp = Blueprint("stock", __name__)

_STATUS_ORDER = {"out": 0, "low": 1, "unknown": 2, "ok": 3}


def _default_threshold() -> int:
    try:
        return int(get_setting("STOCK_DEFAULT_THRESHOLD", "5"))
    except (TypeError, ValueError):
        return 5


def _body():
    return request.get_json(silent=True) or request.form


def _get_item(data):
    sid = data.get("stock_item_id")
    try:
        return db.session.get(StockItem, int(sid)) if sid not in (None, "") else None
    except (TypeError, ValueError):
        return None


@stock_bp.get("/stock")
def stock_page():
    return render_template("stock.html")


@stock_bp.get("/api/stock/subgroups")
def api_stock_subgroups():
    return jsonify({"subgroups": list_subgroups()})


@stock_bp.get("/api/stock/search")
def api_stock_search():
    q = (request.args.get("q") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()
    payload = list_items(page=1, page_size=25, q=q, subgroup=subgroup)
    tracked = {s.itm_code for s in StockItem.query.filter_by(active=True).all()}
    for it in payload.get("items", []):
        it["tracked"] = it.get("code") in tracked
    return jsonify(payload)


def _serialize_items():
    """Return (rows, live_unavailable) for all active tracked items."""
    items = StockItem.query.filter_by(active=True).all()
    item_ids = [s.id for s in items]
    events_by_item = {s.id: [] for s in items}
    if item_ids:
        for ev in StockEvent.query.filter(StockEvent.stock_item_id.in_(item_ids)).all():
            events_by_item[ev.stock_item_id].append(ev)

    pairs = []
    for s in items:
        c = latest_count(events_by_item[s.id])
        if c is not None:
            start, _ = biz_date_range_8h(c.event_date)
            pairs.append((s.itm_code, start))

    sold_map, live_unavailable = {}, False
    try:
        sold_map = units_sold_since(tuple(sorted(pairs)))
    except Exception:
        live_unavailable = True

    rows = []
    for s in items:
        info = compute_live(events_by_item[s.id], sold_map.get(s.itm_code, 0.0),
                            s.alert_threshold)
        status = "unknown" if live_unavailable else info["status"]
        rows.append({
            "id": s.id, "itm_code": s.itm_code, "title": s.title, "subgroup": s.subgroup,
            "threshold": s.alert_threshold, "live": info["live"], "status": status,
            "q0": info["q0"], "d0": str(info["d0"]) if info["d0"] else None,
            "sold": info["sold"], "has_baseline": info["has_baseline"],
        })
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9), (r["title"] or "").lower()))
    return rows, live_unavailable


@stock_bp.get("/api/stock/list")
def api_stock_list():
    rows, live_unavailable = _serialize_items()
    return jsonify({"items": rows, "live_unavailable": live_unavailable})


@stock_bp.post("/api/stock/add")
def api_stock_add():
    data = _body()
    itm_code = (str(data.get("itm_code") or "")).strip()
    if not itm_code:
        return jsonify({"ok": False, "error": "itm_code required"}), 400
    try:
        qty = float(data.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "qty must be a number"}), 400

    title = (str(data.get("title") or "")).strip()
    subgroup = (str(data.get("subgroup") or "")).strip()
    raw_threshold = data.get("threshold")
    try:
        threshold = int(raw_threshold) if raw_threshold not in (None, "") else _default_threshold()
    except (TypeError, ValueError):
        threshold = _default_threshold()

    existing = StockItem.query.filter_by(itm_code=itm_code).first()
    if existing:
        existing.active = True
        if title:
            existing.title = title
        if subgroup:
            existing.subgroup = subgroup
        existing.alert_threshold = threshold
        si = existing
    else:
        si = StockItem(itm_code=itm_code, title=title, subgroup=subgroup,
                       alert_threshold=threshold, active=True)
        db.session.add(si)
        db.session.flush()

    db.session.add(StockEvent(stock_item_id=si.id, event_type="count", qty=qty,
                              event_date=date.today(), source="manual"))
    db.session.commit()
    return jsonify({"ok": True, "id": si.id})


@stock_bp.post("/api/stock/set-count")
def api_stock_set_count():
    data = _body()
    si = _get_item(data)
    if si is None:
        return jsonify({"ok": False, "error": "item not found"}), 404
    try:
        qty = float(data.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "qty must be a number"}), 400
    db.session.add(StockEvent(stock_item_id=si.id, event_type="count", qty=qty,
                              event_date=date.today(), source="manual"))
    db.session.commit()
    return jsonify({"ok": True})


@stock_bp.post("/api/stock/set-threshold")
def api_stock_set_threshold():
    data = _body()
    si = _get_item(data)
    if si is None:
        return jsonify({"ok": False, "error": "item not found"}), 404
    try:
        si.alert_threshold = int(data.get("threshold"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "threshold must be an integer"}), 400
    db.session.commit()
    return jsonify({"ok": True})


@stock_bp.post("/api/stock/remove")
def api_stock_remove():
    data = _body()
    si = _get_item(data)
    if si is None:
        return jsonify({"ok": False, "error": "item not found"}), 404
    si.active = False
    db.session.commit()
    return jsonify({"ok": True})


@stock_bp.get("/api/stock/alerts")
def api_stock_alerts():
    rows, live_unavailable = _serialize_items()
    alerts = [r for r in rows if r["status"] in ("out", "low")]
    return jsonify({"items": alerts, "count": len(alerts), "live_unavailable": live_unavailable})
```

- [ ] **Step 4: Register the blueprint in `main.py`**

In `main.py`, after `from routes.invoices import invoices_bp` (line ~40):

```python
from routes.stock import stock_bp
```

And after `app.register_blueprint(invoices_bp)` (line ~341):

```python
app.register_blueprint(stock_bp)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_routes_stock.py -v`
Expected: PASS (9 passed).

- [ ] **Step 6: Commit**

```bash
git add routes/stock.py main.py tests/test_routes_stock.py
git commit -m "feat(stock): stock blueprint (add/list/set-count/threshold/remove/alerts)"
```

---

## Task 5: Templates + sidebar link

This task is UI; verification is a Jinja render check (no unit test). The implementer
MUST first read `templates/base.html` to match its block name and sidebar markup exactly.

**Files:**
- Create: `templates/stock.html`
- Modify: `templates/base.html` (add sidebar link)

- [ ] **Step 1: Read `base.html` to learn the block name + sidebar pattern**

Run: open `templates/base.html`. Identify (a) the content block name (e.g. `{% block content %}`), (b) how an existing sidebar `<a>` link is structured (icon class, active-state condition). Match them. Below assumes `{% block content %}` and Bootstrap + `bi` icons (used elsewhere) — ADAPT if base.html differs.

- [ ] **Step 2: Create `templates/stock.html`**

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-3" id="stockApp">
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <h4 class="mb-0"><i class="bi bi-box-seam"></i> Stock</h4>
    <div id="alertBanner" class="text-muted small"></div>
  </div>

  <!-- Add panel -->
  <div class="card mb-3">
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div class="col-12 col-md-5">
          <label class="form-label small mb-1">Search POS items</label>
          <input id="searchInput" class="form-control" placeholder="Name or code…" autocomplete="off">
        </div>
        <div class="col-8 col-md-5">
          <label class="form-label small mb-1">Subgroup</label>
          <select id="subgroupSelect" class="form-select"><option value="">All</option></select>
        </div>
        <div class="col-4 col-md-2">
          <button id="searchBtn" class="btn btn-primary w-100">Search</button>
        </div>
      </div>
      <div id="searchResults" class="mt-3"></div>
    </div>
  </div>

  <!-- Tracked items -->
  <div id="trackedWrap">
    <div class="text-muted">Loading tracked items…</div>
  </div>
</div>

<script>
const fmt = (n) => (n === null || n === undefined) ? "—" : (Math.round(n * 100) / 100);
const badge = (s) => ({out:"danger", low:"warning", ok:"success", unknown:"secondary"}[s] || "secondary");

async function jget(url){ const r = await fetch(url); return r.json(); }
async function jpost(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  return r.json();
}

async function loadSubgroups(){
  try{
    const d = await jget("/api/stock/subgroups");
    const sel = document.getElementById("subgroupSelect");
    (d.subgroups||[]).forEach(s => {
      const o = document.createElement("option");
      o.value = s.subgroup; o.textContent = `${s.subgroup} (${s.count})`;
      sel.appendChild(o);
    });
  }catch(e){ /* non-fatal */ }
}

async function doSearch(){
  const q = document.getElementById("searchInput").value.trim();
  const sg = document.getElementById("subgroupSelect").value;
  const wrap = document.getElementById("searchResults");
  wrap.innerHTML = '<div class="text-muted small">Searching…</div>';
  try{
    const d = await jget(`/api/stock/search?q=${encodeURIComponent(q)}&subgroup=${encodeURIComponent(sg)}`);
    const items = d.items || [];
    if(!items.length){ wrap.innerHTML = '<div class="text-muted small">No items.</div>'; return; }
    wrap.innerHTML = items.map(it => `
      <div class="d-flex align-items-center gap-2 border-bottom py-2 flex-wrap">
        <div class="flex-grow-1">
          <div class="fw-semibold">${it.title || it.code}</div>
          <div class="text-muted small">${it.code} · ${it.subgroup || ""}</div>
        </div>
        ${it.tracked
          ? '<span class="badge bg-success">Tracked</span>'
          : `<input type="number" min="0" step="1" class="form-control form-control-sm qtyIn" style="width:90px" placeholder="Qty">
             <button class="btn btn-sm btn-outline-primary addBtn"
               data-code="${encodeURIComponent(it.code)}"
               data-title="${encodeURIComponent(it.title||'')}"
               data-subgroup="${encodeURIComponent(it.subgroup||'')}">Add</button>`}
      </div>`).join("");
    wrap.querySelectorAll(".addBtn").forEach(b => b.addEventListener("click", onAdd));
  }catch(e){ wrap.innerHTML = '<div class="text-danger small">Search failed.</div>'; }
}

async function onAdd(e){
  const btn = e.currentTarget;
  const qtyEl = btn.parentElement.querySelector(".qtyIn");
  const qty = parseFloat(qtyEl && qtyEl.value);
  if(isNaN(qty)){ alert("Enter a quantity."); return; }
  btn.disabled = true;
  const res = await jpost("/api/stock/add", {
    itm_code: decodeURIComponent(btn.dataset.code),
    title: decodeURIComponent(btn.dataset.title),
    subgroup: decodeURIComponent(btn.dataset.subgroup),
    qty: qty,
  });
  if(res.ok){ await doSearch(); await loadTracked(); }
  else { alert(res.error || "Failed."); btn.disabled = false; }
}

function rowHtml(r){
  const liveTxt = r.has_baseline ? fmt(r.live) : "—";
  return `
   <tr>
     <td><div class="fw-semibold">${r.title || r.itm_code}</div>
         <div class="text-muted small">${r.itm_code} · ${r.subgroup || ""}</div></td>
     <td class="text-center"><span class="fs-5 fw-bold text-${badge(r.status)}">${liveTxt}</span></td>
     <td class="text-center"><span class="badge bg-${badge(r.status)}">${r.status.toUpperCase()}</span></td>
     <td class="text-center">
       <input type="number" min="0" step="1" value="${r.threshold}" class="form-control form-control-sm thrIn"
              data-id="${r.id}" style="width:80px;display:inline-block">
     </td>
     <td class="text-end">
       <button class="btn btn-sm btn-outline-secondary setBtn" data-id="${r.id}" data-title="${encodeURIComponent(r.title||'')}">Set count</button>
       <button class="btn btn-sm btn-outline-danger rmBtn" data-id="${r.id}">Remove</button>
     </td>
   </tr>`;
}

async function loadTracked(){
  const wrap = document.getElementById("trackedWrap");
  const d = await jget("/api/stock/list");
  const rows = d.items || [];
  const lowOut = rows.filter(r => r.status === "low" || r.status === "out");
  document.getElementById("alertBanner").innerHTML = d.live_unavailable
    ? '<span class="text-warning">Live sales unavailable — showing baseline.</span>'
    : (lowOut.length ? `<span class="text-danger fw-semibold">${rows.filter(r=>r.status==='out').length} out · ${rows.filter(r=>r.status==='low').length} low</span>` : 'All good.');
  if(!rows.length){ wrap.innerHTML = '<div class="text-muted">No tracked items yet. Search above to add some.</div>'; return; }
  wrap.innerHTML = `
    <div class="table-responsive"><table class="table align-middle">
      <thead><tr><th>Item</th><th class="text-center">Live</th><th class="text-center">Status</th><th class="text-center">Alert ≤</th><th></th></tr></thead>
      <tbody>${rows.map(rowHtml).join("")}</tbody>
    </table></div>`;
  wrap.querySelectorAll(".rmBtn").forEach(b => b.addEventListener("click", async (e)=>{
    if(!confirm("Stop tracking this item?")) return;
    await jpost("/api/stock/remove", {stock_item_id: e.currentTarget.dataset.id});
    loadTracked();
  }));
  wrap.querySelectorAll(".setBtn").forEach(b => b.addEventListener("click", async (e)=>{
    const v = prompt("New counted quantity for " + decodeURIComponent(e.currentTarget.dataset.title) + ":");
    if(v === null) return;
    const qty = parseFloat(v);
    if(isNaN(qty)){ alert("Not a number."); return; }
    await jpost("/api/stock/set-count", {stock_item_id: e.currentTarget.dataset.id, qty});
    loadTracked();
  }));
  wrap.querySelectorAll(".thrIn").forEach(inp => inp.addEventListener("change", async (e)=>{
    const t = parseInt(e.currentTarget.value, 10);
    if(isNaN(t)) return;
    await jpost("/api/stock/set-threshold", {stock_item_id: e.currentTarget.dataset.id, threshold: t});
    loadTracked();
  }));
}

document.getElementById("searchBtn").addEventListener("click", doSearch);
document.getElementById("searchInput").addEventListener("keydown", (e)=>{ if(e.key==="Enter") doSearch(); });
loadSubgroups(); loadTracked();
</script>
{% endblock %}
```

- [ ] **Step 3: Add the sidebar link in `base.html`**

Find the sidebar `<a>` links (e.g. the Invoices one) and add alongside, matching the exact markup/classes used there. Example (ADAPT classes/active-check to base.html):

```html
<a href="/stock" class="nav-link {{ 'active' if request.path == '/stock' else '' }}">
  <i class="bi bi-box-seam"></i> Stock
</a>
```

- [ ] **Step 4: Verify templates render (Jinja parse + route smoke)**

Run:
```bash
python -c "import main; c=main.app.test_client(); main.app.config['TESTING']=True; \
import flask; \
print('templates OK' )"
```
Then verify the Jinja templates parse:
```bash
python -c "import main; \
ctx=main.app.app_context(); ctx.push(); \
from flask import render_template; \
print(render_template('stock.html')[:60]); ctx.pop()"
```
Expected: prints the start of the rendered HTML (no `TemplateSyntaxError`). If `main` import fails on missing `.env`, run with the env present (copy repo `.env` into the worktree, then remove it after — see CLAUDE.md), or set the required vars in the shell.

- [ ] **Step 5: Commit**

```bash
git add templates/stock.html templates/base.html
git commit -m "feat(stock): stock page UI + sidebar link"
```

---

## Task 6: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full app test suite**

Run: `python -m pytest tests/ test_*.py -v`
Expected: all PASS (Task 1–4 stock tests + pre-existing suite). Do NOT include `server/`.

- [ ] **Step 2: Confirm additive table creation**

Run:
```bash
python -c "import models; from flask import Flask; a=Flask(__name__); \
a.config['SQLALCHEMY_DATABASE_URI']='sqlite:///:memory:'; models.db.init_app(a); \
import inspect as _; \
ctx=a.app_context(); ctx.push(); models.db.create_all(); \
from sqlalchemy import inspect as sinspect; \
print(sorted(sinspect(models.db.engine).get_table_names())); ctx.pop()"
```
Expected: table list includes `stock_items` and `stock_events` alongside the existing tables — confirms additive creation (no destructive migration).

- [ ] **Step 3: Manual smoke (optional, if env available)**

With required env vars present, run `python main.py`, log in, open `/stock`. Add an item with a qty, confirm it appears in the tracked table with a live number and a colored status badge; change its threshold; click "Set count"; remove it. (POS must be reachable for the live number; otherwise the banner shows "Live sales unavailable".)

- [ ] **Step 4: Final commit (if any verification tweaks were needed)**

```bash
git add -A
git commit -m "chore(stock): Phase 1 verification"
```

---

## Self-Review notes

- **Spec coverage:** models (T1) ✓; live math incl. business-day boundary, net-of-returns, receive seam (T2) ✓; batched cached POS query + graceful degradation (T3, T4) ✓; all 9 routes incl. alerts + Out/Low sort (T4) ✓; search/subgroup filter UI + tracked table + alerts banner + sidebar (T5) ✓; additive migration (T6) ✓; per-item threshold default via setting (T4 `_default_threshold`) ✓.
- **Phase 2 seams:** `event_type='receive'` handled by `receives_after`/`compute_live`; `invoice_id` column present; no schema change needed later.
- **Types consistent:** `compute_live`/`latest_count`/`receives_after`/`status_for`/`build_units_sold_query`/`units_sold_since` signatures match their call sites in `routes/stock.py`. Row dict keys (`live`, `status`, `q0`, `d0`, `itm_code`, `threshold`, `has_baseline`) match the template's usage.
- **`STOCK_DEFAULT_THRESHOLD`** read via `get_setting` with a `"5"` fallback — no migration needed; setting row is optional.
