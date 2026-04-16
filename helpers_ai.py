import os, json, hashlib, decimal
import datetime
import decimal
import json
from datetime import timedelta
from openai import OpenAI
import sqlalchemy
from flask import current_app
from helpers_intelligence import execute_sql_readonly
import traceback
import pandas as pd


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_cache = {}
CACHE_TTL_MINUTES = 30


# ==========================================================================
# Semantic Schema Definition for the POS Database
# ==========================================================================

POS_SCHEMA_DESCRIPTION = """
Database: SBCDB (POS)

Database: SBCDB (Point of Sale System)

TABLE: ITEMS
- ITM_CODE (INT, PK): unique item identifier.
- ITM_TITLE (NVARCHAR): item name as shown on receipt.
- ITM_DESCRIPTION (NVARCHAR): optional description.
- ITM_BRAND (SMALLINT): brand identifier or flag.
- ITM_TYPE (SMALLINT): item type.
- ITM_SUBGROUP (INT, FK → SUBGROUPS.SubGrp_ID): category ID.
- ITM_SUPPLIER (INT): supplier code.
(… other financial columns omitted for analytics.)

TABLE: SUBGROUPS
- SubGrp_ID (INT, PK): category identifier (e.g., 1 = Tobacco, 2 = Chips, 3 = Chocolate, etc.).
- SubGrp_Name (NVARCHAR): category name.
- SubGrp_PARENTID (INT): store branch ID (always 1 for your branch).
(ignore this field for joins)

TABLE: HISTORIC_RECEIPT
- RCPT_ID (INT, PK): receipt header ID.
- RCPT_DATE (SMALLDATETIME): sale timestamp in local time (UTC+2).
- RCPT_AMOUNT (NUMERIC): total sale amount in LBP.
- RCPT_NO (INT): visible receipt number.

TABLE: HISTORIC_RECEIPT_CONTENTS
- RCPT_ID (INT, FK → HISTORIC_RECEIPT.RCPT_ID)
- ITM_CODE (INT, FK → ITEMS.ITM_CODE)
- RCPT_LINE (SMALLINT): line number in receipt.
- ITM_QUANTITY (NUMERIC)
- ITM_PRICE (NUMERIC)
(Use ITM_PRICE × ITM_QUANTITY for revenue per line.)

RELATIONSHIPS
1. HISTORIC_RECEIPT ↔ HISTORIC_RECEIPT_CONTENTS via RCPT_ID  
2. HISTORIC_RECEIPT_CONTENTS ↔ ITEMS via ITM_CODE  
3. ITEMS ↔ SUBGROUPS via ITM_SUBGROUP → SubGrp_ID  

RULES FOR THE AI
- When joining ITEMS and SUBGROUPS, always use:
  ```sql
  LEFT JOIN SUBGROUPS AS sg ON sg.SubGrp_ID = i.ITM_SUBGROUP
- Never use SubGrp_PARENTID.
"""



def _cache_key(widget: str, data: dict):
    raw = json.dumps(data, sort_keys=True)
    return hashlib.md5(f"{widget}:{raw}".encode()).hexdigest()


STORE_CONTEXT = """
You are a sharp retail analyst for a drive-thru mini-market in Lebanon.
Store hours: 08:00–02:00 (next day). Hours 03:00–07:59 are closed — ignore them entirely.
Currency: LBP. Always convert key figures to USD (1 USD = 89,000 LBP) and show both.
Hours in the raw data use an internal index (0–23) shifted by +8 to get real clock time — e.g. index 0 = 08:00, index 16 = 00:00.
Top categories by margin: Tobacco, Alcohol, Energy Drinks. Daily staples: Water, Coffee, Soft Drinks. Snacks: Biscuits, Chocolate, Croissants.
Write in plain English. Be specific and concise — name exact hours, amounts, and percentages. No filler phrases like "It's worth noting" or "Overall".
"""

WIDGET_PROMPTS = {
    "sales_hourly": {
        "instructions": STORE_CONTEXT + """
You are analysing TODAY's hourly sales data vs the same weekday over the past 4 weeks.
Data format: array of {hour (0-based index), sales (LBP)}.
Your output: 2–3 punchy sentences covering:
1. Peak hour and its sales (convert to USD).
2. Quietest hour during open hours.
3. Whether today is pacing above or below the 4-week pattern for the same weekday, with a % difference if calculable.
Be specific: name real clock times (add 8 to each index, wrap at 24).
""",
        "input_hint": "Hourly sales for today (each item = one hour of business):"
    },

    "sales_category": {
        "instructions": STORE_CONTEXT + """
You are analysing today's sales breakdown by product category (subgroup).
Data format: array of {subgroup, sales (LBP)}.
Your output: 2–3 sentences covering:
1. The top category and its share of total sales (%).
2. Any surprising category — unexpectedly high or low vs typical mix (Tobacco/Alcohol usually dominate).
3. One actionable observation (e.g. a lagging staple category, a spike worth investigating).
Always mention total sales across all categories in LBP and USD.
""",
        "input_hint": "Category sales breakdown for today:"
    },

    "sales_hourly_cumulative": {
        "instructions": STORE_CONTEXT + """
You are analysing cumulative sales progression across the business day — today vs the same weekday over the past 4 weeks.
Data format: array of series, each with a date and cumulative sales by hour.
Your output: 2–3 sentences covering:
1. At what point in the day today's cumulative line diverged from the historical average (ahead or behind, and by how much).
2. The steepest sales window today (where the curve climbed fastest = busiest rush).
3. End-of-day projection: if today maintains its current pace, is it trending above or below the average day?
Name real clock times (index + 8, wrap at 24).
""",
        "input_hint": "Cumulative hourly sales series (today + past weeks):"
    },

    "sales_last14days": {
        "instructions": STORE_CONTEXT + """
You are analysing the last 14 business days of daily sales.
Data format: array of {date (YYYY-MM-DD), sales_total (LBP)}.
Your output: 3 sentences covering:
1. Best day and worst day in the period — dates and amounts in LBP + USD.
2. Overall trend direction: is revenue rising, falling, or flat? Include % change from day 1 to day 14.
3. Weekend effect: are Fri/Sat noticeably higher or lower than weekdays in this window?
""",
        "input_hint": "Daily sales for the last 14 business days:"
    },
}

def summarize_widget(widget: str, data: dict) -> str:
    key = _cache_key(widget, data)
    if key in _cache and datetime.datetime.now() - _cache[key]["time"] < timedelta(minutes=CACHE_TTL_MINUTES):
        return _cache[key]["summary"]

    prompt_cfg = WIDGET_PROMPTS.get(widget)
    if prompt_cfg:
        instructions = prompt_cfg["instructions"].strip()
        input_hint   = prompt_cfg.get("input_hint", "Data:")
    else:
        # Fallback for unknown widgets
        instructions = STORE_CONTEXT + "Write 2 concise sentences summarising the key insight from this data."
        input_hint   = "Data:"

    serialized = json.dumps(data, ensure_ascii=False)[:5000]
    user_input = f"{input_hint}\n{serialized}"

    try:
        response = client.responses.create(
            model="gpt-5.4-nano-2026-03-17",
            instructions=instructions,
            input=user_input,
            max_output_tokens=300
        )
        summary = response.output_text.strip()
    except Exception as e:
        summary = f"(AI summary unavailable: {e})"

    _cache[key] = {"summary": summary, "time": datetime.datetime.now()}
    return summary



# ==========================================================================
# AI SQL Query Generator for POS Database
# ==========================================================================

def generate_sql_query(natural_question: str) -> str:
    """
    Use GPT-5-mini to generate a safe, performant SQL query for the SBCDB POS database.
    Returns a text string containing only SQL (no explanations).
    """
    prompt = f"""
    You are a senior SQL analyst for a retail POS system.
    Your job is to translate natural questions into optimized SQL for Microsoft SQL Server.

    Schema reference:
    {POS_SCHEMA_DESCRIPTION}

    Requirements:
    - Only generate a single SELECT statement.
    - Never modify data (no INSERT, UPDATE, DELETE, DROP, TRUNCATE, CREATE).
    - Always alias tables clearly (short names).
    - Include TOP 100 unless user explicitly requests totals or aggregates.
    - Format code neatly.
    - Assume datetime column RCPT_DATE is in [HISTORIC_RECEIPT].
    - When computing revenue, use (ITM_PRICE * ITM_QUANTITY).
    - Prefer INNER JOINs for clarity.
    - Include WHERE clauses that match timeframes from the question (e.g., “this week”).
    - End the output with a semicolon.
    - Output ONLY the SQL text, nothing else.
    - If there is any type mismatch between columns, cast both sides to NVARCHAR before comparing.

    User question:
    {natural_question}
    """

    try:
        response = client.responses.create(
            model="gpt-5.4-nano-2026-03-17",
            input=[{"role": "user", "content": prompt}],
        )
        sql_query = response.output_text.strip().strip("`")
        print  (f"[generate_sql_query] Generated SQL:\n{sql_query}")
        return sql_query
    except Exception as e:
        print(f"[generate_sql_query] Error: {e}")
        return "SELECT 'Error generating SQL' AS message;"



def generate_streaming_response(prompt_text: str):
    """Stream GPT-5-mini output token by token using the modern Responses API."""
    stream = client.responses.create(
        model="gpt-5.4-nano-2026-03-17",
        input=[
            {
                "role": "system",
                "content": "You are the Checkout Analytics Assistant — an AI analyst that helps interpret sales data.",
            },
            {"role": "user", "content": prompt_text},
        ],
        stream=True,
    )

    for event in stream:
        # Text chunks arrive as response.output_text.delta events
        if event.type == "response.output_text.delta":
            yield event.delta
        elif event.type == "response.completed":
            break


        
def default_serializer(obj):
    """Safely convert datetime and decimal objects for JSON serialization."""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return str(obj)



def generate_narrative_from_sql(question: str, sql_query: str, rows: list, previous_response_id: str = None):
    """
    Converts SQL results into a management-style narrative using GPT-5-mini.
    Adds precomputed sales stats and retail context for accurate storytelling.
    Supports conversational chaining via previous_response_id.
    """

    if not rows:
        return {"story": f"No data found for query: {question}", "response_id": None}

    try:
        # --- Limit sample to avoid flooding the model ---
        sample_rows = rows[:25]
        df = pd.DataFrame(rows)
        df.columns = [c.lower() for c in df.columns]

        # Detect key columns (robust to naming variation)
        # --- Safe numeric field detection ---
        col_revenue = next((c for c in df.columns if "revenue" in c.lower()), None)
        col_price   = next((c for c in df.columns if "price" in c.lower() and "revenue" not in c.lower()), None)
        col_qty     = next((c for c in df.columns if "qty" in c.lower() or "quantity" in c.lower()), None)

        col_title = next((c for c in df.columns if "title" in c), None)
        col_cat = next((c for c in df.columns if "subgroup" in c or "category" in c), None)

        # Normalize numeric columns
        for col in [col_price, col_qty, col_revenue]:
            if col and col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # Compute summary metrics
        total_revenue = df[col_revenue].sum() if col_revenue else (df[col_price] * df[col_qty]).sum()
        unique_products = df[col_title].nunique() if col_title else 0
        total_items = len(df)

        top_by_revenue = (
            df.groupby(col_title)[col_revenue].sum().nlargest(3).to_dict()
            if col_title and col_revenue else {}
        )
        top_by_units = (
            df.groupby(col_title)[col_qty].sum().nlargest(3).to_dict()
            if col_title and col_qty else {}
        )
        top_categories = (
            df.groupby(col_cat)[col_revenue].sum().nlargest(3).to_dict()
            if col_cat and col_revenue else {}
        )

        summary_data = {
            "total_revenue_LBP": round(total_revenue, 2),
            "total_revenue_USD": round(total_revenue / 89000, 2),
            "total_items": total_items,
            "unique_products": unique_products,
            "top_by_revenue": top_by_revenue,
            "top_by_units": top_by_units,
            "top_categories": top_categories,
        }

        rows_json = json.dumps(sample_rows, ensure_ascii=False, indent=2, default=default_serializer)

        # --- Build narrative prompt ---
        prompt = f"""
            You are an experienced retail analyst writing a daily sales summary
            for a drive-thru mini-market in Lebanon (open 08:00–02:59).
            Speak like a human analyst — concise, factual, and insightful.

            Context:
            - Tobacco, Alcohol, and Energy Drinks are high-margin fast movers.
            - Water, Coffee, and Soft Drinks are daily staples.
            - Biscuits, Chocolate, and Croissants are snacks.
            - Food and Nuts categories are essentials.
            - Exclude after-hours activity (03:00–07:59).
            - Currency: LBP; show USD equivalent at 1 USD = 89,000 LBP.

            Your task:
            Write a short 3–5 sentence narrative summarizing yesterday’s activity.
            Include total sales, number of unique products, and highlight top
            performing items and categories. Mention what stood out, avoid generic filler.

            Question:
            {question}

            SQL Query:
            {sql_query}

            Computed Summary:
            {json.dumps(summary_data, ensure_ascii=False, indent=2)}

            Sample Data (up to 25 rows):
            {rows_json}
            """

        # --- Call GPT-5-mini with optional chaining ---
        response = client.responses.create(
            model="gpt-5.4-nano-2026-03-17",
            input=[{"role": "system", "content": "", "role": "user", "content": prompt}],
            previous_response_id=previous_response_id,
            max_output_tokens=3000            
        )

        story = response.output_text.strip()
        new_response_id = getattr(response, "id", None)

        return {"story": story, "response_id": new_response_id}

    except Exception as e:
        print(f"[generate_narrative_from_sql] Error: {e}")
        traceback.print_exc()
        return {"story": "⚠️ Error generating narrative.", "response_id": None}
