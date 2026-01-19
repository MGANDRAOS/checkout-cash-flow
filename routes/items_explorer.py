# routes/items_explorer.py
from flask import Blueprint, render_template, jsonify, request
from helpers_intelligence import search_items_explorer, get_item_daily_series, get_item_momentum_kpis


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


@items_explorer_bp.route("/api/items/explorer/item-series")
def api_item_series():
    """
    Item 360° drawer sparkline endpoint.
    Returns daily qty series for last 14 BizDates (0-filled).
    """
    item_code = (request.args.get("item_code", type=str, default="") or "").strip()
    days = request.args.get("days", type=int, default=30)
    lookback = request.args.get("lookback", type=int, default=14)

    if not item_code:
        return jsonify({"series": [], "error": "item_code is required"}), 400

    series = get_item_daily_series(item_code=item_code, days=days, lookback=lookback)
    return jsonify({"series": series})


# routes/items_explorer.py

from flask import Blueprint, request, jsonify
from helpers_intelligence import get_item_last_invoices  # <-- add this import

# ... your existing blueprint code ...


@items_explorer_bp.get("/api/items/360/invoices")
def api_item_360_invoices():
    """
    Drawer API: last N invoices where an item appears.

    Query params:
      - item_code (required)
      - days (optional, default 30)
      - limit (optional, default 10)
    """
    item_code = (request.args.get("item_code", type=str) or "").strip()
    days = request.args.get("days", type=int, default=30)
    limit = request.args.get("limit", type=int, default=10)

    rows = get_item_last_invoices(item_code=item_code, days=days, limit=limit)

    return jsonify({
        "item_code": item_code,
        "days": days,
        "limit": limit,
        "rows": rows
    })


@items_explorer_bp.get("/api/items/360/kpis")
def api_item_360_kpis():
    """
    Drawer API: momentum KPIs (days since last sold + peak hour)
    """
    item_code = (request.args.get("item_code", type=str) or "").strip()
    days = request.args.get("days", type=int, default=30)

    kpis = get_item_momentum_kpis(item_code=item_code, days=days)
    return jsonify(kpis)