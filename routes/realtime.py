# routes/realtime.py
from flask import Blueprint, request, jsonify, render_template
from datetime import datetime
from helpers_realtime import (
    rt_get_kpis, rt_get_hourly, rt_get_hourly_cumulative,
    rt_get_category, rt_get_items_sold, rt_get_receipts, rt_get_receipt_detail
)

realtime_bp = Blueprint("realtime", __name__)

# ---------- Page (optional: if you ever want /realtime standalone) ----------
@realtime_bp.route("/realtime")
def realtime_page():
    today = datetime.now().date().strftime("%Y-%m-%d")
    return render_template("intelligence.html", today=today)

# ------------------------------ APIs ------------------------------
@realtime_bp.get("/api/realtime/kpis")
def api_rt_kpis():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_kpis(date))

@realtime_bp.get("/api/realtime/hourly")
def api_rt_hourly():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_hourly(date))

@realtime_bp.get("/api/realtime/hourly-cumulative")
def api_rt_hourly_cumulative():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_hourly_cumulative(date))

@realtime_bp.get("/api/realtime/category")
def api_rt_category():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_category(date))

@realtime_bp.get("/api/realtime/items")
def api_rt_items():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_items_sold(date))

@realtime_bp.get("/api/realtime/receipts")
def api_rt_receipts():
    date = request.args.get("date", datetime.now().date().strftime("%Y-%m-%d"))
    return jsonify(rt_get_receipts(date))

@realtime_bp.get("/api/realtime/receipt/<int:rcpt_id>")
def api_rt_receipt_detail(rcpt_id: int):
    return jsonify(rt_get_receipt_detail(rcpt_id))
