# routes/intelligence.py
from flask import Blueprint, render_template, jsonify
from helpers_intelligence import (
    get_kpis,
    get_receipts_by_day,
    get_hourly_last_business_day,
    get_top_items,
    get_payment_split,
)

intelligence_bp = Blueprint("intelligence", __name__)

@intelligence_bp.route("/intelligence")
def intelligence_home():
    # Pure UI — JS fetches data
    return render_template("intelligence.html")

# --------- JSON endpoints consumed by modular JS ---------
@intelligence_bp.route("/api/intelligence/kpis")
def api_kpis():
    return jsonify(get_kpis())

@intelligence_bp.route("/api/intelligence/receipts-by-day")
def api_receipts_by_day():
    return jsonify(get_receipts_by_day(days=7))

@intelligence_bp.route("/api/intelligence/hourly-today")
def api_hourly_today():
    return jsonify(get_hourly_last_business_day())

@intelligence_bp.route("/api/intelligence/top-items")
def api_top_items():
    return jsonify(get_top_items(limit=10, days=1))

@intelligence_bp.route("/api/intelligence/payment-split")
def api_payment_split():
    return jsonify(get_payment_split())
