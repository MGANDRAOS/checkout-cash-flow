# routes/analytics_assistant.py
from flask import Blueprint, render_template, request, Response, stream_with_context, session
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
    """
    Enhanced Analytics Assistant
    ----------------------------
      Generates SQL from the natural-language question (stateless)
      Executes query safely via helpers_intelligence
      Generates narrative summary with GPT-5-mini (stateful)
         → remembers last conversation turn using response_id
    """

    question = request.args.get("prompt", "").strip()
    if not question:
        return Response("No question provided.", status=400)

    try:
        # --- Step 1: Generate SQL (stateless) ---
        sql_query = generate_sql_query(question)
        print(f"[SQL Generated]\n{sql_query}\n")

        # --- Step 2: Execute SQL safely ---
        rows = execute_sql_readonly(sql_query)
        print(f"[SQL Rows] → {len(rows)} returned\n")

        if not rows:
            return Response("No data found for this query.", mimetype="text/plain")

        # --- Step 3: Generate narrative (stateful) ---
        last_id = session.get("analytics_last_response_id")

        result = generate_narrative_from_sql(
            question=question,
            sql_query=sql_query,
            rows=rows,
            previous_response_id=last_id,   # 🔗 keep conversation thread
        )

        story = result.get("story", "")
        new_id = result.get("response_id")
        session["analytics_last_response_id"] = new_id

        print(f"[Story Generated] Response ID → {new_id}\n")

        return Response(story, mimetype="text/plain")

    except Exception as e:
        print(f"[stream_analytics] Error: {e}")
        traceback.print_exc()
        return Response(f"⚠️ Error: {e}", status=500)