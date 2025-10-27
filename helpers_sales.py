# helpers_sales.py
from datetime import datetime, timedelta
from helpers_intelligence import _connect

BUSINESS_OPEN_HOUR = 8  # 08:00
# Business date expression reused in WHERE clauses:
# Anything before 08:00 counts to the PREVIOUS business date.
BUSINESS_DATE_SQL = """
CASE 
  WHEN DATEPART(HOUR, r.RCPT_DATE) < 8 THEN DATEADD(DAY, -1, CAST(r.RCPT_DATE AS date))
  ELSE CAST(r.RCPT_DATE AS date)
END
"""
# Rotate real clock hour to "business hour" bucket where 0==08:00, 23==07:00
BIZ_HOUR_SQL = "((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)"

# ----------------------------------------------------------
# DAILY SALES SUMMARY
# ----------------------------------------------------------
def get_sales_summary(date_str: str):
    from datetime import datetime, timedelta
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    yesterday = date - timedelta(days=1)
    four_weeks_ago = [date - timedelta(weeks=i+1) for i in range(4)]

    with _connect() as cn:
        cur = cn.cursor()

        # --- Today (by business date)
        cur.execute(f"""
            SELECT
              SUM(r.RCPT_AMOUNT) AS total_sales,
              COUNT(DISTINCT r.RCPT_ID) AS receipts
            FROM dbo.HISTORIC_RECEIPT r
            WHERE {BUSINESS_DATE_SQL} = ?
        """, (date,))
        row = cur.fetchone()
        today_sales = float(row.total_sales or 0)
        today_receipts = int(row.receipts or 0)
        avg_ticket = today_sales / today_receipts if today_receipts else 0

        # --- Yesterday (by business date)
        cur.execute(f"""
            SELECT SUM(r.RCPT_AMOUNT) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            WHERE {BUSINESS_DATE_SQL} = ?
        """, (yesterday,))
        prev = cur.fetchone()
        y_sales = float(prev.total_sales or 0)
        growth_vs_yesterday = ((today_sales - y_sales) / y_sales * 100.0) if y_sales else 0.0

        # --- Same weekday over last 4 weeks (business date)
        totals = []
        for d in four_weeks_ago:
            cur.execute(f"""
                SELECT SUM(r.RCPT_AMOUNT) AS total_sales
                FROM dbo.HISTORIC_RECEIPT r
                WHERE {BUSINESS_DATE_SQL} = ?
            """, (d,))
            rw = cur.fetchone()
            totals.append(float(rw.total_sales or 0))
        avg_4w = (sum(totals) / len(totals)) if totals else 0.0
        growth_vs_4w = ((today_sales - avg_4w) / avg_4w * 100.0) if avg_4w else 0.0

        # --- Peak hour (return real clock like "20:00")
        cur.execute(f"""
            SELECT TOP 1
              DATEPART(HOUR, r.RCPT_DATE) AS hr_real,
              SUM(r.RCPT_AMOUNT) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            WHERE {BUSINESS_DATE_SQL} = ?
            GROUP BY DATEPART(HOUR, r.RCPT_DATE)
            ORDER BY total_sales DESC
        """, (date,))
        p = cur.fetchone()
        peak_hour = f"{int(p.hr_real):02d}:00" if p and p.hr_real is not None else None

    return {
        "date": str(date),
        "total_sales": today_sales,
        "receipts": today_receipts,
        "avg_ticket": avg_ticket,
        "growth_vs_yesterday": growth_vs_yesterday,
        "growth_vs_4week": growth_vs_4w,
        "peak_hour": peak_hour,
    }

# ----------------------------------------------------------
# HOURLY SALES (TODAY)
# ----------------------------------------------------------
def get_sales_by_hour(date_str: str):
    from datetime import datetime
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT
              {BIZ_HOUR_SQL} AS biz_hour,
              SUM(r.RCPT_AMOUNT) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            WHERE {BUSINESS_DATE_SQL} = ?
            GROUP BY {BIZ_HOUR_SQL}
            ORDER BY biz_hour
        """, (date,))
        rows = cur.fetchall()

    seen = {int(r.biz_hour): float(r.total_sales or 0) for r in rows}
    return [{"hour": h, "sales": seen.get(h, 0.0)} for h in range(24)]


# ----------------------------------------------------------
# HOURLY SALES (SAME WEEKDAY LAST 4 WEEKS)
# ----------------------------------------------------------
def get_sales_by_hour_last4weeks(date_str: str):
    from datetime import datetime, timedelta
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    past_dates = [date - timedelta(weeks=i+1) for i in range(4)]
    out = []
    with _connect() as cn:
        cur = cn.cursor()
        for d in past_dates:
            cur.execute(f"""
                SELECT
                  {BIZ_HOUR_SQL} AS biz_hour,
                  SUM(r.RCPT_AMOUNT) AS total_sales
                FROM dbo.HISTORIC_RECEIPT r
                WHERE {BUSINESS_DATE_SQL} = ?
                GROUP BY {BIZ_HOUR_SQL}
                ORDER BY biz_hour
            """, (d,))
            rows = cur.fetchall()
            seen = {int(r.biz_hour): float(r.total_sales or 0) for r in rows}
            out.append({
                "date": str(d),
                "series": [{"hour": h, "sales": seen.get(h, 0.0)} for h in range(24)]
            })
    return out


# ----------------------------------------------------------
# HOURLY CUMULATIVE SALES (TODAY + LAST 4 WEEKS)
# ----------------------------------------------------------
def get_sales_cumulative_by_hour(date_str: str):
    """
    Returns cumulative hourly sales for the selected date
    and the same weekday over the past 4 weeks.
    Each entry includes its date and a 24-hour series
    of running totals using the +8 business-hour rotation rule.
    Example output:
      [
        {"date": "2025-10-26", "series": [{"hour": 0, "sales_total": 1200}, ...]},
        {"date": "2025-10-19", "series": [{"hour": 0, "sales_total": 800}, ...]},
        ...
      ]
    """
    from datetime import datetime, timedelta
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    # include today + past 4 same weekdays
    all_dates = [date - timedelta(weeks=i) for i in range(0, 5)]
    out = []

    with _connect() as cn:
        cur = cn.cursor()
        for d in all_dates:
            cur.execute(f"""
                SELECT
                  {BIZ_HOUR_SQL} AS biz_hour,
                  SUM(r.RCPT_AMOUNT) AS total_sales
                FROM dbo.HISTORIC_RECEIPT r
                WHERE {BUSINESS_DATE_SQL} = ?
                GROUP BY {BIZ_HOUR_SQL}
                ORDER BY biz_hour
            """, (d,))
            rows = cur.fetchall()

            # Fill 24 hours with zeros
            hourly = [0.0] * 24
            for r in rows:
                hourly[int(r.biz_hour)] = float(r.total_sales or 0)

            # Build cumulative curve
            cumulative = []
            running = 0.0
            for h in range(24):
                running += hourly[h]
                cumulative.append({"hour": h, "sales_total": running})

            out.append({"date": str(d), "series": cumulative})

    return out



# ----------------------------------------------------------
# CATEGORY / SUBGROUP BREAKDOWN
# ----------------------------------------------------------
def get_sales_by_category(date_str: str):
    from datetime import datetime
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT TOP (20)
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS Subgroup,
              SUM(c.ITM_QUANTITY * c.ITM_PRICE) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE {BUSINESS_DATE_SQL} = ?
            GROUP BY LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown')))
            ORDER BY total_sales DESC
        """, (date,))
        rows = cur.fetchall()
    return [{"subgroup": r.Subgroup, "sales": float(r.total_sales or 0)} for r in rows]


# ----------------------------------------------------------
# TOP PRODUCTS
# ----------------------------------------------------------
def get_top_products(date_str: str, limit: int = 20):
    from datetime import datetime
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT TOP ({limit})
              i.ITM_TITLE AS title,
              SUM(c.ITM_QUANTITY) AS qty,
              SUM(c.ITM_QUANTITY * c.ITM_PRICE) AS sales
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            WHERE {BUSINESS_DATE_SQL} = ?
            GROUP BY i.ITM_TITLE
            ORDER BY sales DESC
        """, (date,))
        rows = cur.fetchall()
    return [
        {"title": r.title or "(Unknown)", "qty": int(r.qty or 0), "sales": float(r.sales or 0)}
        for r in rows
    ]



# ----------------------------------------------------------
# SLOW PRODUCTS (no sales last N days)
# ----------------------------------------------------------
def get_slow_products(days: int = 7):
    """
    Items not sold in the past N days.
    """
    cutoff = datetime.now().date() - timedelta(days=days)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT TOP (50)
              i.ITM_CODE, i.ITM_TITLE,
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS Subgroup,
              MAX(r.RCPT_DATE) AS LastSold
            FROM dbo.ITEMS i
            LEFT JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.ITM_CODE = i.ITM_CODE
            LEFT JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            GROUP BY i.ITM_CODE, i.ITM_TITLE, s.SubGrp_Name
            HAVING MAX(r.RCPT_DATE) IS NULL OR MAX(r.RCPT_DATE) < ?
            ORDER BY MAX(r.RCPT_DATE) ASC;
        """, (cutoff,))
        rows = cur.fetchall()

    results = []
    for r in rows:
        last = None
        if getattr(r, "LastSold", None):
            try:
                last = r.LastSold.strftime("%Y-%m-%d %H:%M")
            except Exception:
                last = str(r.LastSold)
        results.append({
            "code": r.ITM_CODE,
            "title": r.ITM_TITLE or "",
            "subgroup": r.Subgroup or "Unknown",
            "last_sold": last
        })
    return results


# ----------------------------------------------------------
# RECEIPTS TABLE (for drilldown)
# ----------------------------------------------------------
def get_receipts(date_str: str):
    from datetime import datetime
    date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT
              r.RCPT_ID,
              r.RCPT_DATE,
              COUNT(c.ITM_CODE) AS items_count,
              MAX(r.RCPT_AMOUNT) AS total  -- RCPT per receipt
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            WHERE {BUSINESS_DATE_SQL} = ?
            GROUP BY r.RCPT_ID, r.RCPT_DATE
            ORDER BY r.RCPT_DATE DESC
        """, (date,))
        rows = cur.fetchall()

    out = []
    for r in rows:
        try:
            dt = r.RCPT_DATE.strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = str(r.RCPT_DATE)
        out.append({
            "id": r.RCPT_ID,
            "datetime": dt,
            "items_count": int(r.items_count or 0),
            "total": float(r.total or 0)
        })
    return out


# ----------------------------------------------------------
# DAILY SALES - LAST 14 BUSINESS DAYS (ENDING YESTERDAY)
# ----------------------------------------------------------
def get_sales_last14days():
    """
    Returns total sales per business day for the last 14 days,
    ending yesterday, using BUSINESS_DATE_SQL to respect store hours.
    Example output: [{'date': '2025-10-11', 'sales_total': 5120000}, ...]
    """
    from datetime import datetime, timedelta
    end_date = datetime.now().date() - timedelta(days=1)
    start_date = end_date - timedelta(days=24)

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT
              {BUSINESS_DATE_SQL} AS business_date,
              SUM(r.RCPT_AMOUNT) AS sales_total
            FROM dbo.HISTORIC_RECEIPT r
            WHERE {BUSINESS_DATE_SQL} BETWEEN ? AND ?
            GROUP BY {BUSINESS_DATE_SQL}
            ORDER BY business_date
        """, (start_date, end_date))
        rows = cur.fetchall()

    # Convert results to list of dicts (fill missing days with 0)
    sales_map = {str(r.business_date): float(r.sales_total or 0) for r in rows}
    out = []
    current = start_date
    while current <= end_date:
        out.append({
            "date": str(current),
            "sales_total": sales_map.get(str(current), 0.0)
        })
        current += timedelta(days=1)
    return out