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


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_cache = {}
CACHE_TTL_MINUTES = 30


# ==========================================================================
# Semantic Schema Definition for the POS Database
# ==========================================================================

POS_SCHEMA_DESCRIPTION = """
Database: SBCDB (POS)

TABLE ITEMS
- ITM_CODE (PK): unique item code.
- ITM_TITLE: name of the item.
- ITM_DESCRIPTION: textual description.
- ITM_BRAND: brand name.
- ITM_TYPE: product type.
- ITM_SUBGROUP (INT): foreign key → SUBGROUPS.SubGrp_PARENTID (integer link to subgroup id).
- ITM_SUPPLIER: supplier code.

TABLE ITEM_BARCODE
- ITM_CODE (FK → ITEMS.ITM_CODE): item code.
- ITM_PRICE: current or historical sale price of the item.
- DATE_CREATED: date the price/barcode record was created.
- DATE_MODIFIED: date the price/barcode record was last updated.

TABLE SUBGROUPS
- SubGrp_ID (INT PK, optional).
- SubGrp_Name (NVARCHAR): category name.
- SubGrp_PARENTID (INT): integer id linked from ITEMS.ITM_SUBGROUP.

TABLE HISTORIC_RECEIPT
- RCPT_ID (PK): unique receipt ID.
- RCPT_DATE: datetime of sale.
- RCPT_AMOUNT: total amount of the receipt.
- RCPT_NO: human-readable receipt number.

TABLE HISTORIC_RECEIPT_CONTENTS
- RCPT_ID (FK → HISTORIC_RECEIPT.RCPT_ID): link to receipt header.
- ITM_CODE (FK → ITEMS.ITM_CODE): sold item.
- RCPT_LINE: line number within the receipt.
- ITM_QUANTITY: quantity sold.
- ITM_PRICE: sale price at the time of transaction.

Relationships:
1. HISTORIC_RECEIPT ↔ HISTORIC_RECEIPT_CONTENTS via RCPT_ID
2. HISTORIC_RECEIPT_CONTENTS ↔ ITEMS via ITM_CODE
3. ITEMS ↔ ITEM_BARCODE via ITM_CODE
4. ITEMS ↔ SUBGROUPS via ITM_SUBGROUP → SubGrp_PARENTID

Rules for the AI:
- - When joining ITEMS and SUBGROUPS, always use:
    LEFT JOIN SUBGROUPS AS sg ON sg.SubGrp_PARENTID = ITEMS.ITM_SUBGROUP
  (both columns are INT). Do not compare to SubGrp_Name, which is NVARCHAR.
  NEVER join on SubGrp_PARENTID, as it causes duplicate rows.
- Only generate safe SELECT statements (no INSERT/UPDATE/DELETE).
- Always include TOP 100 (for MSSQL) unless summarizing.
- Prefer JOINs instead of subqueries for clarity.
- Use date filters like WHERE RCPT_DATE >= DATEADD(day, -7, GETDATE()).
- When aggregating sales, compute SUM(ITM_PRICE * ITM_QUANTITY).
- Use descriptive table aliases (hr, hrc, i, sg) for readability.
"""



def _cache_key(widget: str, data: dict):
    raw = json.dumps(data, sort_keys=True)
    return hashlib.md5(f"{widget}:{raw}".encode()).hexdigest()


def summarize_widget(widget: str, data: dict) -> str:
    key = _cache_key(widget, data)
    if key in _cache and datetime.datetime.now() - _cache[key]["time"] < timedelta(minutes=CACHE_TTL_MINUTES):
        return _cache[key]["summary"]

    serialized = json.dumps(data)[:4000]

    instructions = (
        "You are an analytics assistant for a retail store."
        "Write a one-sentence, human-friendly summary (max 50 words)"
        "of the data. Mention major trends or anomalies."
        "Time axis is strict 24-hour clock and shifted by +8 hours. make sure to adjust accordingly."
        "This line should be taken into consideration while you are thinking: Opening time is 08:00. Closing time is 2AM max the next day, so hours make sure to ignore the hours between 3AM and 7AM."
        "Currency is LBP, convert to USD where 1 USD = 89000 LBP."
    )

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            instructions=instructions,
            input=serialized,
            max_output_tokens=2000
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
            model="gpt-5-mini",
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
        model="gpt-5-mini",
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



def generate_narrative_from_sql(question: str, sql_query: str, rows: list) -> str:
    """
    Converts SQL results into a narrative, storytelling summary using GPT-5-mini.
    - question: the user’s natural language question
    - sql_query: the executed SQL statement
    - rows: list of dicts returned from execute_sql_readonly()
    """
    # Limit sample to avoid overloading the model
    sample_rows = rows[:25]

    # Serialize safely, converting datetime/decimal objects
    rows_json = json.dumps(
        sample_rows,
        ensure_ascii=False,
        indent=2,
        default=default_serializer
    )

    # Prompt for GPT-5-mini
    prompt = f"""
    You are the Checkout Analytics Assistant, a friendly data storyteller.
    You are given:
    1. A natural-language business question.
    2. The SQL query that was executed.
    3. The raw data rows returned by the query.

    Your task:
    Write a clear, concise, storytelling-style summary (3–6 sentences)
    that answers the question. Focus on trends, insights, and meaning.
    Mention totals, averages, top performers, or notable changes if visible.
    Speak like an experienced retail analyst — conversational but factual.

    Question:
    {question}

    SQL Query:
    {sql_query}

    Data (sample up to 25 rows):
    {rows_json}
    """

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            input=[{"role": "user", "content": prompt}],
        )
        story = response.output_text.strip()
        return story
    
    except Exception as e:
        print(f"[generate_narrative_from_sql] Error: {e}")
        traceback.print_exc()
        return "⚠️ Error generating narrative."

