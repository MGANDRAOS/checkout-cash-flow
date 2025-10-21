# routes/intelligence.py
from flask import Blueprint, render_template, jsonify, request
from helpers_intelligence import (
    get_kpis,
    get_receipts_by_day,
    get_hourly_last_business_day,
    get_top_items,
    get_subgroup_contribution,
    get_top_items_in_subgroup, 
    get_items_per_receipt_histogram, 
    get_receipt_amount_histogram,   
    get_subgroup_velocity,
    get_affinity_pairs,
    get_hourly_profile,      
    get_dow_profile      
)

intelligence_bp = Blueprint("intelligence", __name__)

@intelligence_bp.route("/intelligence")
def intelligence_home():
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


@intelligence_bp.route("/api/intelligence/subgroup")
def api_subgroup():
    return jsonify(get_subgroup_contribution(days=7))


@intelligence_bp.route("/api/intelligence/subgroup-top-items")
def api_subgroup_top_items():
    name = request.args.get("name", type=str, default="").strip()
    if not name:
        return jsonify([])
    return jsonify(get_top_items_in_subgroup(name, days=7, limit=10))


@intelligence_bp.route("/api/intelligence/items-per-receipt")
def api_items_per_receipt():
    return jsonify(get_items_per_receipt_histogram(days=7))


@intelligence_bp.route("/api/intelligence/receipt-amounts")
def api_receipt_amounts():
    return jsonify(get_receipt_amount_histogram(days=7))


@intelligence_bp.route("/api/intelligence/subgroup-velocity")
def api_subgroup_velocity():
    return jsonify(get_subgroup_velocity(days=14, top=8))


@intelligence_bp.route("/api/intelligence/affinity")
def api_affinity():
    return jsonify(get_affinity_pairs(days=30, top=15))


@intelligence_bp.route("/api/intelligence/hourly-profile")
def api_hourly_profile():
    return jsonify(get_hourly_profile(days=30))

@intelligence_bp.route("/api/intelligence/dow-profile")
def api_dow_profile():
    return jsonify(get_dow_profile(days=56))