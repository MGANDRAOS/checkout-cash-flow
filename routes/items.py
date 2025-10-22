# routes/items.py
from flask import Blueprint, render_template, request, jsonify
from helpers_items import list_items

items_bp = Blueprint("items", __name__)

@items_bp.route("/items")
def items_home():
    return render_template("items.html")

@items_bp.route("/api/items")
def api_items():
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(200, max(5, int(request.args.get("page_size", 25))))
    q = (request.args.get("q", "") or "").strip()
    data = list_items(page=page, page_size=page_size, q=q)
    return jsonify(data)
