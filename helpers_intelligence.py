# helpers_intelligence.py
# Receipt-centric analytics for the Intelligence dashboard
# Business day window: starts 07:00, ends next day 05:00 (safe for late EOD)

import os
import pyodbc
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# ---------- Connection ----------
def _conn_str() -> str:
     driver   = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
     server   = os.getenv("MSSQL_SERVER", "155.117.44.163,65431\\SQLEXPRESS")
     database = os.getenv("MSSQL_DATABASE", "SBCDB")
     username = os.getenv("MSSQL_USERNAME", "mgandraos")
     password = os.getenv("MSSQL_PASSWORD", "Andr@o$00")


     return (
           f"Driver={{{driver}}};"
           f"Server={server};"
           f"Database={database};"
           f"Uid={username};"
           f"Pwd={password};"
           f"Encrypt=yes;"
           f"TrustServerCertificate=yes;"
     )  
    
    
    # ---------- Connection ----------
#def _conn_str() -> str:
 #   driver   = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
  #  server   = os.getenv("MSSQL_SERVER", "localhost,1433")
   # database = os.getenv("MSSQL_DATABASE", "SBCDB")


 #   return f"Driver={{{driver}}};Server={server};Database={database};Trusted_Connection=yes;"

def _connect():
    return pyodbc.connect(_conn_str())

def execute_sql_readonly(sql_query: str):
    """
    Executes a safe read-only SQL query on the POS database.
    Returns rows as list[dict].
    """
    query = sql_query.strip().lower()
    if not query.startswith("select"):
        raise ValueError("Only SELECT statements are allowed.")
    if ";" in query[:-1]:
        raise ValueError("Multiple statements detected; query rejected.")

    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(sql_query)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"[execute_sql_readonly] Error executing SQL: {e}")
        raise


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


def get_subgroup_contribution(days: int = 7, limit: int = 12):
    """
    Top subgroups over the last <days> business days (default 7).
    Resolves subgroup via SUBGROUPS:
      1) if ITEMS.ITM_SUBGROUP is numeric -> join by SubGrp_ID
      2) else join by SubGrp_Name (trimmed)
      3) else fallback to raw ITEMS.ITM_SUBGROUP text
      4) else 'Unknown'
    SQL-2008 safe (no TRY_CONVERT).
    """
    days = max(1, min(int(days), 60))
    limit = max(1, min(int(limit), 50))

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Label business days with a -7h shift (07:00 start → next-day 05:00 end)
            WITH R AS (
              SELECT r.RCPT_ID,
                     CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (  -- RCPT_IDs inside the last <days> business dates
              SELECT RCPT_ID
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            )

            SELECT TOP (?)
              COALESCE(
                  s_id.SubGrp_Name,
                  s_name.SubGrp_Name,
                  NULLIF(x.SubGrpText, N''),
                  N'Unknown'
              ) AS subgroup,
              SUM(CAST(c.ITM_QUANTITY AS float))                            AS qty,
              SUM(CAST(c.ITM_QUANTITY AS float) * CAST(c.ITM_PRICE AS float)) AS amount
            FROM dbo.HISTORIC_RECEIPT_CONTENTS AS c
            JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
            LEFT JOIN dbo.ITEMS AS i ON i.ITM_CODE = c.ITM_CODE

            -- Derive numeric ID (only digits) and a trimmed text
            CROSS APPLY (
              SELECT
                CASE
                  WHEN i.ITM_SUBGROUP IS NULL THEN NULL
                  WHEN LTRIM(RTRIM(i.ITM_SUBGROUP)) = N'' THEN NULL
                  -- numeric-only test: NOT LIKE any non-digit char
                  WHEN i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                  ELSE NULL
                END AS SubGrpID,
                LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpText
            ) AS x

            -- Prefer lookup by ID, else by name
            LEFT JOIN dbo.SUBGROUPS AS s_id
              ON s_id.SubGrp_ID = x.SubGrpID
            LEFT JOIN dbo.SUBGROUPS AS s_name
              ON LTRIM(RTRIM(s_name.SubGrp_Name)) = x.SubGrpText

            GROUP BY COALESCE(
                      s_id.SubGrp_Name,
                      s_name.SubGrp_Name,
                      NULLIF(x.SubGrpText, N''),
                      N'Unknown'
                     )
            ORDER BY amount DESC, subgroup ASC;
        """, (days, limit))

        rows = cur.fetchall()
        return [
            {"subgroup": r.subgroup, "qty": float(r.qty or 0.0), "amount": float(r.amount or 0.0)}
            for r in rows
        ]


def get_top_items_in_subgroup(subgroup_name: str, days: int = 7, limit: int = 10):
    """
    Top items (qty + amount) for a given subgroup label over the last <days> business days.
    subgroup_name is matched to SUBGROUPS.SubGrp_Name (case/whitespace-insensitive),
    but also works when ITEMS.ITM_SUBGROUP stores the name directly or a numeric ID.

    Returns: [{item, qty, amount}] ordered by qty desc.
    """
    if not subgroup_name or not str(subgroup_name).strip():
        return []

    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 50))

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Label business days with a -7h shift (07:00 start)
            WITH R AS (
              SELECT r.RCPT_ID,
                     CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (  -- RCPT_IDs inside the last <days> business dates
              SELECT RCPT_ID
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            ),
            -- Resolve each line's subgroup label using SUBGROUPS (ID or Name)
            Labeled AS (
              SELECT
                -- subgroup label (resolved)
                COALESCE(
                  s_id.SubGrp_Name,
                  s_nm.SubGrp_Name,
                  NULLIF(x.SubGrpText, N''),
                  N'Unknown'
                ) AS subgroup_label,
                -- item display label (title or code as text)
                CAST(
                  CASE
                    WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> N'' THEN i.ITM_TITLE
                    ELSE CAST(c.ITM_CODE AS nvarchar(128))
                  END AS nvarchar(128)
                ) AS item_label,
                CAST(c.ITM_QUANTITY AS float) AS qty,
                CAST(c.ITM_PRICE    AS float) AS price
              FROM dbo.HISTORIC_RECEIPT_CONTENTS AS c
              JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
              LEFT JOIN dbo.ITEMS AS i ON i.ITM_CODE = c.ITM_CODE

              CROSS APPLY (
                SELECT
                  CASE
                    WHEN i.ITM_SUBGROUP IS NULL THEN NULL
                    WHEN LTRIM(RTRIM(i.ITM_SUBGROUP)) = N'' THEN NULL
                    WHEN i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                    ELSE NULL
                  END AS SubGrpID,
                  LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpText
              ) AS x

              LEFT JOIN dbo.SUBGROUPS AS s_id
                ON s_id.SubGrp_ID = x.SubGrpID
              LEFT JOIN dbo.SUBGROUPS AS s_nm
                ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = x.SubGrpText
            )

            SELECT TOP (?)
              item_label AS item,
              SUM(qty)   AS qty,
              SUM(qty * price) AS amount
            FROM Labeled
            WHERE UPPER(LTRIM(RTRIM(subgroup_label))) = UPPER(LTRIM(RTRIM(?)))
            GROUP BY item_label
            ORDER BY qty DESC, item ASC;
        """, (days, limit, subgroup_name))

        rows = cur.fetchall()
        return [
            {"item": r.item, "qty": float(r.qty or 0.0), "amount": float(r.amount or 0.0)}
            for r in rows
        ]


def get_items_per_receipt_histogram(days: int = 7):
    """
    Buckets number of items per receipt over the last <days> business days.
    Bins: 1,2,3,4,5,6-10,11-15,16-20,20+
    """
    days = max(1, min(int(days), 60))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            WITH R AS (
              SELECT r.RCPT_ID, CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (
              SELECT RCPT_ID
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            ),
            ItemsPerReceipt AS (
              SELECT c.RCPT_ID, SUM(CAST(c.ITM_QUANTITY AS float)) AS itemcnt
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
              GROUP BY c.RCPT_ID
            )
            SELECT
              CASE
                WHEN itemcnt <= 1  THEN '1'
                WHEN itemcnt =  2  THEN '2'
                WHEN itemcnt =  3  THEN '3'
                WHEN itemcnt =  4  THEN '4'
                WHEN itemcnt =  5  THEN '5'
                WHEN itemcnt BETWEEN 6  AND 10 THEN '6-10'
                WHEN itemcnt BETWEEN 11 AND 15 THEN '11-15'
                WHEN itemcnt BETWEEN 16 AND 20 THEN '16-20'
                ELSE '20+'
              END AS bin,
              CASE
                WHEN itemcnt <= 1  THEN 1
                WHEN itemcnt =  2  THEN 2
                WHEN itemcnt =  3  THEN 3
                WHEN itemcnt =  4  THEN 4
                WHEN itemcnt =  5  THEN 5
                WHEN itemcnt BETWEEN 6  AND 10 THEN 6
                WHEN itemcnt BETWEEN 11 AND 15 THEN 7
                WHEN itemcnt BETWEEN 16 AND 20 THEN 8
                ELSE 9
              END AS seq,
              COUNT(*) AS cnt
            FROM ItemsPerReceipt
            GROUP BY
              CASE
                WHEN itemcnt <= 1  THEN '1'
                WHEN itemcnt =  2  THEN '2'
                WHEN itemcnt =  3  THEN '3'
                WHEN itemcnt =  4  THEN '4'
                WHEN itemcnt =  5  THEN '5'
                WHEN itemcnt BETWEEN 6  AND 10 THEN '6-10'
                WHEN itemcnt BETWEEN 11 AND 15 THEN '11-15'
                WHEN itemcnt BETWEEN 16 AND 20 THEN '16-20'
                ELSE '20+'
              END,
              CASE
                WHEN itemcnt <= 1  THEN 1
                WHEN itemcnt =  2  THEN 2
                WHEN itemcnt =  3  THEN 3
                WHEN itemcnt =  4  THEN 4
                WHEN itemcnt =  5  THEN 5
                WHEN itemcnt BETWEEN 6  AND 10 THEN 6
                WHEN itemcnt BETWEEN 11 AND 15 THEN 7
                WHEN itemcnt BETWEEN 16 AND 20 THEN 8
                ELSE 9
              END
            ORDER BY seq;
        """, (days,))
        rows = cur.fetchall()
        return [{"bin": r.bin, "count": int(r.cnt or 0)} for r in rows]


def get_receipt_amount_histogram(days: int = 7):
    """
    Buckets RCPT_AMOUNT over last <days> business days (LBP).
    Bins: 0–100k, 100–250k, 250–500k, 500k–1M, 1–2M, 2–5M, 5–10M, 10M+
    """
    days = max(1, min(int(days), 60))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            WITH R AS (
              SELECT r.RCPT_ID, r.RCPT_AMOUNT, CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (
              SELECT RCPT_ID, RCPT_AMOUNT
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            )
            SELECT
              CASE
                WHEN RCPT_AMOUNT <      100000 THEN '0–100k'
                WHEN RCPT_AMOUNT <      250000 THEN '100–250k'
                WHEN RCPT_AMOUNT <      500000 THEN '250–500k'
                WHEN RCPT_AMOUNT <     1000000 THEN '500k–1M'
                WHEN RCPT_AMOUNT <     2000000 THEN '1–2M'
                WHEN RCPT_AMOUNT <     5000000 THEN '2–5M'
                WHEN RCPT_AMOUNT <    10000000 THEN '5–10M'
                ELSE '10M+'
              END AS bin,
              CASE
                WHEN RCPT_AMOUNT <      100000 THEN 1
                WHEN RCPT_AMOUNT <      250000 THEN 2
                WHEN RCPT_AMOUNT <      500000 THEN 3
                WHEN RCPT_AMOUNT <     1000000 THEN 4
                WHEN RCPT_AMOUNT <     2000000 THEN 5
                WHEN RCPT_AMOUNT <     5000000 THEN 6
                WHEN RCPT_AMOUNT <    10000000 THEN 7
                ELSE 8
              END AS seq,
              COUNT(*) AS cnt
            FROM CUT
            GROUP BY
              CASE
                WHEN RCPT_AMOUNT <      100000 THEN '0–100k'
                WHEN RCPT_AMOUNT <      250000 THEN '100–250k'
                WHEN RCPT_AMOUNT <      500000 THEN '250–500k'
                WHEN RCPT_AMOUNT <     1000000 THEN '500k–1M'
                WHEN RCPT_AMOUNT <     2000000 THEN '1–2M'
                WHEN RCPT_AMOUNT <     5000000 THEN '2–5M'
                WHEN RCPT_AMOUNT <    10000000 THEN '5–10M'
                ELSE '10M+'
              END,
              CASE
                WHEN RCPT_AMOUNT <      100000 THEN 1
                WHEN RCPT_AMOUNT <      250000 THEN 2
                WHEN RCPT_AMOUNT <      500000 THEN 3
                WHEN RCPT_AMOUNT <     1000000 THEN 4
                WHEN RCPT_AMOUNT <     2000000 THEN 5
                WHEN RCPT_AMOUNT <     5000000 THEN 6
                WHEN RCPT_AMOUNT <    10000000 THEN 7
                ELSE 8
              END
            ORDER BY seq;
        """, (days,))
        rows = cur.fetchall()
        return [{"bin": r.bin, "count": int(r.cnt or 0)} for r in rows]


def get_subgroup_velocity(days: int = 14, top: int = 8):
    """
    Change in subgroup amount: last 7d vs prior 7d (business days).
    Returns top |delta%| subgroups.
    """
    days = max(14, min(int(days), 60))
    top  = max(1, min(int(top), 20))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Label business dates
            WITH R AS (
              SELECT r.RCPT_ID, CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (  -- last <days> business days
              SELECT R.RCPT_ID, R.BizDate
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            ),
            -- Resolve subgroup label (ID or Name)
            Labeled AS (
              SELECT
                COALESCE(s_id.SubGrp_Name, s_nm.SubGrp_Name, NULLIF(x.SubGrpText, N''), N'Unknown') AS subgroup_label,
                CAST(c.ITM_QUANTITY AS float) AS qty,
                CAST(c.ITM_PRICE    AS float) AS price,
                CUT.BizDate
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
              LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
              CROSS APPLY (
                SELECT
                  CASE
                    WHEN i.ITM_SUBGROUP IS NULL THEN NULL
                    WHEN LTRIM(RTRIM(i.ITM_SUBGROUP)) = N'' THEN NULL
                    WHEN i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                    ELSE NULL
                  END AS SubGrpID,
                  LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpText
              ) x
              LEFT JOIN dbo.SUBGROUPS s_id ON s_id.SubGrp_ID = x.SubGrpID
              LEFT JOIN dbo.SUBGROUPS s_nm ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = x.SubGrpText
            ),
            Agg AS (
              SELECT subgroup_label AS subgroup,
                     SUM(qty*price) AS amount,
                     BizDate
              FROM Labeled
              GROUP BY subgroup_label, BizDate
            ),
            MB AS ( SELECT MAX(BizDate) AS MaxBiz FROM Agg ),
            WinFlag AS (
              SELECT a.subgroup, a.amount, a.BizDate,
                     CASE WHEN a.BizDate >  DATEADD(DAY, -7, MB.MaxBiz) THEN 1 ELSE 0 END AS is_last7
              FROM Agg a CROSS JOIN MB
              WHERE a.BizDate > DATEADD(DAY, -14, MB.MaxBiz)
            ),
            WIN AS (
              SELECT subgroup,
                     SUM(CASE WHEN is_last7 = 1 THEN amount ELSE 0 END) AS last7,
                     SUM(CASE WHEN is_last7 = 0 THEN amount ELSE 0 END) AS prev7
              FROM WinFlag
              GROUP BY subgroup
            )
            SELECT TOP (?)
              s.subgroup,
              s.last7,
              s.prev7,
              s.delta_pct
            FROM (
              SELECT
                subgroup,
                last7,
                prev7,
                CASE WHEN prev7 > 0 THEN (last7/prev7) - 1 ELSE NULL END AS delta_pct
              FROM WIN
            ) AS s
            ORDER BY
              CASE WHEN s.delta_pct IS NULL THEN 0 ELSE ABS(s.delta_pct) END DESC,
              s.subgroup ASC;
        """, (days, top))
        rows = cur.fetchall()
        return [
            {
                "subgroup": r.subgroup,
                "last7": float(r.last7 or 0.0),
                "prev7": float(r.prev7 or 0.0),
                "delta_pct": None if r.delta_pct is None else float(r.delta_pct)
            }
            for r in rows
        ]


def get_affinity_pairs(days: int = 30, top: int = 15):
    """
    Top co-occurring item pairs over the last <days> business days (default 30).
    - De-duplicates per receipt (an item counted once per receipt).
    - Returns [{a, b, co_count, coverage_pct, lift}]
      where:
        coverage_pct = co_count / total_receipts
        lift = (co_count * total_receipts) / (count(a) * count(b))
    """
    days = max(1, min(int(days), 60))
    top  = max(1, min(int(top), 50))

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Label business days (start 07:00)
            WITH R AS (
              SELECT r.RCPT_ID, CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (  -- target window receipts
              SELECT R.RCPT_ID
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            ),
            -- Build a stable item label (title if present, else code as text)
            LinesRaw AS (
              SELECT c.RCPT_ID,
                     CAST(
                       CASE
                         WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> N'' THEN i.ITM_TITLE
                         ELSE CAST(c.ITM_CODE AS nvarchar(128))
                       END AS nvarchar(128)
                     ) AS item_label
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN CUT ON CUT.RCPT_ID = c.RCPT_ID
              LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
            ),
            -- De-duplicate per receipt/item (so a pair is counted once per receipt)
            Lines AS (
              SELECT DISTINCT RCPT_ID, item_label
              FROM LinesRaw
            ),
            ItemCnt AS (
              SELECT item_label, COUNT(DISTINCT RCPT_ID) AS rcpt_count
              FROM Lines
              GROUP BY item_label
            ),
            Total AS (
              SELECT COUNT(DISTINCT RCPT_ID) AS total_rcpts FROM Lines
            ),
            Pairs AS (
              SELECT
                a.item_label AS a_label,
                b.item_label AS b_label,
                COUNT(*)     AS co_count
              FROM Lines a
              JOIN Lines b
                ON a.RCPT_ID = b.RCPT_ID
               AND a.item_label < b.item_label       -- lexicographic to avoid dup/self-pairs
              GROUP BY a.item_label, b.item_label
            )
            SELECT TOP (?)
              p.a_label AS a,
              p.b_label AS b,
              p.co_count,
              CAST(p.co_count * 1.0 / NULLIF(t.total_rcpts,0) AS float)                       AS coverage_pct,
              CAST(p.co_count * 1.0 * t.total_rcpts / NULLIF(ia.rcpt_count * ib.rcpt_count,0) AS float) AS lift
            FROM Pairs p
            CROSS JOIN Total t
            JOIN ItemCnt ia ON ia.item_label = p.a_label
            JOIN ItemCnt ib ON ib.item_label = p.b_label
            WHERE p.co_count >= 2         -- tiny noise filter
            ORDER BY p.co_count DESC, a, b;
        """, (days, top))

        rows = cur.fetchall()
        return [
            {
                "a": r.a, "b": r.b,
                "co_count": int(r.co_count or 0),
                "coverage_pct": float(r.coverage_pct or 0.0),
                "lift": None if r.lift is None else float(r.lift)
            }
            for r in rows
        ]


def get_hourly_profile(days: int = 30):
    """
    Average receipts per business hour over the last <days> DISTINCT business days with receipts.
    Always returns 24 rows (biz_hour 0..23 where 0 == 07:00 local).
    - BizDate = CAST(DATEADD(HOUR,-7, RCPT_DATE) AS date)
    - BizHour = DATEPART(HOUR, DATEADD(HOUR,-7, RCPT_DATE))
    """
    days = max(1, min(int(days), 90))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Shift to business calendar
            WITH R AS (
              SELECT
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date)   AS BizDate,
                DATEPART(HOUR, DATEADD(HOUR,-7, r.RCPT_DATE)) AS BizHour
              FROM dbo.HISTORIC_RECEIPT r
            ),

            -- Take the last N DISTINCT business days that actually have receipts
            DistinctDays AS (
              SELECT DISTINCT BizDate FROM R
            ),
            Ranked AS (
              SELECT BizDate, ROW_NUMBER() OVER (ORDER BY BizDate DESC) AS rn
              FROM DistinctDays
            ),
            LastN AS (
              SELECT BizDate FROM Ranked WHERE rn <= ?
            ),

            -- 24 business hours (0..23), 0 == 07:00 local
            H AS (
              SELECT 0 AS h UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
              UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
              UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL SELECT 16 UNION ALL SELECT 17
              UNION ALL SELECT 18 UNION ALL SELECT 19 UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23
            ),

            -- Count receipts per hour across those days
            Hourly AS (
              SELECT R.BizHour, COUNT(*) AS rcpts
              FROM R
              JOIN LastN L ON L.BizDate = R.BizDate
              GROUP BY R.BizHour
            ),
            DayCount AS ( SELECT COUNT(*) AS days_total FROM LastN )

            SELECT
              H.h AS BizHour,
              CAST(COALESCE(Hourly.rcpts,0) AS float) / NULLIF(DC.days_total,0) AS avg_rcpts,
              COALESCE(Hourly.rcpts,0) AS total_rcpts,
              DC.days_total AS days_total
            FROM H
            CROSS JOIN DayCount DC
            LEFT JOIN Hourly ON Hourly.BizHour = H.h
            ORDER BY H.h;
        """, (days,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            biz_hour = int(r.BizHour)
            clock_hour = (biz_hour + 7) % 24  # map back to local clock hour 07..06
            out.append({
                "biz_hour": biz_hour,
                "clock_hour": clock_hour,
                "avg_receipts": float(r.avg_rcpts or 0.0),
                "total_receipts": int(r.total_rcpts or 0),
                "days_present": int(r.days_total or 0),
            })
        return out


def get_dow_profile(days: int = 56):
    """
    Average receipts per business day-of-week over the last <days> business days.
    Uses Monday=0 .. Sunday=6 via a fixed Monday anchor (2000-01-03).
    Returns: [{dow_index:int, dow_label:str, avg_receipts:float}]
    """
    days = max(7, min(int(days), 140))
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            WITH R AS (
              SELECT CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
            ),
            LAST AS ( SELECT MAX(BizDate) AS MaxBiz FROM R ),
            CUT AS (
              SELECT BizDate
              FROM R CROSS JOIN LAST
              WHERE R.BizDate BETWEEN DATEADD(DAY, -?+1, LAST.MaxBiz) AND LAST.MaxBiz
            ),
            Daily AS (
              SELECT CUT.BizDate, COUNT(*) AS rcpts
              FROM CUT
              JOIN R ON R.BizDate = CUT.BizDate
              GROUP BY CUT.BizDate
            ),
            DOW AS (
              SELECT
                -- Monday anchor 2000-01-03 is a Monday
                ((DATEDIFF(DAY, '20000103', BizDate) % 7) + 7) % 7 AS dow_idx,
                rcpts
              FROM Daily
            )
            SELECT dow_idx, AVG(CAST(rcpts AS float)) AS avg_rcpts
            FROM DOW
            GROUP BY dow_idx
            ORDER BY dow_idx;
        """, (days,))
        idx_to_name = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        rows = cur.fetchall()
        return [
            {"dow_index": int(r.dow_idx), "dow_label": idx_to_name[int(r.dow_idx) % 7], "avg_receipts": float(r.avg_rcpts or 0.0)}
            for r in rows
        ]


def get_top_windows(window_hours: int = 3, days: int = 30, top: int = 5, quiet: int = 3):
    """
    Top and quiet rolling <window_hours>-hour windows within operational hours (08:00..23:59 and 00:00..03:59),
    averaged over the last <days> DISTINCT business days with receipts.
    Business time uses the -7h shift (0 == 07:00 local).
    Returns: {"top":[{start_clock,end_clock,avg_receipts,avg_amount}], "quiet":[...]}
    """
    window_hours = max(1, min(int(window_hours), 8))
    days = max(1, min(int(days), 90))
    top = max(1, min(int(top), 10))
    quiet = max(1, min(int(quiet), 10))

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            -- Business calendar from receipts (shift -7h)
            WITH R AS (
              SELECT
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date)   AS BizDate,
                DATEPART(HOUR, DATEADD(HOUR,-7, r.RCPT_DATE)) AS BizHour
              FROM dbo.HISTORIC_RECEIPT r
            ),
            DistinctDays AS ( SELECT DISTINCT BizDate FROM R ),
            Ranked AS (
              SELECT BizDate, ROW_NUMBER() OVER (ORDER BY BizDate DESC) AS rn
              FROM DistinctDays
            ),
            LastN AS ( SELECT BizDate FROM Ranked WHERE rn <= ? ),

            -- 24 business hours (0..23), where 0 == 07:00 local
            H AS (
              SELECT 0 AS h UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL
              SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL
              SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL
              SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL
              SELECT 16 UNION ALL SELECT 17 UNION ALL SELECT 18 UNION ALL SELECT 19 UNION ALL
              SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23
            ),

            -- Allowed operational hours in *clock* time: 08..23 and 00..03
            -- Convert to *business* hours: biz_hour = (clock_hour - 7 + 24) % 24
            AH AS (
              SELECT ((8  -7 + 24) % 24) AS h UNION ALL  -- 01
              SELECT ((9  -7 + 24) % 24) UNION ALL       -- 02
              SELECT ((10 -7 + 24) % 24) UNION ALL       -- 03
              SELECT ((11 -7 + 24) % 24) UNION ALL       -- 04
              SELECT ((12 -7 + 24) % 24) UNION ALL       -- 05
              SELECT ((13 -7 + 24) % 24) UNION ALL       -- 06
              SELECT ((14 -7 + 24) % 24) UNION ALL       -- 07
              SELECT ((15 -7 + 24) % 24) UNION ALL       -- 08
              SELECT ((16 -7 + 24) % 24) UNION ALL       -- 09
              SELECT ((17 -7 + 24) % 24) UNION ALL       -- 10
              SELECT ((18 -7 + 24) % 24) UNION ALL       -- 11
              SELECT ((19 -7 + 24) % 24) UNION ALL       -- 12
              SELECT ((20 -7 + 24) % 24) UNION ALL       -- 13
              SELECT ((21 -7 + 24) % 24) UNION ALL       -- 14
              SELECT ((22 -7 + 24) % 24) UNION ALL       -- 15
              SELECT ((23 -7 + 24) % 24) UNION ALL       -- 16
              SELECT ((0  -7 + 24) % 24) UNION ALL       -- 17 (00:00)
              SELECT ((1  -7 + 24) % 24) UNION ALL       -- 18
              SELECT ((2  -7 + 24) % 24) UNION ALL       -- 19
              SELECT ((3  -7 + 24) % 24)                  -- 20 (03:00)
            ),

            -- Counts per business hour across those days
            HourlyCnt AS (
              SELECT R.BizHour, COUNT(*) AS rcpts
              FROM R
              JOIN LastN L ON L.BizDate = R.BizDate
              GROUP BY R.BizHour
            ),
            DayCount AS ( SELECT COUNT(*) AS days_total FROM LastN ),
            AvgCnt AS (
              SELECT H.h AS BizHour,
                     CAST(COALESCE(HourlyCnt.rcpts,0) AS float) / NULLIF(DC.days_total,0) AS avg_rcpts
              FROM H
              CROSS JOIN DayCount DC
              LEFT JOIN HourlyCnt ON HourlyCnt.BizHour = H.h
            ),

            -- Amounts by business hour (sum of contents per receipt hour)
            C AS (
              SELECT
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date)   AS BizDate,
                DATEPART(HOUR, DATEADD(HOUR,-7, r.RCPT_DATE)) AS BizHour,
                SUM(CAST(c.ITM_QUANTITY AS float) * CAST(c.ITM_PRICE AS float)) AS amt
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              GROUP BY CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date),
                       DATEPART(HOUR, DATEADD(HOUR,-7, r.RCPT_DATE))
            ),
            HourlyAmt AS (
              SELECT C.BizHour, SUM(C.amt) AS amount
              FROM C
              JOIN LastN L ON L.BizDate = C.BizDate
              GROUP BY C.BizHour
            ),
            AvgAmt AS (
              SELECT H.h AS BizHour,
                     CAST(COALESCE(HourlyAmt.amount,0) AS float) / NULLIF(DC.days_total,0) AS avg_amt
              FROM H
              CROSS JOIN DayCount DC
              LEFT JOIN HourlyAmt ON HourlyAmt.BizHour = H.h
            ),

            -- K = offsets 0..window_hours-1 (from a 0..23 generator)
            N0 AS (
              SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL
              SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL
              SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL
              SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL
              SELECT 16 UNION ALL SELECT 17 UNION ALL SELECT 18 UNION ALL SELECT 19 UNION ALL
              SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23
            ),
            K AS ( SELECT n FROM N0 WHERE n < ? ),

            -- Candidate start hours = all allowed start points
            Starts AS ( SELECT h AS s FROM AH ),

            -- Build windows: for each start s, take hours (s+n) % 24, require all in AH
            WinHours AS (
              SELECT s.s AS s, k.n AS n, ((s.s + k.n) % 24) AS h
              FROM Starts s
              JOIN K k ON 1=1
              JOIN AH ah ON ah.h = ((s.s + k.n) % 24)  -- ensures window stays inside operational hours
            ),
            WinAgg AS (
              SELECT s,
                     SUM(AC.avg_rcpts) AS win_avg_rcpts,
                     SUM(AA.avg_amt)   AS win_avg_amt,
                     COUNT(*)          AS hcount
              FROM WinHours wh
              JOIN AvgCnt AC ON AC.BizHour = wh.h
              JOIN AvgAmt AA ON AA.BizHour = wh.h
              GROUP BY s
              HAVING COUNT(*) = (SELECT COUNT(*) FROM K) -- keep only full windows
            ),

            TopWins AS (
              SELECT TOP (?)
                s AS start_bh,
                win_avg_rcpts,
                win_avg_amt
              FROM WinAgg
              ORDER BY win_avg_rcpts DESC, s ASC
            ),
            QuietWins AS (
              SELECT TOP (?)
                s AS start_bh,
                win_avg_rcpts,
                win_avg_amt
              FROM WinAgg
              ORDER BY win_avg_rcpts ASC, s ASC
            )

            SELECT 'top'   AS kind, start_bh, win_avg_rcpts, win_avg_amt FROM TopWins
            UNION ALL
            SELECT 'quiet' AS kind, start_bh, win_avg_rcpts, win_avg_amt FROM QuietWins
            ORDER BY kind, start_bh;
        """, (days, window_hours, top, quiet))

        rows = cur.fetchall()
        top_rows, quiet_rows = [], []
        for r in rows:
            start_bh = int(r.start_bh)                 # business hour
            start_clock = (start_bh + 7) % 24          # local hour label
            end_clock = (start_clock + window_hours - 1) % 24
            rec = {
                "start_clock": start_clock,
                "end_clock": end_clock,
                "avg_receipts": float(r.win_avg_rcpts or 0.0),
                "avg_amount": float(r.win_avg_amt or 0.0),
            }
            if r.kind == 'top':
                top_rows.append(rec)
            else:
                quiet_rows.append(rec)
        return {"top": top_rows, "quiet": quiet_rows}




# -------------------------------------------------------------------
# Dynamic Trends helpers (Item Trends report)
# -------------------------------------------------------------------

def get_subgroups_list() -> List[Dict]:
    """
    Returns a clean list of subgroups for dropdowns:
      [{ "id": <int>, "name": <str> }, ...]
    """
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            SELECT
              CAST(SubGrp_ID AS int)   AS id,
              CAST(SubGrp_Name AS nvarchar(200)) AS name
            FROM dbo.SUBGROUPS
            WHERE SubGrp_Name IS NOT NULL AND LTRIM(RTRIM(SubGrp_Name)) <> N''
            ORDER BY SubGrp_Name ASC;
        """)
        rows = cur.fetchall()
        return [{"id": int(r.id), "name": str(r.name)} for r in rows]


def get_item_trends(
    start_date,
    end_date,
    bucket: str,
    top_n: int,
    rank_by: str = "total",
    subgroup_label: Optional[str] = None,
    item_codes: Optional[List[str]] = None,
    output_format: str = "long",
) -> List[Dict]:
    """
    Fully dynamic Item Trends report.

    - Uses business-day shift (-7h) consistent with your intelligence logic.
    - Ranks top N items either by:
        rank_by="total"       => total qty over entire range
        rank_by="last_bucket" => qty in the last bucket within range
    - Optional subgroup filter uses your proven subgroup resolution logic.
    - Optional item_codes limits the universe further.

    Returns (long format):
      [{bucket_start, item_code, item, subgroup, qty}, ...]
    """

    # ---------- Safety clamps ----------
    top_n = max(1, min(int(top_n), 200))
    bucket = (bucket or "").strip().lower()
    rank_by = (rank_by or "total").strip().lower()
    output_format = (output_format or "long").strip().lower()

    if bucket not in ("daily", "weekly", "monthly"):
        raise ValueError("bucket must be daily|weekly|monthly")
    if rank_by not in ("total", "last_bucket"):
        raise ValueError("rank_by must be total|last_bucket")

    # NOTE: wide format can be added later. For now we return long always.
    # Keeping parameter now avoids breaking the API later.
    _ = output_format

    # ---------- Bucket expression (SAFE: whitelist only) ----------
    # We compute BizDate = CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date)
    # Then bucket_start is derived from BizDate.
    if bucket == "daily":
        bucket_expr = "BizDate"
    elif bucket == "weekly":
        # Monday-based week start, using the same stable Monday anchor you used in get_dow_profile()
        bucket_expr = "DATEADD(DAY, -(((DATEDIFF(DAY, '20000103', BizDate) % 7) + 7) % 7), BizDate)"
    else:  # monthly
        bucket_expr = "DATEFROMPARTS(YEAR(BizDate), MONTH(BizDate), 1)"

    # ---------- Optional IN (...) for item codes ----------
    item_code_filter_sql = ""
    item_code_params: List = []
    if item_codes:
        # pyodbc needs ? placeholders; build safely
        placeholders = ",".join(["?"] * len(item_codes))
        item_code_filter_sql = f" AND CAST(c.ITM_CODE AS nvarchar(128)) IN ({placeholders}) "
        item_code_params.extend(item_codes)

    # ---------- Optional subgroup filter ----------
    subgroup_filter_sql = ""
    subgroup_params: List = []
    if subgroup_label and str(subgroup_label).strip():
        subgroup_filter_sql = " AND UPPER(LTRIM(RTRIM(subgroup_label))) = UPPER(LTRIM(RTRIM(?))) "
        subgroup_params.append(subgroup_label.strip())

    # ---------- Date window ----------
    # Inclusive dates: [start_date 00:00 .. end_date+1 00:00)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt_exclusive = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)

    with _connect() as cn:
        cur = cn.cursor()

        # IMPORTANT: We do a two-phase query:
        #  1) Build a labeled line dataset with BizDate + subgroup resolution + item labels
        #  2) Pick TOP N items based on rank_by
        #  3) Return bucketed trends for those TOP N items
        #
        # This keeps performance sane and prevents “everything in DB” results.

        sql = f"""
            SET NOCOUNT ON;

            WITH Receipts AS (
              SELECT
                r.RCPT_ID,
                r.RCPT_DATE,
                CAST(DATEADD(HOUR,-7, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT r
              WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
            ),

            Lines AS (
              SELECT
                rc.BizDate,

                -- stable item code as text (safe for mixed numeric types)
                CAST(c.ITM_CODE AS nvarchar(128)) AS item_code,

                -- item display label (title if present else code)
                CAST(
                  CASE
                    WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> N'' THEN i.ITM_TITLE
                    ELSE CAST(c.ITM_CODE AS nvarchar(128))
                  END
                AS nvarchar(128)) AS item_label,

                -- subgroup resolution logic (same pattern you already use)
                COALESCE(
                  s_id.SubGrp_Name,
                  s_nm.SubGrp_Name,
                  NULLIF(x.SubGrpText, N''),
                  N'Unknown'
                ) AS subgroup_label,

                CAST(c.ITM_QUANTITY AS float) AS qty

              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN Receipts rc ON rc.RCPT_ID = c.RCPT_ID
              LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE

              CROSS APPLY (
                SELECT
                  CASE
                    WHEN i.ITM_SUBGROUP IS NULL THEN NULL
                    WHEN LTRIM(RTRIM(i.ITM_SUBGROUP)) = N'' THEN NULL
                    WHEN i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                    ELSE NULL
                  END AS SubGrpID,
                  LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpText
              ) AS x

              LEFT JOIN dbo.SUBGROUPS AS s_id
                ON s_id.SubGrp_ID = x.SubGrpID
              LEFT JOIN dbo.SUBGROUPS AS s_nm
                ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = x.SubGrpText

              WHERE 1=1
              {item_code_filter_sql}
            ),

            Filtered AS (
              SELECT *
              FROM Lines
              WHERE 1=1
              {subgroup_filter_sql}
            ),

            LastBucket AS (
              SELECT MAX({bucket_expr}) AS last_bucket_start
              FROM Filtered
            ),

            Ranked AS (
              SELECT
                f.item_code,
                f.item_label,
                f.subgroup_label,
                SUM(
                  CASE
                    WHEN ? = 'last_bucket'
                      THEN CASE WHEN {bucket_expr} = lb.last_bucket_start THEN f.qty ELSE 0 END
                    ELSE f.qty
                  END
                ) AS rank_qty
              FROM Filtered f
              CROSS JOIN LastBucket lb
              GROUP BY f.item_code, f.item_label, f.subgroup_label
            ),


            TopItems AS (
              SELECT TOP (?)
                item_code, item_label, subgroup_label
              FROM Ranked
              WHERE rank_qty > 0
              ORDER BY rank_qty DESC, item_label ASC
            )

            SELECT
              CONVERT(varchar(10), {bucket_expr}, 23) AS bucket_start,
              f.item_code,
              f.item_label AS item,
              f.subgroup_label AS subgroup,
              SUM(f.qty) AS qty
            FROM Filtered f
            JOIN TopItems t ON t.item_code = f.item_code
            GROUP BY
              {bucket_expr},
              f.item_code,
              f.item_label,
              f.subgroup_label
            ORDER BY
              {bucket_expr} ASC,
              qty DESC,
              item ASC;
        """

        # Params order MUST match ? placeholders above
        params: List = []
        params.extend([start_dt, end_dt_exclusive])   # Receipts date range
        params.extend(item_code_params)               # optional item_codes IN (...)
        params.extend(subgroup_params)                # optional subgroup label filter
        params.append(rank_by)                        # ? = 'last_bucket' check
        params.append(top_n)                          # TOP (?)

        cur.execute(sql, params)
        rows = cur.fetchall()

        return [
            {
                "bucket_start": r.bucket_start,
                "item_code": r.item_code,
                "item": r.item,
                "subgroup": r.subgroup,
                "qty": float(r.qty or 0.0),
            }
            for r in rows
        ]
        
        
def search_items_explorer(
  query: str = "",
  subgroup_name: str = "",
  days: int = 30,
  trend: str = "",
  limit: int = 500
) -> List[Dict]:
  """
  Items Explorer data source.

  Numbers explained:
  - avg_per_day: total quantity sold in the window / number of days in the window.
    This is a baseline demand estimate, not a forecast.
  - last_sold: most recent receipt datetime for this item within the window.
    Builds trust that the item is active and shows recency.
  - trend: compares last business day qty vs previous business day qty (within the window).
    up/down/flat is a quick signal; details belong to Item 360.
  """
  query = (query or "").strip()
  subgroup_name = (subgroup_name or "").strip()

  days = max(1, min(int(days), 365))
  limit = max(50, min(int(limit), 2000))
  trend = (trend or "").strip().lower()
  if trend not in ("", "up", "down", "flat"):
      trend = ""

  with _connect() as cn:
      cur = cn.cursor()

      # IMPORTANT: define the analysis window based on business date (07:00 boundary via DATEADD(HOUR,-7,...))
      # We anchor on the latest BizDate present in the receipts table, then go back N days.
      sql = f"""
SET NOCOUNT ON;

WITH R AS (
  SELECT
    r.RCPT_ID,
    r.RCPT_DATE,
    CAST(DATEADD(HOUR, -7, r.RCPT_DATE) AS date) AS BizDate
  FROM dbo.HISTORIC_RECEIPT r
),
MaxBiz AS (
  SELECT MAX(BizDate) AS MaxBizDate FROM R
),
Windowed AS (
  SELECT
    r.RCPT_ID,
    r.RCPT_DATE,
    r.BizDate
  FROM R r
  CROSS JOIN MaxBiz m
  WHERE r.BizDate >= DATEADD(DAY, -? + 1, m.MaxBizDate)
    AND r.BizDate <= m.MaxBizDate
),
Top2Days AS (
  SELECT TOP (2) BizDate
  FROM (SELECT DISTINCT BizDate FROM Windowed) d
  ORDER BY BizDate DESC
),
DayMarks AS (
  SELECT
    MAX(BizDate) AS LastBiz,
    MIN(BizDate) AS PrevBiz
  FROM Top2Days
),
Base AS (
  SELECT
CAST(i.ITM_CODE AS nvarchar(50)) AS item_code,
    COALESCE(
      NULLIF(LTRIM(RTRIM(CAST(i.ITM_TITLE AS nvarchar(255)))), ''),
      CAST(i.ITM_CODE AS nvarchar(50))
    ) AS item_title,

    -- subgroup_name:
    -- We intentionally take it from ITEMS.ITM_SUBGROUP to avoid any int/text conversion issues.
    -- This supports values like numeric IDs, 'PAYMENT', or Arabic labels.
    COALESCE(
      NULLIF(LTRIM(RTRIM(CAST(i.ITM_SUBGROUP AS nvarchar(100)))), ''),
      ''
    ) AS subgroup_name,

    w.RCPT_DATE,
    w.BizDate,
    c.ITM_QUANTITY AS qty
  FROM Windowed w
  JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = w.RCPT_ID
  JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE
),
Agg AS (
  SELECT
    b.item_code,
    b.item_title,
    b.subgroup_name,
    MAX(b.RCPT_DATE) AS last_sold_dt,
    SUM(b.qty)       AS total_qty,
    SUM(CASE WHEN b.BizDate = dm.LastBiz THEN b.qty ELSE 0 END) AS qty_last_day,
    SUM(CASE WHEN b.BizDate = dm.PrevBiz THEN b.qty ELSE 0 END) AS qty_prev_day
  FROM Base b
  CROSS JOIN DayMarks dm
  WHERE ( ? = '' OR b.subgroup_name = ? )
    AND (
      ? = '' OR
      b.item_code LIKE '%' + ? + '%' OR
      b.item_title LIKE '%' + ? + '%'
    )
  GROUP BY b.item_code, b.item_title, b.subgroup_name
)
SELECT TOP (?)
  a.item_code,
  a.item_title,
  a.subgroup_name,
  CONVERT(varchar(19), a.last_sold_dt, 120) AS last_sold,
  CAST(a.total_qty AS float) / NULLIF(?, 0) AS avg_per_day,
  a.qty_last_day,
  a.qty_prev_day
FROM Agg a
ORDER BY avg_per_day DESC, a.last_sold_dt DESC;
"""


      # We divide by "days" in SQL (simple baseline average)
      # IMPORTANT: params order MUST match the ? placeholders in the SQL.
      # Placeholder order in SQL:
      # 1) days window (int)
      # 2) subgroup filter check (? = '')
      # 3) subgroup filter value (b.subgroup_name = ?)
      # 4) query empty check (? = '')
      # 5) item_code LIKE
      # 6) item_title LIKE
      # 7) TOP limit
      # 8) avg_per_day divisor days
      params = [
          int(days),
          subgroup_name, subgroup_name,
          query, query, query,
          int(limit),
          int(days),
      ]
      
      print("DEBUG search_items_explorer params:", params)

      cur.execute(sql, params)
      rows = cur.fetchall()

      result = []
      for r in rows:
          last_qty = float(r.qty_last_day or 0.0)
          prev_qty = float(r.qty_prev_day or 0.0)

          # IMPORTANT: Trend logic kept simple and explainable:
          # - prev=0 and last>0 => "up" (new spike)
          # - small change => "flat"
          # - otherwise compare
          if prev_qty == 0 and last_qty == 0:
              t = "flat"
          elif prev_qty == 0 and last_qty > 0:
              t = "up"
          else:
              pct = ((last_qty - prev_qty) / prev_qty) * 100.0 if prev_qty else 0.0
              if abs(pct) < 5.0:
                  t = "flat"
              elif pct > 0:
                  t = "up"
              else:
                  t = "down"

          # Apply optional trend filter server-side
          if trend and t != trend:
              continue

          result.append({
              "item_code": r.item_code,
              "item": r.item_title,
              "subgroup": r.subgroup_name,
              "avg_per_day": round(float(r.avg_per_day or 0.0), 2),
              "last_sold": r.last_sold or "",
              "trend": t
          })

      return result
       
        

