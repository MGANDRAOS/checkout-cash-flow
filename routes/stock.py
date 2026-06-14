from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request

from models import db, StockItem, StockEvent, get_setting
from helpers_stock import (
    units_sold_since, compute_live, latest_count, live_last_sold, count_window_start,
    stock_analytics,
)
from helpers_items import list_items, list_subgroups
from config import CURRENCY
from helpers_invoice_ocr import extract_invoice_lines
from helpers_invoice_match import load_catalog, match_lines, upsert_alias

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

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
    return render_template("stock.html", currency=CURRENCY)


@stock_bp.get("/api/stock/subgroups")
def api_stock_subgroups():
    return jsonify({"subgroups": list_subgroups()})


@stock_bp.get("/api/stock/search")
def api_stock_search():
    q = (request.args.get("q") or "").strip()
    subgroup_id_raw = (request.args.get("subgroup") or "").strip()
    try:
        subgroup_id = int(subgroup_id_raw) if subgroup_id_raw else None
    except (TypeError, ValueError):
        subgroup_id = None
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    payload = list_items(page=page, page_size=25, q=q, subgroup_id=subgroup_id)
    items = payload.get("items", [])
    tracked = {s.itm_code for s in StockItem.query.filter_by(active=True).all()}
    # list_items' "last_purchased" reads only the archived HISTORIC_RECEIPT tables, so an
    # item whose only sale is today (still in the live dbo.RECEIPT tables) shows no date.
    # Overlay today's live last-sold for the items on this page so the Stock search matches
    # the live stock count, which already unions both table sets. Stock-page only by design.
    codes = tuple(sorted({str(it.get("code")) for it in items if it.get("code") not in (None, "")}))
    try:
        live_sold = live_last_sold(codes)
    except Exception:
        # A POS hiccup here must not break search; fall back to historic-only dates.
        log.exception("live_last_sold failed; serving historic last-purchased only")
        live_sold = {}
    for it in items:
        it["tracked"] = it.get("code") in tracked
        lv = live_sold.get(str(it.get("code")))
        if lv is not None:
            lv_str = lv.strftime("%Y-%m-%d %H:%M") if hasattr(lv, "strftime") else str(lv)
            # Both formats sort chronologically as strings; keep the most recent.
            if not it.get("last_purchased") or lv_str > it["last_purchased"]:
                it["last_purchased"] = lv_str
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
            # Window starts at the exact moment the count was taken (counted_at), so a
            # count set any time of day only deducts sales AFTER it; the counted number
            # already reflects earlier sales. Legacy counts with no counted_at fall back
            # to the business-day 08:00 boundary. (Both are local time, comparable to
            # POS RCPT_DATE; the 08:00 boundary matches the dashboard's daily totals.)
            start = count_window_start(c)
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
        events = events_by_item[s.id]
        info = compute_live(events, sold_map.get(s.itm_code, 0.0), s.alert_threshold)
        status = "unknown" if live_unavailable else info["status"]
        a = stock_analytics(events, info, s.alert_threshold)
        rows.append({
            "id": s.id, "itm_code": s.itm_code, "title": s.title, "subgroup": s.subgroup,
            "threshold": s.alert_threshold, "live": info["live"], "status": status,
            "q0": info["q0"], "d0": str(info["d0"]) if info["d0"] else None,
            "sold": info["sold"], "has_baseline": info["has_baseline"],
            "receives_since": info["receives"],
            # Derived analytics (pure arithmetic — no extra POS hit):
            "velocity": a["velocity"], "days_cover": a["days_cover"],
            "days_since_baseline": a["days_since_baseline"],
            "reorder_qty": a["reorder_qty"], "needs_reorder": a["needs_reorder"],
            "last_cost_cents": a["last_cost_cents"], "value_cents": a["value_cents"],
            "receive_count": a["receive_count"], "count_count": a["count_count"],
            "last_count_date": a["last_count_date"],
        })
    rows.sort(key=lambda r: (float("inf") if r["live"] is None else r["live"], (r["title"] or "").lower()))
    return rows, live_unavailable


@stock_bp.get("/api/stock/list")
def api_stock_list():
    rows, live_unavailable = _serialize_items()
    return jsonify({"items": rows, "live_unavailable": live_unavailable})


def _fmt_dt(dt, fmt="%Y-%m-%d %H:%M"):
    return dt.strftime(fmt) if dt is not None and hasattr(dt, "strftime") else None


@stock_bp.get("/api/stock/item/<int:item_id>")
def api_stock_item(item_id):
    """Full detail for one tracked item: live math, analytics, and the event ledger.

    Lazily loaded when a row is expanded so the main list stays snappy. Uses local
    SQLite for the ledger and ONE cached POS round-trip for this item's live sales.
    """
    si = db.session.get(StockItem, item_id)
    if si is None or not si.active:
        return jsonify({"ok": False, "error": "item not found"}), 404

    events = StockEvent.query.filter_by(stock_item_id=si.id).all()
    c = latest_count(events)
    sold_map, live_unavailable = {}, False
    if c is not None:
        try:
            sold_map = units_sold_since(((si.itm_code, count_window_start(c)),))
        except Exception:
            log.exception("units_sold_since failed for item detail %s", si.id)
            live_unavailable = True
    info = compute_live(events, sold_map.get(si.itm_code, 0.0), si.alert_threshold)
    status = "unknown" if live_unavailable else info["status"]
    analytics = stock_analytics(events, info, si.alert_threshold)

    last_sold = None
    try:
        ls = live_last_sold((si.itm_code,)).get(si.itm_code)
        last_sold = _fmt_dt(ls)
    except Exception:
        log.exception("live_last_sold failed for item detail %s", si.id)

    # Ledger newest-first; receives carry a line total at their recorded unit cost.
    ledger = []
    for e in sorted(events, key=lambda e: (e.event_date, e.created_at), reverse=True):
        is_receive = e.event_type == "receive"
        line_total = (int(round(e.qty * e.unit_cost_cents))
                      if is_receive and e.unit_cost_cents is not None else None)
        ledger.append({
            "id": e.id, "type": e.event_type, "qty": e.qty, "date": str(e.event_date),
            "counted_at": _fmt_dt(e.counted_at), "source": e.source,
            "unit_cost_cents": e.unit_cost_cents, "line_total_cents": line_total,
            "batch_id": e.batch_id, "note": e.note, "created_at": _fmt_dt(e.created_at),
        })
    receives = [l for l in ledger if l["type"] == "receive"]
    counts = [l for l in ledger if l["type"] == "count"]
    received_units = sum(l["qty"] for l in receives)
    received_value = sum(l["line_total_cents"] or 0 for l in receives)

    return jsonify({
        "ok": True,
        "item": {"id": si.id, "itm_code": si.itm_code, "title": si.title,
                 "subgroup": si.subgroup, "threshold": si.alert_threshold,
                 "created_at": _fmt_dt(si.created_at, "%Y-%m-%d")},
        "live": info["live"], "status": status, "live_unavailable": live_unavailable,
        "q0": info["q0"], "d0": str(info["d0"]) if info["d0"] else None,
        "sold": info["sold"], "receives_since": info["receives"],
        "has_baseline": info["has_baseline"], "analytics": analytics, "last_sold": last_sold,
        "ledger": ledger, "receives": receives, "counts": counts,
        "totals": {"received_units": received_units, "received_value_cents": received_value,
                   "events": len(ledger)},
    })


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
                              event_date=date.today(), counted_at=datetime.now(),
                              source="manual"))
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
                              event_date=date.today(), counted_at=datetime.now(),
                              source="manual"))
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


@stock_bp.get("/stock/receive")
def stock_receive_page():
    return render_template("stock_receive.html")


@stock_bp.post("/api/stock/receive/scan")
def api_stock_receive_scan():
    f = request.files.get("image")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "no image uploaded"}), 400
    if request.content_length and request.content_length > _MAX_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "image too large (max 15MB)"}), 413
    image_bytes = f.read()
    if not image_bytes:
        return jsonify({"ok": False, "error": "empty image"}), 400
    if len(image_bytes) > _MAX_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "image too large (max 15MB)"}), 413
    media_type = f.mimetype or "image/jpeg"
    try:
        lines = extract_invoice_lines(image_bytes, media_type=media_type)
    except Exception as e:
        log.exception("invoice OCR failed")
        return jsonify({"ok": False, "error": f"could not read invoice: {e}"}), 400
    catalog = load_catalog()
    matched = match_lines(lines, catalog)
    tracked = {s.itm_code for s in StockItem.query.filter_by(active=True).all()}
    for m in matched:
        code = (m.get("match") or {}).get("code")
        m["tracked"] = code in tracked if code else False
    return jsonify({"ok": True, "lines": matched})


@stock_bp.post("/api/stock/receive/confirm")
def api_stock_receive_confirm():
    data = _body()
    lines = data.get("lines") if isinstance(data, dict) else None
    if not lines:
        return jsonify({"ok": False, "error": "no lines to confirm"}), 400
    batch_id = str(uuid.uuid4())  # 36-char hyphenated, matches StockEvent.batch_id String(36)
    received = 0
    try:
        for ln in lines:
            itm_code = (str(ln.get("itm_code") or "")).strip()
            if not itm_code:
                continue
            try:
                qty = float(ln.get("qty"))
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            raw_cost = ln.get("unit_cost")
            try:
                cost_cents = int(round(float(raw_cost) * 100)) if raw_cost not in (None, "") else None
            except (TypeError, ValueError):
                cost_cents = None
            if cost_cents is not None and cost_cents < 0:
                cost_cents = None  # a negative cost is noise, not data
            title = (str(ln.get("title") or "")).strip()
            subgroup = (str(ln.get("subgroup") or "")).strip()

            si = StockItem.query.filter_by(itm_code=itm_code).first()
            if si and si.active:
                event_type = "receive"
            elif si and not si.active:
                si.active = True
                event_type = "receive"
            else:
                si = StockItem(itm_code=itm_code, title=title, subgroup=subgroup,
                               alert_threshold=_default_threshold(), active=True)
                db.session.add(si)
                db.session.flush()
                event_type = "count"  # first delivery is the baseline for a new item
            db.session.add(StockEvent(stock_item_id=si.id, event_type=event_type, qty=qty,
                                      event_date=date.today(), source="invoice",
                                      counted_at=(datetime.now() if event_type == "count" else None),
                                      unit_cost_cents=cost_cents, batch_id=batch_id))
            raw = (str(ln.get("raw_description") or "")).strip()
            if raw:
                upsert_alias(raw, itm_code)
            received += 1
        if received == 0:
            db.session.rollback()
            return jsonify({"ok": False, "error": "no valid lines"}), 400
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception("invoice receive confirm failed")
        return jsonify({"ok": False, "error": "could not save received items"}), 500
    return jsonify({"ok": True, "batch_id": batch_id, "received": received})


@stock_bp.post("/api/stock/receive/undo")
def api_stock_receive_undo():
    data = _body()
    batch_id = (str(data.get("batch_id") or "")).strip()
    if not batch_id:
        return jsonify({"ok": False, "error": "batch_id required"}), 400
    events = StockEvent.query.filter_by(batch_id=batch_id).all()
    affected = {e.stock_item_id for e in events}
    for e in events:
        db.session.delete(e)
    db.session.flush()
    removed_items = 0
    for sid in affected:
        if StockEvent.query.filter_by(stock_item_id=sid).count() == 0:
            si = db.session.get(StockItem, sid)
            if si is not None:
                db.session.delete(si)
                removed_items += 1
    db.session.commit()
    return jsonify({"ok": True, "events_removed": len(events), "items_removed": removed_items})
