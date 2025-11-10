# helpers_realtime.py
# --------------------------------------------------------------
# Realtime (open-day) analytics helpers
# Reads from RECEIPT / RECEIPT_CONTENTS (+ ITEMS, SUBGROUPS)
# Business day window: 08:00 → 02:59 next day
# --------------------------------------------------------------

from datetime import datetime
from helpers_intelligence import _connect  # <-- keep same connector used elsewhere

BUSINESS_DATE_SQL_RT = """
CASE 
  WHEN DATEPART(HOUR, r.RCPT_DATE) < 8 THEN DATEADD(DAY, -1, CAST(r.RCPT_DATE AS date))
  ELSE CAST(r.RCPT_DATE AS date)
END
"""

# --------------------------- KPIs ----------------------------
def rt_get_kpis(date_str: str):
    """Core realtime KPIs for the business day (08:00–02:59)."""
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        # total sales, receipts, avg ticket
        cur.execute(f"""
            SELECT 
              SUM(CAST(r.RCPT_AMOUNT AS float)) AS total_sales,
              COUNT(DISTINCT r.RCPT_ID) AS receipts
            FROM dbo.RECEIPT r
            WHERE {BUSINESS_DATE_SQL_RT} = ?
        """, (date,))
        row = cur.fetchone() or (0, 0)
        total_sales = float(row.total_sales or 0)
        receipts = int(row.receipts or 0)
        avg_ticket = (total_sales / receipts) if receipts else 0.0

        # items sold
        cur.execute(f"""
            SELECT SUM(CAST(c.ITM_QUANTITY AS float)) AS items_sold
            FROM dbo.RECEIPT r
            JOIN dbo.RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            WHERE {BUSINESS_DATE_SQL_RT} = ?
        """, (date,))
        items_row = cur.fetchone()
        items_sold = float(getattr(items_row, "items_sold", 0) or 0)

        # peak hour (live day)
        cur.execute(f"""
            WITH H AS (
              SELECT 
                ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24) AS biz_hour,
                SUM(CAST(r.RCPT_AMOUNT AS float)) AS sales
              FROM dbo.RECEIPT r
              WHERE {BUSINESS_DATE_SQL_RT} = ?
              GROUP BY ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)
            )
            SELECT TOP 1 biz_hour, sales
            FROM H
            ORDER BY sales DESC, biz_hour ASC
        """, (date,))
        hr = cur.fetchone()
        peak_hour = None
        if hr and getattr(hr, "biz_hour", None) is not None:
            # convert shifted 0..23 (starting 08:00) back to clock
            clock = (int(hr.biz_hour) + 8) % 24
            peak_hour = f"{clock:02d}:00"

        # growth vs yesterday / 4w average (optional, from historics)
        # Keep zero for now; wire later if desired
        growth_vs_y = 0.0
        growth_vs_4w = 0.0

    return {
        "total_sales": total_sales,
        "receipts": receipts,
        "avg_ticket": avg_ticket,
        "items_sold": items_sold,
        "peak_hour": peak_hour,
        "growth_vs_yesterday": growth_vs_y,
        "growth_vs_4week": growth_vs_4w,
    }

# ----------------------- Hourly (live) -----------------------
def rt_get_hourly(date_str: str):
    """Live hourly sales for the business day, shifted hour buckets."""
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT 
              ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24) AS biz_hour,
              SUM(CAST(r.RCPT_AMOUNT AS float)) AS sales
            FROM dbo.RECEIPT r
            WHERE {BUSINESS_DATE_SQL_RT} = ?
            GROUP BY ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)
            ORDER BY biz_hour
        """, (date,))
        return [{"hour": int(r.biz_hour), "sales": float(r.sales or 0)} for r in cur.fetchall()]

def rt_get_hourly_cumulative(date_str: str):
    """Running total across live business hours."""
    series = rt_get_hourly(date_str)
    total = 0.0
    out = []
    for p in series:
        total += p["sales"]
        out.append({"hour": p["hour"], "sales_total": total})
    return [{"label": "Live Day", "series": out}]

# ---------------------- Category (live) ----------------------
def rt_get_category(date_str: str):
    """Revenue per subgroup from live lines."""
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT 
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS subgroup,
              SUM(CAST(c.ITM_QUANTITY * c.ITM_PRICE AS float)) AS sales
            FROM dbo.RECEIPT r
            JOIN dbo.RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s 
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
               OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE {BUSINESS_DATE_SQL_RT} = ?
            GROUP BY LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown')))
            ORDER BY sales DESC
        """, (date,))
        return [{"subgroup": r.subgroup, "sales": float(r.sales or 0)} for r in cur.fetchall()]

# --------------------- Items Sold (live) ---------------------
def rt_get_items_sold(date_str: str):
    """Aggregated items sold table for the live business day."""
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT
              LTRIM(RTRIM(COALESCE(i.ITM_TITLE, '(Unknown)'))) AS item_name,
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS category,
              SUM(CAST(c.ITM_QUANTITY AS float)) AS total_qty,
              AVG(CAST(c.ITM_PRICE AS float)) AS avg_price,
              SUM(CAST(c.ITM_QUANTITY * c.ITM_PRICE AS float)) AS total_revenue
            FROM dbo.RECEIPT r
            JOIN dbo.RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s 
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
               OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE {BUSINESS_DATE_SQL_RT} = ?
            GROUP BY
              LTRIM(RTRIM(COALESCE(i.ITM_TITLE, '(Unknown)'))),
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown')))
            ORDER BY total_revenue DESC
        """, (date,))
        rows = cur.fetchall()

    total_rev = sum(float(r.total_revenue or 0) for r in rows) or 1.0
    out = []
    for r in rows:
        rev = float(r.total_revenue or 0)
        share = round((rev / total_rev) * 100, 1)
        out.append({
            "item_name": r.item_name,
            "category": r.category,
            "total_qty": float(r.total_qty or 0),
            "avg_price": float(r.avg_price or 0),
            "total_revenue": rev,
            "share": share,
        })
    return out

# --------------------- Receipts list (live) ------------------
def rt_get_receipts(date_str: str):
    """
    Receipt list for live day (click for details).
    Only header-level info here; lines are fetched via rt_get_receipt_detail.
    """
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT 
              r.RCPT_ID AS id,
              FORMAT(r.RCPT_DATE, 'HH:mm') AS time_str,
              SUM(CAST(c.ITM_QUANTITY AS float)) AS items_count,
              SUM(CAST(c.ITM_QUANTITY * c.ITM_PRICE AS float)) AS total
            FROM dbo.RECEIPT r
            LEFT JOIN dbo.RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            WHERE {BUSINESS_DATE_SQL_RT} = ?
            GROUP BY r.RCPT_ID, FORMAT(r.RCPT_DATE, 'HH:mm')
            ORDER BY r.RCPT_ID DESC
        """, (date,))
        return [
            {
                "id": int(r.id),
                "datetime": r.time_str,
                "items_count": float(r.items_count or 0),
                "total": float(r.total or 0),
            } for r in cur.fetchall()
        ]

# --------------- Receipt detail (click-to-open) ---------------
def rt_get_receipt_detail(rcpt_id: int):
    """
    Full invoice data for a single receipt:
    header, lines with item name/category, and totals.
    """
    with _connect() as cn:
        cur = cn.cursor()
        # Header
        cur.execute("""
            SELECT 
              r.RCPT_ID,
              r.RCPT_NO,
              r.RCPT_DATE,
              CAST(r.RCPT_AMOUNT AS float) AS total_amount
            FROM dbo.RECEIPT r
            WHERE r.RCPT_ID = ?
        """, (rcpt_id,))
        hdr = cur.fetchone()
        if not hdr:
            return {"exists": False}

        # Lines
        cur.execute("""
            SELECT
              c.RCPT_LINE,
              LTRIM(RTRIM(COALESCE(i.ITM_TITLE, '(Unknown)'))) AS item_name,
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS category,
              CAST(c.ITM_QUANTITY AS float) AS qty,
              CAST(c.ITM_PRICE AS float) AS unit_price,
              CAST(c.ITM_QUANTITY * c.ITM_PRICE AS float) AS line_total
            FROM dbo.RECEIPT_CONTENTS c
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s 
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
               OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE c.RCPT_ID = ?
            ORDER BY c.RCPT_LINE
        """, (rcpt_id,))
        lines = [{
            "line": int(r.RCPT_LINE),
            "item_name": r.item_name,
            "category": r.category,
            "qty": float(r.qty or 0),
            "unit_price": float(r.unit_price or 0),
            "line_total": float(r.line_total or 0),
        } for r in cur.fetchall()]

    return {
        "exists": True,
        "header": {
            "rcpt_id": int(hdr.RCPT_ID),
            "rcpt_no": int(hdr.RCPT_NO or 0) if getattr(hdr, "RCPT_NO", None) is not None else None,
            "datetime": hdr.RCPT_DATE.strftime("%Y-%m-%d %H:%M"),
            "total_amount": float(hdr.total_amount or 0),
        },
        "lines": lines,
    }
