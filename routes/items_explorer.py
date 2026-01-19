# routes/items_explorer.py
from flask import Blueprint, render_template, jsonify, request
from helpers_intelligence import search_items_explorer

items_explorer_bp = Blueprint("items_explorer", __name__)

@items_explorer_bp.route("/items/explorer")
def items_explorer_home():
    """
    Items Explorer (Command Center)
    - Search + filters
    - Result table populated via /api/items/explorer
    """
    return render_template("items_explorer.html")


@items_explorer_bp.route("/api/items/explorer")
def api_items_explorer():
    """
    JSON endpoint used by Items Explorer page.

    Query params:
      - q:        free text search (item name or code)
      - subgroup: subgroup name (optional)
      - days:     lookback window (7/30/90 etc.)
      - trend:    'up' | 'down' | 'flat' | '' (optional)
      - limit:    max number of returned items (safety clamped)
    """
    q = (request.args.get("q", type=str, default="") or "").strip()
    subgroup = (request.args.get("subgroup", type=str, default="") or "").strip()
    days = request.args.get("days", type=int, default=30)
    trend = (request.args.get("trend", type=str, default="") or "").strip().lower()
    limit = request.args.get("limit", type=int, default=500)

    result = search_items_explorer(
        query=q,
        subgroup_name=subgroup,
        days=days,
        trend=trend,
        limit=limit
    )
    return jsonify(result)
