from __future__ import annotations

import logging
from datetime import date

from flask import Blueprint, jsonify, render_template, request

from models import db, StockItem, StockEvent, get_setting
from helpers_stock import units_sold_since, compute_live, latest_count
from pos_dates import biz_date_range_8h
from helpers_items import list_items, list_subgroups

log = logging.getLogger(__name__)

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
            # 08:00 boundary (not the 07:00 used by intelligence KPIs): deduction must
            # match the daily sales totals the owner sees on the dashboard, which use
            # biz_date_range_8h. Open-ended (>= start) so all sales since the count subtract.
            start, _ = biz_date_range_8h(c.event_date)
            pairs.append((s.itm_code, start))

    sold_map, live_unavailable = {}, False
    try:
        sold_map = units_sold_since(tuple(sorted(pairs)))
    except Exception:
        # Broad on purpose: POS outages/timeouts surface in many forms and /stock must
        # never 500. Log it so a real bug here can't hide behind "live unavailable".
        log.exception("units_sold_since failed; serving baseline without live sales")
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
    if qty < 0:
        return jsonify({"ok": False, "error": "qty must be >= 0"}), 400

    title = (str(data.get("title") or "")).strip()
    subgroup = (str(data.get("subgroup") or "")).strip()
    raw_threshold = data.get("threshold")
    # threshold is optional here: a bad/negative value falls back to the default
    # (unlike set-threshold, an explicit edit that rejects bad input with 400).
    try:
        threshold = int(raw_threshold) if raw_threshold not in (None, "") else _default_threshold()
    except (TypeError, ValueError):
        threshold = _default_threshold()
    if threshold < 0:
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
    if qty < 0:
        return jsonify({"ok": False, "error": "qty must be >= 0"}), 400
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
        threshold = int(data.get("threshold"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "threshold must be an integer"}), 400
    if threshold < 0:
        return jsonify({"ok": False, "error": "threshold must be >= 0"}), 400
    si.alert_threshold = threshold
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
