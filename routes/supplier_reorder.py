from flask import Blueprint, render_template, jsonify, request

from config import CURRENCY
from helpers_supplier_reorder import (
    unmatched_items, set_match, reorder_now, browse_catalog, list_categories,
)
from models import Supplier

supplier_reorder_bp = Blueprint("supplier_reorder", __name__)


def _body():
    return request.get_json(silent=True) or request.form


@supplier_reorder_bp.get("/supplier-reorder/match")
def supplier_reorder_match_page():
    return render_template("supplier_reorder_match.html")


@supplier_reorder_bp.get("/api/supplier-reorder/match/unmatched")
def api_supplier_reorder_unmatched():
    return jsonify({"items": unmatched_items()})


@supplier_reorder_bp.post("/api/supplier-reorder/match/confirm")
def api_supplier_reorder_confirm():
    data = _body()
    try:
        supplier_item_id = int(data.get("supplier_item_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "supplier_item_id required"}), 400
    itm_code = (str(data.get("itm_code") or "")).strip() or None
    if not set_match(supplier_item_id, itm_code):
        return jsonify({"ok": False, "error": "item not found"}), 404
    return jsonify({"ok": True})


@supplier_reorder_bp.get("/supplier-reorder")
def supplier_reorder_page():
    return render_template("supplier_reorder.html", currency=CURRENCY)


@supplier_reorder_bp.get("/api/supplier-reorder/reorder-now")
def api_supplier_reorder_now():
    return jsonify(reorder_now())


@supplier_reorder_bp.get("/api/supplier-reorder/catalog")
def api_supplier_reorder_catalog():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    return jsonify(browse_catalog(q=q, category=category, page=page))


@supplier_reorder_bp.get("/api/supplier-reorder/categories")
def api_supplier_reorder_categories():
    return jsonify({"categories": list_categories()})


@supplier_reorder_bp.get("/api/supplier-reorder/suppliers")
def api_supplier_reorder_suppliers():
    rows = Supplier.query.filter_by(active=True).order_by(Supplier.name).all()
    return jsonify({"suppliers": [{"id": s.id, "name": s.name} for s in rows]})
