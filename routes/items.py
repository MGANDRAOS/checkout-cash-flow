# routes/items.py
from flask import Blueprint, render_template, request, jsonify
from helpers_items import list_items, list_subgroups  

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
    subgroup = (request.args.get("subgroup", "") or "").strip()            # existing text fallback
    subgroup_id = request.args.get("subgroup_id")                           # NEW
    try:
        subgroup_id = int(subgroup_id) if subgroup_id not in (None, "", "ALL") else None
    except Exception:
        subgroup_id = None

    data = list_items(
        page=page, page_size=page_size, q=q, sort=sort,
        subgroup=subgroup, subgroup_id=subgroup_id                         # NEW
    )
    return jsonify(data)



@items_bp.route("/api/items/subgroups")
def api_items_subgroups():  # ⬅️ NEW
    return jsonify(list_subgroups())