# routes/cost_coverage.py
# Cost Coverage report: which items have no cost, ranked by revenue-at-risk.
import csv
import io

from flask import Blueprint, render_template, jsonify, request, Response

import config
from helpers_intelligence import get_cost_coverage

cost_coverage_bp = Blueprint("cost_coverage", __name__)

DEFAULT_DAYS = 90
MAX_DAYS = 730


def _days_param():
    try:
        days = int(request.args.get("days", DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    return max(1, min(days, MAX_DAYS))


def _subgroup_param():
    return (request.args.get("subgroup") or "").strip() or None


@cost_coverage_bp.route("/reports/cost-coverage")
def cost_coverage_page():
    return render_template("report_cost_coverage.html")


@cost_coverage_bp.route("/api/reports/cost-coverage")
def api_cost_coverage():
    days = _days_param()
    subgroup = _subgroup_param()
    try:
        data = get_cost_coverage(days=days, subgroup_label=subgroup)
    except Exception as e:  # keep the UI alive — structured error
        return jsonify({
            "coverage": {"active": 0, "uncosted_active": 0, "coverage_pct": 0.0},
            "at_risk": {"items": 0, "revenue": 0.0, "revenue_usd": 0.0},
            "dormant_uncosted": 0, "rows": [], "meta": {}, "error": str(e),
        }), 500

    rate = float(config.USD_EXCHANGE_RATE or 0)
    data["at_risk"]["revenue_usd"] = (data["at_risk"]["revenue"] / rate) if rate else 0.0
    return jsonify(data)


@cost_coverage_bp.route("/api/reports/cost-coverage/export-csv")
def api_cost_coverage_csv():
    days = _days_param()
    subgroup = _subgroup_param()
    try:
        data = get_cost_coverage(days=days, subgroup_label=subgroup)
    except Exception as e:
        return Response(f"Failed to build CSV: {e}", status=500, mimetype="text/plain")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["item_code", "item", "subgroup", "units", "revenue", "avg_price", "last_sold"])
    for r in data["rows"]:
        w.writerow([
            r["item_code"], r["item"], r["subgroup"], r["qty"],
            round(r["revenue"], 2), round(r["avg_price"], 2), r.get("last_sold") or "",
        ])

    sub = (subgroup or "all").replace(" ", "-")
    fname = f"cost_coverage_{days}d_{sub}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
