# routes/items.py
from flask import Blueprint, render_template, request, jsonify, current_app
from helpers_items import list_items, list_subgroups, get_item_details, update_item_fields

items_bp = Blueprint("items", __name__)

@items_bp.route("/items")
def items_home():
    return render_template("items.html")


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
    Accepts either a rolling window (days) or explicit start_date / end_date range.
    If start_date & end_date are provided, they override `days`.
    """
    try:
        days = int(request.args.get("days", 30))
    except Exception:
        days = 30

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    biz_start_hour = int(current_app.config.get("BUSINESS_DAY_START_HOUR", 7))
    biz_end_hour   = int(current_app.config.get("BUSINESS_DAY_END_HOUR", 5))

    data = get_item_details(
        code=str(code),
        days=days,
        start_date=start_date,
        end_date=end_date,
        biz_start_hour=biz_start_hour,
        biz_end_hour=biz_end_hour
    )
    return jsonify(data)



@items_bp.route("/api/items/<code>", methods=["PATCH"])
def api_update_item(code):
    """Update item title, subgroup, and price in local MSSQL."""
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"success": False, "error": "Invalid JSON"}), 400

    title = data.get("title")
    subgroup = data.get("subgroup")
    price = data.get("price")

    # --- validations ---
    if title is not None and len(title.strip()) == 0:
        return jsonify({"success": False, "error": "Title cannot be empty."}), 400
    if price is not None:
        try:
            price = float(price)
            if price < 0:
                return jsonify({"success": False, "error": "Price cannot be negative."}), 400
        except Exception:
            return jsonify({"success": False, "error": "Invalid price value."}), 400

    ok, err = update_item_fields(code, title, subgroup, price)
    if not ok:
        return jsonify({"success": False, "error": err}), 500
    return jsonify({"success": True})