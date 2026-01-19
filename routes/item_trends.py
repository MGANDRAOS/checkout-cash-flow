# routes/item_trends.py
# Fully-dynamic Item Trends report (date range + bucket + top N + filters)
# Thin blueprint routes returning either HTML or JSON.

from datetime import datetime, timedelta
from typing import List, Optional

from flask import Blueprint, render_template, jsonify, request

from helpers_intelligence import (
    get_item_trends,
    get_subgroups_list,
)

item_trends_bp = Blueprint("item_trends", __name__)


@item_trends_bp.route("/reports/item-trends")
def item_trends_page():
    """
    Renders the report page. All heavy data is fetched from JS via the API endpoint.
    """
    return render_template("report_item_trends.html")


@item_trends_bp.route("/api/reports/subgroups")
def api_subgroups():
    """
    Subgroup dropdown source.
    Returns: [{id, name}]
    """
    return jsonify(get_subgroups_list())


@item_trends_bp.route("/api/reports/item-trends")
def api_item_trends():
    """
    Fully dynamic report endpoint.

    Query params:
      - start_date=YYYY-MM-DD (required)
      - end_date=YYYY-MM-DD   (required)
      - bucket=daily|weekly|monthly (required)
      - top_n=int (required)
      - rank_by=total|last_bucket (optional, default total)
      - subgroup=str (optional, label)
      - item_codes=csv (optional, example: 123,456,789)
      - format=long|wide (optional, default long)  <-- wide can be added later, long is default
    """
    # ---------- Parse + validate (keep this strict to protect MSSQL) ----------
    start_date_str = (request.args.get("start_date") or "").strip()
    end_date_str = (request.args.get("end_date") or "").strip()
    bucket = (request.args.get("bucket") or "").strip().lower()
    rank_by = (request.args.get("rank_by") or "total").strip().lower()
    subgroup = (request.args.get("subgroup") or "").strip()
    fmt = (request.args.get("format") or "long").strip().lower()

    top_n = request.args.get("top_n", type=int)

    if not start_date_str or not end_date_str:
        return jsonify({"error": "start_date and end_date are required"}), 400

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    if start_date > end_date:
        return jsonify({"error": "start_date must be <= end_date"}), 400

    # Hard safety clamp (prevents accidental “5 years” queries freezing MSSQL)
    max_days = 730  # 24 months
    if (end_date - start_date).days > max_days:
        return jsonify({"error": f"Date range too large. Max {max_days} days."}), 400

    if bucket not in ("daily", "weekly", "monthly"):
        return jsonify({"error": "bucket must be one of: daily, weekly, monthly"}), 400

    if rank_by not in ("total", "last_bucket"):
        return jsonify({"error": "rank_by must be one of: total, last_bucket"}), 400

    if fmt not in ("long", "wide"):
        return jsonify({"error": "format must be one of: long, wide"}), 400

    if top_n is None:
        return jsonify({"error": "top_n is required"}), 400

    # Clamp top N to keep results sane
    top_n = max(1, min(int(top_n), 200))

    # Parse optional item_codes csv
    item_codes_csv = (request.args.get("item_codes") or "").strip()
    item_codes: Optional[List[str]] = None
    if item_codes_csv:
        # keep only non-empty segments
        raw = [p.strip() for p in item_codes_csv.split(",") if p.strip()]
        # safety clamp: don’t allow someone to pass 5000 codes
        item_codes = raw[:300]

    # Inclusive end_date (convert to exclusive end datetime by adding 1 day)
    # We keep dates in Python and let the helper handle the timestamp logic.
    result = get_item_trends(
        start_date=start_date,
        end_date=end_date,
        bucket=bucket,
        top_n=top_n,
        rank_by=rank_by,
        subgroup_label=subgroup if subgroup else None,
        item_codes=item_codes,
        output_format=fmt,
    )

    return jsonify(result)
