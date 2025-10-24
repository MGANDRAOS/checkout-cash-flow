# routes/ai.py
from flask import Blueprint, request, jsonify
from helpers_ai import summarize_widget

ai_bp = Blueprint("ai", __name__)

@ai_bp.route("/api/ai/summarize", methods=["POST"])
def ai_summarize():
    """
    Accepts JSON payload { "widget": "...", "data": {...} }
    Returns: { "summary": "..." }
    """
    body = request.get_json(silent=True) or {}
    widget = body.get("widget", "unknown")
    data = body.get("data", {})

    summary = summarize_widget(widget, data)
    return jsonify({"summary": summary})
