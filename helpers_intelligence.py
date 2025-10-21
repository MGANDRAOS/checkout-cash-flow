# helpers_intelligence.py
# Receipt-centric analytics for the Intelligence dashboard
# Business day window: starts 07:00, ends next day 05:00 (safe for late EOD)

import os
import pyodbc
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ---------- Connection ----------
def _conn_str() -> str:
    driver   = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
    server   = os.getenv("MSSQL_SERVER", "localhost,1433")
    database = os.getenv("MSSQL_DATABASE", "SBCDB")

    uid = os.getenv("MSSQL_UID")
    pwd = os.getenv("MSSQL_PWD")

    if uid and pwd:
        return f"Driver={{{driver}}};Server={server};Database={database};UID={uid};PWD={pwd};"
    # Trusted connection by default (local dev)
    trusted = os.getenv("MSSQL_TRUSTED", "yes").lower() in ("1", "true", "yes")
    if trusted:
        return f"Driver={{{driver}}};Server={server};Database={database};Trusted_Connection=yes;"
    raise RuntimeError("No MSSQL credentials provided (set MSSQL_UID/MSSQL_PWD or MSSQL_TRUSTED=yes).")

def _connect():
    return pyodbc.connect(_conn_str())

# ---------- Time window helpers ----------
def _last_business_window(cur) -> Optional[Tuple[datetime, datetime, datetime]]:
    """
    Returns (window_start, window_end, business_date) where:
      start  = BusinessDate @ 07:00
      end    = BusinessDate + 1 day @ 05:00  (exclusive)
      bdate  = BusinessDate (date at 07:00 boundary)

    BusinessDate is derived from MAX(RCPT_DATE) using a -7h shift.
    """
    cur.execute("""
        SET NOCOUNT ON;

        WITH X AS (
          SELECT CAST(DATEADD(HOUR,-7, MAX(RCPT_DATE)) AS date) AS BizDate
          FROM dbo.HISTORIC_RECEIPT
        )
        SELECT
          CAST(DATEADD(HOUR, 7, CAST(BizDate AS datetime2)) AS datetime2) AS WinStart,
          CAST(DATEADD(HOUR, 5, DATEADD(DAY, 1, CAST(BizDate AS datetime2))) AS datetime2) AS WinEnd,
          CAST(BizDate AS datetime2) AS BizDate
        FROM X;
    """)
    row = cur.fetchone()
    if not row or row.WinStart is None:
        return None
    return (row.WinStart, row.WinEnd, row.BizDate)

# ---------- Public API (used by routes) ----------
def get_kpis() -> Dict:
    """
    KPIs for the last business window:
      - total_receipts
      - avg_receipt_value
      - items_per_receipt
      - unique_items
    """
    with _connect() as cn:
        cur = cn.cursor()
        win = _last_business_window(cur)
        if not win:
            return {"total_receipts": 0, "avg_receipt_value": 0.0, "items_per_receipt": 0.0, "unique_items": 0}
        start, end, _ = win

        # total receipts + avg receipt value from HISTORIC_RECEIPT
        cur.execute("""
            SET NOCOUNT ON;
            SELECT
              COUNT(DISTINCT r.RCPT_ID)                                   AS total_receipts,
              COALESCE(SUM(r.RCPT_AMOUNT) * 1.0 / NULLIF(COUNT(DISTINCT r.RCPT_ID),0), 0.0) AS avg_receipt_value
            FROM dbo.HISTORIC_RECEIPT r
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?;
        """, (start, end))
        rrow = cur.fetchone()
        total_receipts = int(rrow.total_receipts or 0)
        avg_receipt    = float(rrow.avg_receipt_value or 0.0)

        # items per receipt + unique items from HISTORIC_RECEIPT_CONTENTS
        cur.execute("""
            SET NOCOUNT ON;
            SELECT
              COALESCE(SUM(c.ITM_QUANTITY), 0) AS total_items,
              COUNT(DISTINCT c.ITM_CODE)       AS unique_items
            FROM dbo.HISTORIC_RECEIPT_CONTENTS c
            WHERE c.RCPT_ID IN (
              SELECT r.RCPT_ID
              FROM dbo.HISTORIC_RECEIPT r
              WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            );
        """, (start, end))
        crow = cur.fetchone()
        total_items  = float(crow.total_items or 0.0)
        unique_items = int(crow.unique_items or 0)

        items_per_receipt = (total_items / total_receipts) if total_receipts > 0 else 0.0

        return {
            "total_receipts": total_receipts,
            "avg_receipt_value": round(avg_receipt, 2)/89000,  # convert to USD
            "items_per_receipt": round(items_per_receipt, 2),
            "unique_items": unique_items
        }

def get_receipts_by_day(days:int=7) -> List[Dict]:
    """
    Last N business days (grouped by business date using 07:00 boundary).
    """
    days = max(1, min(int(days), 60))  # safety clamp
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            WITH R AS (
              SELECT
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate,
                r.RCPT_AMOUNT
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS (
              SELECT MAX(BizDate) AS MaxBiz FROM R
            )
            SELECT TOP (?)
              CONVERT(varchar(10), R.BizDate, 23) AS [date],
              COUNT(*)                              AS receipts,
              SUM(R.RCPT_AMOUNT)                    AS amount
            FROM R
            CROSS JOIN LAST
            WHERE R.BizDate <= LAST.MaxBiz
              AND R.BizDate > DATEADD(DAY, -?+1, LAST.MaxBiz)
            GROUP BY R.BizDate
            ORDER BY R.BizDate DESC;
        """, (days, days))
        rows = cur.fetchall()
        return [{"date": r.date, "receipts": int(r.receipts or 0), "amount": float(r.amount or 0.0)} for r in rows]

def get_hourly_last_business_day() -> List[Dict]:
    """
    Receipts count by *clock hour* within the last business window
    (filter by [07:00 .. next-day 05:00), group by DATEPART(HOUR, RCPT_DATE)).
    """
    with _connect() as cn:
        cur = cn.cursor()
        win = _last_business_window(cur)
        if not win:
            return []
        start, end, _ = win
        cur.execute("""
            SET NOCOUNT ON;
            SELECT
              DATEPART(HOUR, r.RCPT_DATE) AS [hour],
              COUNT(*)                    AS receipts
            FROM dbo.HISTORIC_RECEIPT r
            WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            GROUP BY DATEPART(HOUR, r.RCPT_DATE)
            ORDER BY [hour];
        """, (start, end))
        return [{"hour": int(r.hour), "receipts": int(r.receipts or 0)} for r in cur.fetchall()]

def get_top_items(limit:int=10, days:int=1) -> List[Dict]:
    """
    Top items by quantity over the last <days> business days (default: last day).
    Safely handles ITM_TITLE (nvarchar) vs ITM_CODE (numeric) by forcing text label.
    """
    limit = max(1, min(int(limit), 50))
    days  = max(10, min(int(days), 30))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            WITH R AS (
              SELECT
                r.RCPT_ID,
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS (
              SELECT MAX(BizDate) AS MaxBiz FROM R
            ),
            CUT AS (
              SELECT RCPT_ID
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            )
            SELECT TOP (?)
              CAST(
                CASE 
                  WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> '' 
                    THEN i.ITM_TITLE 
                  ELSE CAST(c.ITM_CODE AS nvarchar(128))
                END
              AS nvarchar(128))                                  AS item,
              SUM(CAST(c.ITM_QUANTITY AS float))                 AS qty,
              SUM(CAST(c.ITM_QUANTITY AS float) * CAST(c.ITM_PRICE AS float)) AS amount
            FROM dbo.HISTORIC_RECEIPT_CONTENTS c
            JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
            LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE   -- keep join sargable; don't cast here
            GROUP BY CAST(
                CASE 
                  WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> '' 
                    THEN i.ITM_TITLE 
                  ELSE CAST(c.ITM_CODE AS nvarchar(128))
                END
              AS nvarchar(128))
            ORDER BY qty DESC, item ASC;
        """, (days, limit))
        return [
            {"item": r.item, "qty": float(r.qty or 0.0), "amount": float(r.amount or 0.0)}
            for r in cur.fetchall()
        ]

def get_payment_split() -> List[Dict]:
    """
    Placeholder — you didn't provide a payments table.
    Return empty list so the UI stays honest.
    """
    return []
