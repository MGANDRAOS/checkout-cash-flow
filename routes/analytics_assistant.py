# routes/analytics_assistant.py
from flask import Blueprint, render_template, request, Response, stream_with_context
from helpers_ai import generate_streaming_response
from helpers_ai import generate_sql_query, generate_narrative_from_sql, execute_sql_readonly
import traceback

bp = Blueprint("analytics_assistant", __name__)

# --------------------------------------------------------------------------
# Render template (optional, if you want /analytics-assistant page itself)
# --------------------------------------------------------------------------
@bp.route("/analytics-assistant")
def analytics_assistant_page():
    return render_template("sales.html")   # since the widget lives inside sales.html

# --------------------------------------------------------------------------
# Stream endpoint called by analyticsAssistant.js
# --------------------------------------------------------------------------



@bp.route("/stream-analytics")
def stream_analytics():
    question = request.args.get("prompt", "").strip()
    if not question:
        return Response("No question provided.", status=400)

    try:
        # 1️⃣  Ask GPT to write SQL
        sql_query = generate_sql_query(question)

        # 2️⃣  Execute safely
        rows = execute_sql_readonly(sql_query)

        # 3️⃣  Ask GPT to narrate
        story = generate_narrative_from_sql(question, sql_query, rows)

        return Response(story, mimetype="text/plain")
    except Exception as e:
        traceback.print_exc()
        return Response(f"⚠️ Error: {e}", status=500)