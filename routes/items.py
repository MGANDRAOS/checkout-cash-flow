# routes/items.py
from flask import Blueprint, render_template, request, jsonify, current_app
from helpers_items import list_items, list_subgroups, get_item_details  

items_bp = Blueprint("items", __name__)

@items_bp.route("/items")
def items_home():
    return render_template("items.html")

# ...
@items_bp.route("/api/items")
def api_items():
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(200, max(5, int(request.args.get("page_size", 25))))
    q = (request.args.get("q", "") or "").strip()
    sort = (request.args.get("sort", "") or "").strip()

    # subgroup by ID (preferred)
    subgroup_id = request.args.get("subgroup_id")
    try:
        subgroup_id = int(subgroup_id) if subgroup_id not in (None, "", "ALL") else None
    except Exception:
        subgroup_id = None

    # NEW: inactivity filters
    inactive_days = request.args.get("inactive_days")
    try:
        inactive_days = int(inactive_days) if inactive_days not in (None, "", "0") else None
    except Exception:
        inactive_days = None

    never_sold = 1 if (request.args.get("never_sold") in ("1", "true", "True")) else 0

    data = list_items(
        page=page, page_size=page_size, q=q, sort=sort,
        subgroup_id=subgroup_id,
        inactive_days=inactive_days, never_sold=never_sold
    )
    return jsonify(data)



@items_bp.route("/api/items/subgroups")
def api_items_subgroups():  # ⬅️ NEW
    return jsonify(list_subgroups())


@items_bp.route("/api/items/<code>/details")
def api_item_details(code):
    """
    Read-only item profile used by the Items grid "View" action.
    Configurable via Flask config keys:
      BUSINESS_DAY_START_HOUR (default 7)
      BUSINESS_DAY_END_HOUR   (default 5)  # not used in grouping, kept for future
    """
    try:
        days = int(request.args.get("days", 30))
    except Exception:
        days = 30

    biz_start_hour = int(current_app.config.get("BUSINESS_DAY_START_HOUR", 7))
    biz_end_hour   = int(current_app.config.get("BUSINESS_DAY_END_HOUR", 5))

    data = get_item_details(
        code=str(code),
        days=days,
        biz_start_hour=biz_start_hour,
        biz_end_hour=biz_end_hour
    )
    return jsonify(data)