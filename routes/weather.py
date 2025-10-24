# routes/weather.py
from flask import Blueprint, request, jsonify
from helpers_weather import get_weather, get_weather_hourly_5weeks

weather_bp = Blueprint("weather", __name__)

@weather_bp.route("/api/weather")
def api_weather():
    """Return cached or live weather for given date (YYYY-MM-DD)."""
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "missing date"}), 400
    try:
        data = get_weather(date)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@weather_bp.route("/api/weather/hourly-5weeks")
def api_weather_hourly_5weeks():
    """
    Return hourly weather for the selected date and
    the same weekday across the previous 4 weeks.
    """
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "missing date"}), 400

    try:
        data = get_weather_hourly_5weeks(date)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500