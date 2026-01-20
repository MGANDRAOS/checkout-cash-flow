# routes/invoices.py

from flask import Blueprint, render_template, request, jsonify
from datetime import datetime

from helpers_intelligence import (
    get_daily_items_detail,
    get_invoices_list,
    get_invoice_details,
    get_daily_items_summary,
    get_daily_items_for_date,
)

invoices_bp = Blueprint("invoices", __name__)

@invoices_bp.get("/invoices")
def invoices_page():
    # Supports deep-link from Item360 "See all invoices"
    prefill_item_code = (request.args.get("item_code", type=str) or "").strip()
    return render_template("invoices.html", prefill_item_code=prefill_item_code)


@invoices_bp.get("/api/invoices")
def api_invoices():
    payload = get_invoices_list(
        start_date=(request.args.get("start", type=str) or "").strip(),
        end_date=(request.args.get("end", type=str) or "").strip(),
        q=(request.args.get("q", type=str) or "").strip(),
        item_code=(request.args.get("item_code", type=str) or "").strip(),
        min_amount=request.args.get("min_amount", type=float, default=None),
        max_amount=request.args.get("max_amount", type=float, default=None),
        page=request.args.get("page", type=int, default=1),
        page_size=request.args.get("page_size", type=int, default=50),
    )
    return jsonify(payload)


@invoices_bp.get("/api/invoices/<rcpt_id>")
def api_invoice_details(rcpt_id):
    rows = get_invoice_details(rcpt_id=str(rcpt_id))
    return jsonify({"rcpt_id": str(rcpt_id), "rows": rows})


@invoices_bp.get("/api/invoices/daily-items")
def api_daily_items():
    payload = get_daily_items_summary(
        start_date=(request.args.get("start", type=str) or "").strip(),
        end_date=(request.args.get("end", type=str) or "").strip(),
        page=request.args.get("page", type=int, default=1),
        page_size=request.args.get("page_size", type=int, default=31),
    )
    return jsonify(payload)


@invoices_bp.get("/api/invoices/daily-items/<biz_date>")
def api_daily_items_one_day(biz_date):
    rows = get_daily_items_for_date(str(biz_date))
    return jsonify({"biz_date": str(biz_date), "rows": rows})


@invoices_bp.get("/api/invoices/daily-items")
def api_daily_items():
    # IMPORTANT: parse dates from query string (YYYY-MM-DD)
    start_str = (request.args.get("start") or "").strip()
    end_str = (request.args.get("end") or "").strip()

    # Optional filters
    item_code = (request.args.get("item_code") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()

    if not start_str or not end_str:
        return jsonify({"error": "start and end are required (YYYY-MM-DD)"}), 400

    start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

    rows = get_daily_items_summary(
        start_date=start_date,
        end_date=end_date,
        item_code=item_code,
        subgroup=subgroup
    )
    return jsonify(rows)


@invoices_bp.get("/api/invoices/daily-items/<biz_date>")
def api_daily_items_detail(biz_date):
    # biz_date path param: YYYY-MM-DD
    from datetime import datetime
    target_date = datetime.strptime(biz_date, "%Y-%m-%d").date()

    item_code = (request.args.get("item_code") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()

    rows = get_daily_items_detail(
        biz_date=target_date,
        item_code=item_code,
        subgroup=subgroup
    )
    return jsonify(rows)