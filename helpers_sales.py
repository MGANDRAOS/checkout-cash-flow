# helpers_sales.py
from datetime import datetime, timedelta
from collections import defaultdict
from helpers_intelligence import _connect
from pos_dates import biz_date_range_8h, cutoff_dt_8h


# ----------------------------------------------------------
# RANGE SALES SUMMARY (DAILY / MONTHLY)
# ----------------------------------------------------------
def get_sales_summary_range(from_str: str, to_str: str, mode: str = "daily"):
    """
    Returns total sales + breakdown for a business-date range.

    Inputs:
      - from_str: YYYY-MM-DD
      - to_str:   YYYY-MM-DD
      - mode:     "daily" | "monthly"

    Output:
      {
        "total_sales": float,
        "rows": [{"label": "2026-03-01", "total": 123.0}, ...],
        "meta": {"count": int, "avg": float}
      }
    """
    mode = (mode or "daily").strip().lower()
    if mode not in ("daily", "monthly"):
        mode = "daily"

    from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
    to_date   = datetime.strptime(to_str,   "%Y-%m-%d").date()
    if from_date > to_date:
        return {"total_sales": 0.0, "rows": [], "meta": {"count": 0, "avg": 0.0}}

    # Sargable outer bounds for the WHERE
    range_start = datetime(from_date.year, from_date.month, from_date.day, 8, 0, 0)
    range_end   = datetime(to_date.year, to_date.month, to_date.day, 8, 0, 0) + timedelta(days=1)

    BIZ_DATE = """CAST(CASE
        WHEN DATEPART(HOUR, r.RCPT_DATE) < 8
          THEN DATEADD(DAY, -1, CAST(r.RCPT_DATE AS date))
        ELSE CAST(r.RCPT_DATE AS date)
      END AS date)"""

    with _connect() as cn:
        cur = cn.cursor()
        if mode == "monthly":
            cur.execute(f"""
                SELECT
                  YEAR({BIZ_DATE})  AS yr,
                  MONTH({BIZ_DATE}) AS mo,
                  SUM(r.RCPT_AMOUNT) AS total
                FROM dbo.HISTORIC_RECEIPT r
                WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
                  AND {BIZ_DATE} BETWEEN ? AND ?
                GROUP BY YEAR({BIZ_DATE}), MONTH({BIZ_DATE})
                ORDER BY yr, mo;
            """, (range_start, range_end, from_date, to_date))
            rows = cur.fetchall()
            parsed_rows = [
                {"label": f"{r.yr}-{r.mo:02d}", "total": float(r.total or 0)}
                for r in rows
            ]
        else:
            cur.execute(f"""
                SELECT
                  {BIZ_DATE} AS label,
                  SUM(r.RCPT_AMOUNT) AS total
                FROM dbo.HISTORIC_RECEIPT r
                WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
                  AND {BIZ_DATE} BETWEEN ? AND ?
                GROUP BY {BIZ_DATE}
                ORDER BY label;
            """, (range_start, range_end, from_date, to_date))
            rows = cur.fetchall()
            parsed_rows = []
            for r in rows:
                try:
                    label_text = r.label.strftime("%Y-%m-%d")
                except Exception:
                    label_text = str(r.label)
                parsed_rows.append({"label": label_text, "total": float(r.total or 0)})

    total_sales = sum(r["total"] for r in parsed_rows)
    count = len(parsed_rows)
    return {
        "total_sales": total_sales,
        "rows": parsed_rows,
        "meta": {"count": count, "avg": total_sales / count if count else 0.0},
    }


# ----------------------------------------------------------
# DAILY SALES SUMMARY
# ----------------------------------------------------------
def get_sales_summary(date_str: str):
    """
    Daily KPI summary: today + yesterday + 4-week same-weekday comparison.
    Was 7 separate queries. Now 2: one multi-date aggregation + one peak hour.
    All WHERE clauses use datetime ranges (sargable — index on RCPT_DATE usable).
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Compute all 6 date windows in Python — (today, yesterday, 4x same weekday)
    all_dates = [d] + [d - timedelta(days=1)] + [d - timedelta(weeks=i + 1) for i in range(4)]
    ranges = [biz_date_range_8h(x) for x in all_dates]

    # Flatten into params: (idx, start, end) × 6 for the UNION ALL ranges CTE
    range_params = []
    for i, (s, e) in enumerate(ranges):
        range_params.extend([i, s, e])
    # Append today's range again for the peak-hour sub-query
    range_params.extend(list(ranges[0]))

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            WITH Ranges AS (
                SELECT ? AS idx, CAST(? AS datetime2) AS rs, CAST(? AS datetime2) AS re
                UNION ALL SELECT ?, ?, ?
                UNION ALL SELECT ?, ?, ?
                UNION ALL SELECT ?, ?, ?
                UNION ALL SELECT ?, ?, ?
                UNION ALL SELECT ?, ?, ?
            ),
            Aggregated AS (
                SELECT
                    rg.idx,
                    COALESCE(SUM(r.RCPT_AMOUNT), 0)   AS total_sales,
                    COUNT(DISTINCT r.RCPT_ID)          AS receipts
                FROM Ranges rg
                LEFT JOIN dbo.HISTORIC_RECEIPT r
                    ON r.RCPT_DATE >= rg.rs AND r.RCPT_DATE < rg.re
                GROUP BY rg.idx
            ),
            PeakHour AS (
                SELECT TOP 1
                    DATEPART(HOUR, r.RCPT_DATE) AS hr_real,
                    SUM(r.RCPT_AMOUNT)          AS hr_sales
                FROM dbo.HISTORIC_RECEIPT r
                WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
                GROUP BY DATEPART(HOUR, r.RCPT_DATE)
                ORDER BY hr_sales DESC
            )
            SELECT
                a.idx,
                a.total_sales,
                a.receipts,
                (SELECT hr_real FROM PeakHour) AS peak_hr
            FROM Aggregated a
            ORDER BY a.idx;
        """, range_params)

        rows = {int(r.idx): r for r in cur.fetchall()}

    def _sales(i):
        row = rows.get(i)
        return float(row.total_sales if row and row.total_sales else 0)

    def _rcpts(i):
        row = rows.get(i)
        return int(row.receipts if row and row.receipts else 0)

    today_sales    = _sales(0)
    today_rcpts    = _rcpts(0)
    y_sales        = _sales(1)
    four_week_avg  = sum(_sales(i) for i in range(2, 6)) / 4.0
    peak_hr_raw    = rows[0].peak_hr if rows.get(0) and rows[0].peak_hr is not None else None
    peak_hour      = f"{int(peak_hr_raw):02d}:00" if peak_hr_raw is not None else None

    avg_ticket          = today_sales / today_rcpts if today_rcpts else 0.0
    growth_vs_yesterday = ((today_sales - y_sales) / y_sales * 100.0) if y_sales else 0.0
    growth_vs_4w        = ((today_sales - four_week_avg) / four_week_avg * 100.0) if four_week_avg else 0.0

    return {
        "date": str(d),
        "total_sales": today_sales,
        "receipts": today_rcpts,
        "avg_ticket": avg_ticket,
        "growth_vs_yesterday": growth_vs_yesterday,
        "growth_vs_4week": growth_vs_4w,
        "peak_hour": peak_hour,
    }


# ----------------------------------------------------------
# HOURLY SALES (TODAY)
# ----------------------------------------------------------
def get_sales_by_hour(date_str: str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = biz_date_range_8h(d)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT
                ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24) AS biz_hour,
                SUM(r.RCPT_AMOUNT) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)
            ORDER BY biz_hour;
        """, (start, end))
        rows = cur.fetchall()
    seen = {int(r.biz_hour): float(r.total_sales or 0) for r in rows}
    return [{"hour": h, "sales": seen.get(h, 0.0)} for h in range(24)]


# ----------------------------------------------------------
# HOURLY SALES (SAME WEEKDAY LAST 4 WEEKS)
# ----------------------------------------------------------
def get_sales_by_hour_last4weeks(date_str: str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    past_dates = [d - timedelta(weeks=i + 1) for i in range(4)]
    ranges = [biz_date_range_8h(x) for x in past_dates]

    # params: (idx, date_str, start, end) × 4
    params = []
    for i, (pd, (s, e)) in enumerate(zip(past_dates, ranges)):
        params.extend([i, str(pd), s, e])

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            WITH Ranges AS (
                SELECT ? AS idx, CAST(? AS nvarchar(10)) AS biz_date,
                       CAST(? AS datetime2) AS rs, CAST(? AS datetime2) AS re
                UNION ALL SELECT ?, ?, ?, ?
                UNION ALL SELECT ?, ?, ?, ?
                UNION ALL SELECT ?, ?, ?, ?
            ),
            Hourly AS (
                SELECT
                    rg.idx,
                    rg.biz_date,
                    ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24) AS biz_hour,
                    SUM(r.RCPT_AMOUNT) AS total_sales
                FROM Ranges rg
                JOIN dbo.HISTORIC_RECEIPT r
                    ON r.RCPT_DATE >= rg.rs AND r.RCPT_DATE < rg.re
                GROUP BY rg.idx, rg.biz_date,
                         ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)
            )
            SELECT idx, biz_date, biz_hour, total_sales
            FROM Hourly
            ORDER BY idx, biz_hour;
        """, params)
        rows = cur.fetchall()

    by_idx: dict[int, dict[int, float]] = defaultdict(dict)
    for r in rows:
        by_idx[int(r.idx)][int(r.biz_hour)] = float(r.total_sales or 0)

    return [
        {
            "date": str(past_dates[i]),
            "series": [{"hour": h, "sales": by_idx[i].get(h, 0.0)} for h in range(24)]
        }
        for i in range(4)
    ]


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
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    all_dates = [d - timedelta(weeks=i) for i in range(5)]  # today + 4 past same weekdays
    ranges = [biz_date_range_8h(x) for x in all_dates]

    params = []
    for i, (pd, (s, e)) in enumerate(zip(all_dates, ranges)):
        params.extend([i, str(pd), s, e])

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            WITH Ranges AS (
                SELECT ? AS idx, CAST(? AS nvarchar(10)) AS biz_date,
                       CAST(? AS datetime2) AS rs, CAST(? AS datetime2) AS re
                UNION ALL SELECT ?, ?, ?, ?
                UNION ALL SELECT ?, ?, ?, ?
                UNION ALL SELECT ?, ?, ?, ?
                UNION ALL SELECT ?, ?, ?, ?
            ),
            Hourly AS (
                SELECT
                    rg.idx,
                    rg.biz_date,
                    ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24) AS biz_hour,
                    SUM(r.RCPT_AMOUNT) AS total_sales
                FROM Ranges rg
                JOIN dbo.HISTORIC_RECEIPT r
                    ON r.RCPT_DATE >= rg.rs AND r.RCPT_DATE < rg.re
                GROUP BY rg.idx, rg.biz_date,
                         ((DATEPART(HOUR, r.RCPT_DATE) + 24 - 8) % 24)
            )
            SELECT idx, biz_date, biz_hour, total_sales
            FROM Hourly
            ORDER BY idx, biz_hour;
        """, params)
        rows = cur.fetchall()

    by_idx: dict[int, dict[int, float]] = defaultdict(dict)
    for r in rows:
        by_idx[int(r.idx)][int(r.biz_hour)] = float(r.total_sales or 0)

    out = []
    for i, pd in enumerate(all_dates):
        hourly = [by_idx[i].get(h, 0.0) for h in range(24)]
        running, cumulative = 0.0, []
        for h, v in enumerate(hourly):
            running += v
            cumulative.append({"hour": h, "sales_total": running})
        out.append({"date": str(pd), "series": cumulative})
    return out


# ----------------------------------------------------------
# CATEGORY / SUBGROUP BREAKDOWN
# ----------------------------------------------------------
def get_sales_by_category(date_str: str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = biz_date_range_8h(d)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT TOP (20)
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS Subgroup,
              SUM(c.ITM_QUANTITY * c.ITM_PRICE) AS total_sales
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown')))
            ORDER BY total_sales DESC;
        """, (start, end))
        rows = cur.fetchall()
    return [{"subgroup": r.Subgroup, "sales": float(r.total_sales or 0)} for r in rows]


# ----------------------------------------------------------
# TOP PRODUCTS
# ----------------------------------------------------------
def get_top_products(date_str: str, limit: int = 20):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = biz_date_range_8h(d)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT TOP ({int(limit)})
              i.ITM_TITLE AS title,
              SUM(c.ITM_QUANTITY) AS qty,
              SUM(c.ITM_QUANTITY * c.ITM_PRICE) AS sales
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY i.ITM_TITLE
            ORDER BY sales DESC;
        """, (start, end))
        rows = cur.fetchall()
    return [
        {"title": r.title or "(Unknown)", "qty": int(r.qty or 0), "sales": float(r.sales or 0)}
        for r in rows
    ]


# ----------------------------------------------------------
# SLOW PRODUCTS (no sales last N days)
# ----------------------------------------------------------
def get_slow_products(days: int = 7):
    """Items not sold in the past N days. Limits scan to last 2 years of history."""
    cutoff = datetime.now().date() - timedelta(days=days)
    history_start = datetime.now() - timedelta(days=730)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT TOP (50)
              i.ITM_CODE, i.ITM_TITLE,
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS Subgroup,
              MAX(r.RCPT_DATE) AS LastSold
            FROM dbo.ITEMS i
            LEFT JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.ITM_CODE = i.ITM_CODE
            LEFT JOIN dbo.HISTORIC_RECEIPT r
                ON r.RCPT_ID = c.RCPT_ID AND r.RCPT_DATE >= ?
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            GROUP BY i.ITM_CODE, i.ITM_TITLE, s.SubGrp_Name
            HAVING MAX(r.RCPT_DATE) IS NULL OR MAX(r.RCPT_DATE) < ?
            ORDER BY MAX(r.RCPT_DATE) ASC;
        """, (history_start, cutoff))
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
            "last_sold": last,
        })
    return results


# ----------------------------------------------------------
# RECEIPTS TABLE (for drilldown)
# ----------------------------------------------------------
def get_receipts(date_str: str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = biz_date_range_8h(d)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT
              r.RCPT_ID,
              r.RCPT_DATE,
              COUNT(c.ITM_CODE) AS items_count,
              MAX(r.RCPT_AMOUNT) AS total
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY r.RCPT_ID, r.RCPT_DATE
            ORDER BY r.RCPT_DATE DESC;
        """, (start, end))
        rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            dt = r.RCPT_DATE.strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = str(r.RCPT_DATE)
        out.append({"id": r.RCPT_ID, "datetime": dt,
                    "items_count": int(r.items_count or 0), "total": float(r.total or 0)})
    return out


# ----------------------------------------------------------
# DAILY SALES - LAST 14 BUSINESS DAYS (ENDING YESTERDAY)
# ----------------------------------------------------------
def get_sales_last14days():
    """
    Returns total sales per business day for the last 14 days,
    ending yesterday, using sargable datetime range bounds.
    Example output: [{'date': '2025-10-11', 'sales_total': 5120000}, ...]
    """
    end_date   = datetime.now().date() - timedelta(days=1)
    start_date = end_date - timedelta(days=24)
    # Sargable outer bounds: start_date@08:00 → (end_date+1)@08:00
    range_start = datetime(start_date.year, start_date.month, start_date.day, 8, 0, 0)
    range_end   = datetime(end_date.year, end_date.month, end_date.day, 8, 0, 0) + timedelta(days=1)
    BIZ_DATE = """CAST(CASE
        WHEN DATEPART(HOUR, r.RCPT_DATE) < 8
          THEN DATEADD(DAY, -1, CAST(r.RCPT_DATE AS date))
        ELSE CAST(r.RCPT_DATE AS date)
      END AS date)"""
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"""
            SELECT
              {BIZ_DATE} AS business_date,
              SUM(r.RCPT_AMOUNT) AS sales_total
            FROM dbo.HISTORIC_RECEIPT r
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY {BIZ_DATE}
            ORDER BY business_date;
        """, (range_start, range_end))
        rows = cur.fetchall()
    sales_map = {str(r.business_date): float(r.sales_total or 0) for r in rows}
    out, current = [], start_date
    while current <= end_date:
        out.append({"date": str(current), "sales_total": sales_map.get(str(current), 0.0)})
        current += timedelta(days=1)
    return out


# ----------------------------------------------------------
# ALL ITEMS SOLD (FULL LIST FOR BUSINESS DAY)
# ----------------------------------------------------------
def get_items_sold(date_str: str):
    """
    Returns every item sold on the selected business day (08:00 → 08:00 next day),
    aggregated by item name and category.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = biz_date_range_8h(d)

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SELECT
              LTRIM(RTRIM(COALESCE(i.ITM_TITLE, '(Unknown)'))) AS item_name,
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown'))) AS category,
              SUM(c.ITM_QUANTITY) AS total_qty,
              AVG(c.ITM_PRICE) AS avg_price,
              SUM(c.ITM_QUANTITY * c.ITM_PRICE) AS total_revenue
            FROM dbo.HISTORIC_RECEIPT r
            JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY
              LTRIM(RTRIM(COALESCE(i.ITM_TITLE, '(Unknown)'))),
              LTRIM(RTRIM(COALESCE(s.SubGrp_Name, 'Unknown')))
            ORDER BY total_revenue DESC;
        """, (start, end))
        rows = cur.fetchall()

    total_revenue = sum(float(r.total_revenue or 0) for r in rows) or 1
    return [
        {
            "item_name": r.item_name,
            "category": r.category,
            "total_qty": float(r.total_qty or 0),
            "avg_price": float(r.avg_price or 0),
            "total_revenue": float(r.total_revenue or 0),
            "share": round((float(r.total_revenue or 0) / total_revenue) * 100, 1),
        }
        for r in rows
    ]
