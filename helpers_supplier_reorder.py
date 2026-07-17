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
