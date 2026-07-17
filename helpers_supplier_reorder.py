"""Supplier catalog logic: matching to tracked stock, reorder-now, browse, CRUD."""
from __future__ import annotations

from typing import List, Optional

from models import db, StockItem, SupplierItem
from helpers_invoice_match import rank_match


def tracked_catalog() -> List[dict]:
    """Active StockItems as [{code,title,subgroup}], the pool matching is scored against."""
    return [{"code": s.itm_code, "title": s.title, "subgroup": s.subgroup}
            for s in StockItem.query.filter_by(active=True).all()]


def unmatched_items() -> List[dict]:
    """Active SupplierItems with no itm_code yet, each with top fuzzy-match candidates."""
    catalog = tracked_catalog()
    items = (SupplierItem.query
             .filter_by(active=True, itm_code=None)
             .order_by(SupplierItem.category, SupplierItem.name)
             .all())
    out = []
    for item in items:
        out.append({
            "id": item.id, "name": item.name, "supplier": item.supplier.name,
            "category": item.category, "unit_price_usd_cents": item.unit_price_usd_cents,
            "candidates": rank_match(item.name, catalog, limit=5),
        })
    return out


def set_match(supplier_item_id: int, itm_code: Optional[str]) -> bool:
    """Confirm (or clear, with itm_code=None) a SupplierItem -> StockItem link."""
    item = db.session.get(SupplierItem, supplier_item_id)
    if item is None:
        return False
    item.itm_code = itm_code or None
    db.session.commit()
    return True


def _cheapest_first(itm_code: str) -> List[SupplierItem]:
    """All active matched SupplierItems for this itm_code, cheapest unit price first."""
    return (SupplierItem.query
            .filter_by(itm_code=itm_code, active=True)
            .order_by(SupplierItem.unit_price_usd_cents.asc())
            .all())


def reorder_now() -> dict:
    """StockItems needing reorder (per helpers_stock.stock_analytics — reused, not
    reimplemented), each priced from its cheapest matched SupplierItem, if any."""
    from models import StockEvent
    from helpers_stock import (
        units_sold_since, compute_live, latest_count, count_window_start, stock_analytics,
    )

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
            pairs.append((s.itm_code, count_window_start(c)))

    sold_map, live_unavailable = {}, False
    try:
        sold_map = units_sold_since(tuple(sorted(pairs)))
    except Exception:
        live_unavailable = True

    rows = []
    totals_by_supplier_cents = {}
    for s in items:
        events = events_by_item[s.id]
        info = compute_live(events, sold_map.get(s.itm_code, 0.0), s.alert_threshold)
        a = stock_analytics(events, info, s.alert_threshold)
        if not a["needs_reorder"]:
            continue
        candidates = _cheapest_first(s.itm_code)
        options = [{"supplier_id": c.supplier_id, "supplier": c.supplier.name,
                    "unit_price_usd_cents": c.unit_price_usd_cents,
                    "supplier_item_id": c.id} for c in candidates]
        chosen = options[0] if options else None
        line_total_cents = (chosen["unit_price_usd_cents"] * a["reorder_qty"]) if chosen else None
        if chosen and line_total_cents is not None:
            totals_by_supplier_cents[chosen["supplier"]] = (
                totals_by_supplier_cents.get(chosen["supplier"], 0) + line_total_cents
            )
        rows.append({
            "stock_item_id": s.id, "itm_code": s.itm_code, "title": s.title,
            "live": info["live"], "days_cover": a["days_cover"],
            "reorder_qty": a["reorder_qty"], "options": options,
            "chosen_supplier_item_id": chosen["supplier_item_id"] if chosen else None,
            "line_total_cents": line_total_cents,
        })
    rows.sort(key=lambda r: (r["days_cover"] if r["days_cover"] is not None else -1))
    return {
        "items": rows, "live_unavailable": live_unavailable,
        "totals_by_supplier_cents": totals_by_supplier_cents,
        "unpriced_count": sum(1 for r in rows if not r["options"]),
    }
