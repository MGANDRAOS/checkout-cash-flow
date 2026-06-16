# routes/items_sold.py
# Items Sold report: pick a date range + optional subgroup, list everything sold.
import csv
import io
from datetime import datetime

from flask import Blueprint, render_template, jsonify, request, Response

import config
from helpers_intelligence import get_items_sold_range

items_sold_bp = Blueprint("items_sold", __name__)

MAX_RANGE_DAYS = 730  # 24 months — protects MSSQL from accidental huge scans


def _parse_params():
    """Returns ((start_date, end_date, subgroup_or_None), None) or (None, (msg, status))."""
    start_s = (request.args.get("start_date") or "").strip()
    end_s = (request.args.get("end_date") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()

    if not start_s or not end_s:
        return None, ("start_date and end_date are required", 400)
    try:
        start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_s, "%Y-%m-%d").date()
    except Exception:
        return None, ("Invalid date format. Use YYYY-MM-DD", 400)
    if start_d > end_d:
        return None, ("start_date must be <= end_date", 400)
    if (end_d - start_d).days > MAX_RANGE_DAYS:
        return None, (f"Date range too large. Max {MAX_RANGE_DAYS} days.", 400)

    return (start_d, end_d, subgroup or None), None


@items_sold_bp.route("/reports/items-sold")
def items_sold_page():
    """Renders the report shell; data is fetched client-side from the API."""
    return render_template("report_items_sold.html")


@items_sold_bp.route("/api/reports/items-sold")
def api_items_sold():
    parsed, err = _parse_params()
    if err:
        return jsonify({"error": err[0]}), err[1]
    start_d, end_d, subgroup = parsed

    try:
        data = get_items_sold_range(start_d, end_d, subgroup_label=subgroup)
    except Exception as e:  # keep the UI alive — return a structured error
        return jsonify({
            "rows": [], "totals": {"items": 0, "qty": 0.0, "revenue": 0.0},
            "meta": {}, "error": str(e),
        }), 500

    rate = float(config.USD_EXCHANGE_RATE or 0)
    totals = data["totals"]
    totals["revenue_usd"] = (totals["revenue"] / rate) if rate else 0.0
    totals["profit_usd"] = (totals.get("profit", 0.0) / rate) if rate else 0.0
    return jsonify(data)


@items_sold_bp.route("/api/reports/items-sold/export-csv")
def api_items_sold_csv():
    parsed, err = _parse_params()
    if err:
        return Response(err[0], status=err[1], mimetype="text/plain")
    start_d, end_d, subgroup = parsed

    try:
        data = get_items_sold_range(start_d, end_d, subgroup_label=subgroup)
    except Exception as e:
        return Response(f"Failed to build CSV: {e}", status=500, mimetype="text/plain")

    def _n(v, nd=2):
        # round when a number is present; blank cell for unknown (None)
        return round(v, nd) if v is not None else ""

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["subgroup", "item_code", "item", "qty", "unit_cost", "avg_price",
                "revenue", "total_cost", "profit", "margin_pct", "share_pct"])
    for r in data["rows"]:
        w.writerow([
            r["subgroup"], r["item_code"], r["item"], r["qty"],
            _n(r.get("unit_cost")), round(r["avg_price"], 2), round(r["revenue"], 2),
            _n(r.get("total_cost")), _n(r.get("profit")),
            _n(r.get("margin"), 1), r["share"],
        ])
    t = data["totals"]
    w.writerow([])
    w.writerow(["TOTAL", "", "", t["qty"], "", "", round(t["revenue"], 2),
                round(t.get("cost", 0.0), 2), round(t.get("profit", 0.0), 2),
                t.get("margin", 0.0), 100.0])

    sub = (subgroup or "all").replace(" ", "-")
    fname = f"items_sold_{start_d}_to_{end_d}_{sub}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
