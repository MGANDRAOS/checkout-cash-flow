from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from helpers_intelligence import get_dead_items_page

dead_items_bp = Blueprint("dead_items", __name__)


@dead_items_bp.get("/reports/dead-items")
def dead_items_page():
    return render_template("dead_items.html")


@dead_items_bp.get("/api/reports/dead-items")
def api_dead_items():
    q = (request.args.get("q", type=str) or "").strip()
    subgroup = (request.args.get("subgroup", type=str) or "").strip()

    dead_days = request.args.get("dead_days", type=int, default=60)
    page = request.args.get("page", type=int, default=1)
    page_size = request.args.get("page_size", type=int, default=50)

    payload = get_dead_items_page(
        q=q,
        subgroup=subgroup,
        dead_days=dead_days,
        page=page,
        page_size=page_size,
    )
    return jsonify(payload)
