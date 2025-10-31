# routes/sales.py
from flask import Blueprint, render_template, request, jsonify
from datetime import datetime
from helpers_sales import (
    get_sales_summary,
    get_sales_by_hour,
    get_sales_by_hour_last4weeks,
    get_sales_by_category,
    get_top_products,
    get_slow_products,
    get_receipts,
    get_sales_cumulative_by_hour,
    get_sales_last14days,
    get_items_sold
)

# Blueprint setup
sales_bp = Blueprint("sales", __name__)

# ----------------------------------------------------------
# MAIN PAGE
# ----------------------------------------------------------
@sales_bp.route("/sales")
def sales_home():
    """
    Render main POS Sales dashboard page.
    Default view shows today's data.
    """
    today = datetime.now().date().strftime("%Y-%m-%d")
    return render_template("sales.html", today=today)


# ----------------------------------------------------------
# API ROUTES
# ----------------------------------------------------------

@sales_bp.route("/api/sales/summary")
def api_sales_summary():
    """
    Returns today's summary (or a specific date if provided).
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_sales_summary(date)
    return jsonify(data)


@sales_bp.route("/api/sales/hourly")
def api_sales_hourly():
    """
    Returns hourly sales totals for the given date.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_sales_by_hour(date)
    return jsonify(data)


@sales_bp.route("/api/sales/hourly-4weeks")
def api_sales_hourly_4weeks():
    """
    Returns same weekday hourly sales over the past 4 weeks.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_sales_by_hour_last4weeks(date)
    return jsonify(data)

@sales_bp.route("/api/sales/hourly-cumulative")
def api_sales_hourly_cumulative():
    """
    Returns cumulative hourly sales totals for the given date.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_sales_cumulative_by_hour(date)
    return jsonify(data)



@sales_bp.route("/api/sales/category")
def api_sales_category():
    """
    Returns subgroup/category breakdown for the day.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_sales_by_category(date)
    return jsonify(data)

@sales_bp.route("/api/sales/items")
def api_sales_items():
    """
    Returns the full list of all items sold for the selected date.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_items_sold(date)
    return jsonify(data)



@sales_bp.route("/api/sales/top")
def api_sales_top():
    """
    Returns top N products by revenue.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    limit = int(request.args.get("limit", 20))
    data = get_top_products(date, limit)
    return jsonify(data)


@sales_bp.route("/api/sales/slow")
def api_sales_slow():
    """
    Returns products not sold in last N days.
    """
    days = int(request.args.get("days", 7))
    data = get_slow_products(days)
    return jsonify(data)


@sales_bp.route("/api/sales/receipts")
def api_sales_receipts():
    """
    Returns receipt list for the given day.
    """
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    data = get_receipts(date)
    return jsonify(data)


@sales_bp.route("/api/sales/daily-14days")
def api_sales_daily_14days():
    """
    Returns sales totals for the last 14 business days.
    """
    data = get_sales_last14days()
    return jsonify(data)


