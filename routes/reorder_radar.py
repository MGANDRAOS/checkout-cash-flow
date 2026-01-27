# routes/reorder_radar.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from flask import Blueprint, jsonify, render_template, request, Response

# IMPORTANT:
# - Keep queries read-only
# - Keep all BizDate rules consistent (RCPT_DATE - 7h)
# - Use parameterized queries (no string concat with user input)


reorder_radar_bp = Blueprint("reorder_radar", __name__)


@dataclass
class DataTablesRequest:
    draw: int
    start: int
    length: int
    order_col_index: int
    order_dir: str
    q: str
    subgroup: str
    lookback: int
    only_action: str


def _parse_datatables_request(payload: Dict[str, Any]) -> DataTablesRequest:
    # IMPORTANT: defensive parsing to avoid crashes from malformed payloads
    order = payload.get("order") or []
    order_first = order[0] if order else {"column": 2, "dir": "desc"}  # default score desc
    order_col_index = int(order_first.get("column", 2))
    order_dir = str(order_first.get("dir", "desc")).lower()
    if order_dir not in ("asc", "desc"):
        order_dir = "desc"

    q = str(payload.get("q") or "").strip()
    subgroup = str(payload.get("subgroup") or "").strip()
    lookback = int(payload.get("lookback") or 30)
    if lookback not in (7, 14, 30, 90):
        lookback = 30

    only_action = str(payload.get("onlyAction") or "1").strip()
    if only_action not in ("0", "1"):
        only_action = "1"

    return DataTablesRequest(
        draw=int(payload.get("draw") or 1),
        start=int(payload.get("start") or 0),
        length=int(payload.get("length") or 25),
        order_col_index=order_col_index,
        order_dir=order_dir,
        q=q,
        subgroup=subgroup,
        lookback=lookback,
        only_action=only_action,
    )


def _map_order_column(index: int) -> str:
    # IMPORTANT: Whitelist ordering columns to prevent SQL injection via ORDER BY
    # Match indexes to the DataTables columns order in reorder_radar.js
    allowed = {
        0: "itm_code",
        1: "itm_name",
        2: "score",
        3: "qty_7d",
        4: "qty_30d",
        5: "avg_daily_30d",
        6: "trend_ratio",
        7: "days_since_last_sale",
        8: "last_sold_bizdate",
        9: "flags",
    }
    return allowed.get(index, "score")


@reorder_radar_bp.get("/reorder-radar")
def reorder_radar_page():
    return render_template("reorder_radar.html")


@reorder_radar_bp.post("/api/reorder-radar")
def reorder_radar_data():
    payload = request.get_json(force=True, silent=True) or {}
    dt = _parse_datatables_request(payload)

    # NOTE:
    # Replace this import with your actual MSSQL helper.
    # You mentioned "helpers_intelligence" safe read-only mode.
    from helpers_intelligence import mssql_readonly_query  # type: ignore

    # Build query and params
    order_by = _map_order_column(dt.order_col_index)
    order_dir = dt.order_dir

    sql, params = build_reorder_radar_sql(
        q=dt.q,
        subgroup=dt.subgroup,
        lookback_days=dt.lookback,
        only_action=(dt.only_action == "1"),
        order_by=order_by,
        order_dir=order_dir,
        offset=dt.start,
        page_size=dt.length,
    )

    rows: List[Dict[str, Any]] = mssql_readonly_query(sql, params)

    # Separate count query for DataTables (total filtered)
    count_sql, count_params = build_reorder_radar_count_sql(
        q=dt.q,
        subgroup=dt.subgroup,
        lookback_days=dt.lookback,
        only_action=(dt.only_action == "1"),
    )
    count_rows = mssql_readonly_query(count_sql, count_params)
    filtered_count = int(count_rows[0]["cnt"]) if count_rows else 0

    # Total count (no filters) - optional; DataTables expects it
    total_sql, total_params = build_reorder_radar_count_sql(
        q="",
        subgroup="",
        lookback_days=dt.lookback,
        only_action=False,  # total should be full population
    )
    total_rows = mssql_readonly_query(total_sql, total_params)
    total_count = int(total_rows[0]["cnt"]) if total_rows else filtered_count

    return jsonify(
        {
            "draw": dt.draw,
            "recordsTotal": total_count,
            "recordsFiltered": filtered_count,
            "data": rows,
        }
    )


@reorder_radar_bp.get("/api/reorder-radar/export")
def reorder_radar_export_csv():
    q = (request.args.get("q") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()
    lookback = int(request.args.get("lookback") or 30)
    if lookback not in (7, 14, 30, 90):
        lookback = 30
    only_action = (request.args.get("onlyAction") or "1").strip() == "1"

    from helpers_intelligence import mssql_readonly_query  # type: ignore

    # Export a larger batch (still read-only)
    sql, params = build_reorder_radar_sql(
        q=q,
        subgroup=subgroup,
        lookback_days=lookback,
        only_action=only_action,
        order_by="score",
        order_dir="desc",
        offset=0,
        page_size=5000,
    )
    rows: List[Dict[str, Any]] = mssql_readonly_query(sql, params)

    # Build CSV
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "itm_code",
            "itm_name",
            "score",
            "qty_7d",
            "qty_30d",
            "avg_daily_30d",
            "trend_ratio",
            "days_since_last_sale",
            "last_sold_bizdate",
            "flags",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.get("itm_code"),
                r.get("itm_name"),
                r.get("score"),
                r.get("qty_7d"),
                r.get("qty_30d"),
                r.get("avg_daily_30d"),
                r.get("trend_ratio"),
                r.get("days_since_last_sale"),
                r.get("last_sold_bizdate"),
                r.get("flags"),
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")  # Excel-friendly BOM

    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reorder_radar.csv"},
    )


def build_reorder_radar_sql(
    *,
    q: str,
    subgroup: str,
    lookback_days: int,
    only_action: bool,
    order_by: str,
    order_dir: str,
    offset: int,
    page_size: int,
) -> Tuple[str, Sequence[Any]]:
    """
    IMPORTANT:
    - pyodbc uses positional parameter markers: '?'
    - keep ORDER BY injected only from a whitelist (_map_order_column)
    - BizDate = RCPT_DATE - 7h
    """

    qty_column = "c.ITM_QUANTITY"  # POS line quantity column


    # IMPORTANT: order_by comes ONLY from _map_order_column (whitelisted)
    safe_order_by = order_by
    safe_order_dir = "DESC" if order_dir.lower() == "desc" else "ASC"

    sql = f"""
WITH receipts AS (
    SELECT
        r.RCPT_ID,
        CAST(DATEADD(HOUR, -7, r.RCPT_DATE) AS date) AS BizDate
    FROM HISTORIC_RECEIPT r
    WHERE CAST(DATEADD(HOUR, -7, r.RCPT_DATE) AS date) >= DATEADD(DAY, -90, CAST(GETDATE() AS date))
),
lines AS (
    SELECT
        rc.BizDate,
        c.ITM_CODE,
        SUM({qty_column}) AS Qty
    FROM receipts rc
    INNER JOIN HISTORIC_RECEIPT_CONTENTS c
        ON c.RCPT_ID = rc.RCPT_ID
    GROUP BY rc.BizDate, c.ITM_CODE
),
agg AS (
    SELECT
        l.ITM_CODE,

        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -7,  CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_7d,
        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -30, CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_30d,
        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -90, CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_90d,

        COUNT(DISTINCT CASE WHEN l.BizDate >= DATEADD(DAY, -30, CAST(GETDATE() AS date)) AND l.Qty > 0 THEN l.BizDate END) AS days_sold_30d,
        COUNT(DISTINCT CASE WHEN l.BizDate >= DATEADD(DAY, -90, CAST(GETDATE() AS date)) AND l.Qty > 0 THEN l.BizDate END) AS days_sold_90d,

        MAX(CASE WHEN l.Qty > 0 THEN l.BizDate END) AS last_sold_bizdate
    FROM lines l
    GROUP BY l.ITM_CODE
),
scored AS (
    SELECT
        a.ITM_CODE AS itm_code,
        i.ITM_TITLE AS itm_name,
        sg.SubGrp_Name AS subgroup_name,

        ISNULL(a.qty_7d, 0) AS qty_7d,
        ISNULL(a.qty_30d, 0) AS qty_30d,
        CAST(ISNULL(a.qty_30d, 0) / 30.0 AS decimal(10, 3)) AS avg_daily_30d,

        CAST(
            (ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)
            AS decimal(10, 3)
        ) AS trend_ratio,

        a.last_sold_bizdate,
        CASE
            WHEN a.last_sold_bizdate IS NULL THEN 9999
            ELSE DATEDIFF(DAY, a.last_sold_bizdate, CAST(GETDATE() AS date))
        END AS days_since_last_sale,

        CAST(
            (
                (ISNULL(a.qty_30d, 0) / 30.0) * 10.0
                + (
                    CASE
                        WHEN ((ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)) >= 1.4 THEN 6
                        WHEN ((ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)) >= 1.1 THEN 3
                        ELSE 0
                    END
                )
                + (
                    CASE
                        WHEN (a.last_sold_bizdate IS NOT NULL)
                             AND (DATEDIFF(DAY, a.last_sold_bizdate, CAST(GETDATE() AS date)) >= 5)
                             AND (ISNULL(a.days_sold_90d, 0) >= 10)
                        THEN 8
                        ELSE 0
                    END
                )
            ) AS decimal(10, 2)
        ) AS score,

        LTRIM(RTRIM(
            CONCAT(
                CASE WHEN ((ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)) >= 1.4 THEN 'FAST ' ELSE '' END,
                CASE WHEN (a.last_sold_bizdate IS NOT NULL)
                          AND (DATEDIFF(DAY, a.last_sold_bizdate, CAST(GETDATE() AS date)) >= 5)
                          AND (ISNULL(a.days_sold_90d, 0) >= 10)
                     THEN 'STOCKOUT? ' ELSE '' END,
                CASE WHEN ISNULL(a.qty_30d, 0) <= 2 AND ISNULL(a.days_sold_90d, 0) <= 3 THEN 'SLOW ' ELSE '' END
            )
        )) AS flags
        FROM agg a
        INNER JOIN ITEMS i
            ON i.ITM_CODE = a.ITM_CODE
        LEFT JOIN SUBGROUPS sg
            ON sg.SubGrp_ID = i.ITM_SUBGROUP
        WHERE 1=1
        AND (
                ? = ''
                OR CAST(a.ITM_CODE AS varchar(50)) LIKE '%' + ? + '%'
                OR i.ITM_TITLE LIKE '%' + ? + '%'
            )
        AND ( ? = '' OR CAST(i.ITM_SUBGROUP AS varchar(50)) = ? )

),
filtered AS (
    SELECT *
    FROM scored
    WHERE 1=1
      AND (
        ? = 0
        OR score >= 5
        OR flags LIKE '%STOCKOUT?%'
      )
)
SELECT
    itm_code,
    itm_name,
    score,
    qty_7d,
    qty_30d,
    avg_daily_30d,
    trend_ratio,
    days_since_last_sale,
    CONVERT(varchar(10), last_sold_bizdate, 120) AS last_sold_bizdate,
    subgroup_name
    flags
FROM filtered
ORDER BY {safe_order_by} {safe_order_dir}, score DESC
OFFSET ? ROWS
FETCH NEXT ? ROWS ONLY;
""".strip()

    # IMPORTANT: positional params must match '?' order exactly
    params: List[Any] = [
        q, q, q,           # three uses in LIKE section
        subgroup, subgroup, # subgroup check + value
        1 if only_action else 0,
        int(offset),
        int(page_size),
    ]

    return sql, params


def build_reorder_radar_count_sql(
    *,
    q: str,
    subgroup: str,
    lookback_days: int,
    only_action: bool,
) -> Tuple[str, Sequence[Any]]:
    """
    Count query using positional params for pyodbc.
    Keep filters consistent with main query.
    """
    sql = """
WITH receipts AS (
    SELECT
        r.RCPT_ID,
        CAST(DATEADD(HOUR, -7, r.RCPT_DATE) AS date) AS BizDate
    FROM HISTORIC_RECEIPT r
    WHERE CAST(DATEADD(HOUR, -7, r.RCPT_DATE) AS date) >= DATEADD(DAY, -90, CAST(GETDATE() AS date))
),
lines AS (
    SELECT
        rc.BizDate,
        c.ITM_CODE,
        SUM(c.ITM_QUANTITY) AS Qty
    FROM receipts rc
    INNER JOIN HISTORIC_RECEIPT_CONTENTS c
        ON c.RCPT_ID = rc.RCPT_ID
    GROUP BY rc.BizDate, c.ITM_CODE
),
agg AS (
    SELECT
        l.ITM_CODE,
        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -7,  CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_7d,
        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -30, CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_30d,
        SUM(CASE WHEN l.BizDate >= DATEADD(DAY, -90, CAST(GETDATE() AS date)) THEN l.Qty ELSE 0 END) AS qty_90d,
        COUNT(DISTINCT CASE WHEN l.BizDate >= DATEADD(DAY, -90, CAST(GETDATE() AS date)) AND l.Qty > 0 THEN l.BizDate END) AS days_sold_90d,
        MAX(CASE WHEN l.Qty > 0 THEN l.BizDate END) AS last_sold_bizdate
    FROM lines l
    GROUP BY l.ITM_CODE
),
scored AS (
    SELECT
        a.ITM_CODE AS itm_code,
        CAST(
            (
                (ISNULL(a.qty_30d, 0) / 30.0) * 10.0
                + (
                    CASE
                        WHEN ((ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)) >= 1.4 THEN 6
                        WHEN ((ISNULL(a.qty_7d, 0) / 7.0 + 0.001) / (ISNULL(a.qty_90d, 0) / 90.0 + 0.001)) >= 1.1 THEN 3
                        ELSE 0
                    END
                )
                + (
                    CASE
                        WHEN (a.last_sold_bizdate IS NOT NULL)
                             AND (DATEDIFF(DAY, a.last_sold_bizdate, CAST(GETDATE() AS date)) >= 5)
                             AND (ISNULL(a.days_sold_90d, 0) >= 10)
                        THEN 8
                        ELSE 0
                    END
                )
            ) AS decimal(10, 2)
        ) AS score,
        LTRIM(RTRIM(
            CONCAT(
                CASE WHEN (a.last_sold_bizdate IS NOT NULL)
                          AND (DATEDIFF(DAY, a.last_sold_bizdate, CAST(GETDATE() AS date)) >= 5)
                          AND (ISNULL(a.days_sold_90d, 0) >= 10)
                     THEN 'STOCKOUT? ' ELSE '' END
            )
        )) AS flags
        FROM agg a
        INNER JOIN ITEMS i
            ON i.ITM_CODE = a.ITM_CODE
        WHERE 1=1
        AND (
                ? = ''
                OR CAST(a.ITM_CODE AS varchar(50)) LIKE '%' + ? + '%'
                OR i.ITM_TITLE LIKE '%' + ? + '%'
            )
        AND ( ? = '' OR CAST(i.ITM_SUBGROUP AS varchar(50)) = ? )
),
filtered AS (
    SELECT *
    FROM scored
    WHERE 1=1
      AND (
        ? = 0
        OR score >= 5
        OR flags LIKE '%STOCKOUT?%'
      )
)
SELECT COUNT(1) AS cnt FROM filtered;
""".strip()

    params: List[Any] = [
        q, q, q,
        subgroup, subgroup,
        1 if only_action else 0,
    ]

    return sql, params