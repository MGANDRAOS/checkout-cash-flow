from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from helpers_intelligence import get_dead_items_page

dead_items_bp = Blueprint("dead_items", __name__)


@dead_items_bp.get("/reports/dead-items")
def dead_items_page():
    return render_template("dead_items.html")


@dead_items_bp.get("/api/dead-items")
def api_dead_items():
    payload = get_dead_items_page(
        q=(request.args.get("q") or "").strip(),
        subgroup=(request.args.get("subgroup") or "").strip(),
        lookback_days=request.args.get("lookback_days", type=int, default=90),
        dead_days=request.args.get("dead_days", type=int, default=30),
        min_qty=request.args.get("min_qty", type=float, default=1.0),
        min_receipts=request.args.get("min_receipts", type=int, default=1),
        page=request.args.get("page", type=int, default=1),
        page_size=request.args.get("page_size", type=int, default=50),
    )
    return jsonify(payload)