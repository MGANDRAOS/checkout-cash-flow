# helpers_items.py
from helpers_intelligence import _connect

def list_items(page=1, page_size=25, q="", sort="", subgroup_id=None, subgroup="", inactive_days=None, never_sold=0):
    page = max(1, int(page))
    page_size = min(200, max(5, int(page_size)))
    start_rn = (page - 1) * page_size + 1
    end_rn = page * page_size

    q = (q or "").strip()
    subgroup = (subgroup or "").strip()
    sort = (sort or "").lower().replace(" ", "")

    allowed = {"code","title","type","subgroup","last_purchased"}
    sort_field, sort_dir = "", ""
    if "," in sort:
        f, d = sort.split(",", 1)
        if f in allowed and d in ("asc","desc"):
            sort_field, sort_dir = f, d

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
        """
            SET NOCOUNT ON;

            DECLARE @q     nvarchar(200) = ?;
            DECLARE @pat   nvarchar(210) = CASE WHEN @q = N'' THEN NULL ELSE N'%' + @q + N'%' END;
            DECLARE @sort  nvarchar(40)  = ?;
            DECLARE @dir   nvarchar(4)   = ?;
            DECLARE @sg    nvarchar(200) = ?;
            DECLARE @sgid  int           = ?;
            DECLARE @inact int           = ?;
            DECLARE @never bit           = ?;

            /* Base items */
            WITH I AS (
              SELECT
                i.ITM_CODE, i.ITM_TITLE, i.ITM_DESCRIPTION, i.ITM_TYPE,
                LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpRaw,
                CASE
                  WHEN i.ITM_SUBGROUP IS NOT NULL AND i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                  ELSE NULL
                END AS SubGrpID
              FROM dbo.ITEMS i
            ),
            J AS (
              SELECT
                I.ITM_CODE, I.ITM_TITLE, I.ITM_DESCRIPTION, I.ITM_TYPE, I.SubGrpRaw,
                COALESCE(s_id.SubGrp_ID, s_nm.SubGrp_ID) AS ResolvedSubGrpID,
                LTRIM(RTRIM(COALESCE(s_id.SubGrp_Name, s_nm.SubGrp_Name, NULLIF(I.SubGrpRaw,N''), N'Unknown')))
                  COLLATE DATABASE_DEFAULT AS ResolvedSubgroup
              FROM I
              LEFT JOIN dbo.SUBGROUPS s_id ON s_id.SubGrp_ID = I.SubGrpID
              LEFT JOIN dbo.SUBGROUPS s_nm ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = I.SubGrpRaw
            ),
            LP AS (
              SELECT c.ITM_CODE, MAX(r.RCPT_DATE) AS LastPurchased
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              GROUP BY c.ITM_CODE
            ),
            /* Bring in a price from ITEM_BARCODE (lowest barcode per item) */
            PB AS (
              SELECT b.ITM_CODE, MIN(b.ITM_BARCODE) AS PrimaryBarcode,
                    MAX(b.ITM_PRICE) AS Price
              FROM dbo.ITEM_BARCODE b
              GROUP BY b.ITM_CODE
            ),
            F AS (
              SELECT
                J.ITM_CODE, J.ITM_TITLE, J.ITM_DESCRIPTION, J.ITM_TYPE,
                J.ResolvedSubGrpID, J.ResolvedSubgroup, LP.LastPurchased,
                PB.Price
              FROM J
              LEFT JOIN LP ON LP.ITM_CODE = J.ITM_CODE
              LEFT JOIN PB ON PB.ITM_CODE = J.ITM_CODE
              WHERE
                (@pat IS NULL
                  OR (J.ITM_TITLE IS NOT NULL AND J.ITM_TITLE LIKE @pat)
                  OR (CAST(J.ITM_CODE AS nvarchar(128)) LIKE @pat)
                  OR (J.ResolvedSubgroup LIKE @pat))
                AND (@sgid IS NULL OR J.ResolvedSubGrpID = @sgid)
                AND (
                  CASE
                    WHEN @never = 1 THEN CASE WHEN LP.LastPurchased IS NULL THEN 1 ELSE 0 END
                    WHEN @inact IS NOT NULL THEN CASE WHEN LP.LastPurchased IS NULL OR LP.LastPurchased < DATEADD(DAY, -@inact, GETDATE()) THEN 1 ELSE 0 END
                    ELSE 1
                  END = 1
                )
            ),
            B AS (
              SELECT
                F.ITM_CODE, F.ITM_TITLE, F.ITM_DESCRIPTION, F.ITM_TYPE,
                F.ResolvedSubgroup AS Subgroup, F.LastPurchased,
                F.Price,
                ROW_NUMBER() OVER (ORDER BY
                  CASE WHEN @sort='last_purchased' AND @dir='asc'  THEN F.LastPurchased END ASC,
                  CASE WHEN @sort='last_purchased' AND @dir='desc' THEN F.LastPurchased END DESC,
                  CASE WHEN @sort='code' AND @dir='asc'  THEN F.ITM_CODE END ASC,
                  CASE WHEN @sort='code' AND @dir='desc' THEN F.ITM_CODE END DESC,
                  CASE WHEN @sort='title' AND @dir='asc' THEN F.ITM_TITLE END ASC,
                  CASE WHEN @sort='title' AND @dir='desc' THEN F.ITM_TITLE END DESC,
                  F.ITM_TITLE ASC
                ) AS rn,
                COUNT(1) OVER() AS total_count
              FROM F
            )
            SELECT ITM_CODE, ITM_TITLE, Subgroup, LastPurchased, Price, rn, total_count
            FROM B
            WHERE rn BETWEEN ? AND ?
            ORDER BY rn;
        """, 
        (q, sort_field, sort_dir, subgroup, subgroup_id, inactive_days, int(never_sold or 0), start_rn, end_rn))

        rows = cur.fetchall()
        items, total = [], 0
        for r in rows:
            total = int(r.total_count or 0)
            lp = None
            if getattr(r, 'LastPurchased', None) is not None:
                try:
                    lp = r.LastPurchased.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    lp = str(r.LastPurchased)
            items.append({
                "code": r.ITM_CODE,
                "title": r.ITM_TITLE or "",
                "subgroup": r.Subgroup or "Unknown",
                "price": float(getattr(r, "Price", 0) or 0.0),
                "last_purchased": lp
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}
              
      
def list_subgroups():
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            SELECT s.SubGrp_ID AS id,
                   LTRIM(RTRIM(s.SubGrp_Name)) AS Subgroup,
                   COUNT(i.ITM_CODE) AS items_count
            FROM dbo.SUBGROUPS s
            LEFT JOIN dbo.ITEMS i
              ON (
                   -- match by numeric id when possible
                   (i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' AND CONVERT(int, i.ITM_SUBGROUP) = s.SubGrp_ID)
                   OR
                   -- or by trimmed name
                   (LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)))
                 )
            GROUP BY s.SubGrp_ID, LTRIM(RTRIM(s.SubGrp_Name))
            ORDER BY items_count DESC, Subgroup;
        """)
        return [{"id": int(r.id), "subgroup": r.Subgroup, "count": int(r.items_count or 0)} for r in cur.fetchall()]


def get_item_details(code: str, days: int = 30, biz_start_hour: int = 7, biz_end_hour: int = 5):
    """
    Return a compact profile for one item:
      - item header (title, subgroup, last_purchased)
      - 30 business-day summary (receipts, units, amount, price_min/avg/max)
      - daily series (qty, amount) grouped by business day (07:00 -> next-day 05:00)
      - last 5 receipts with this item (qty, unit price, line total)
    All read-only SELECTs. Uses parameter binding; no dynamic SQL.
    """
    code = str(code)

    with _connect() as cn:
        cur = cn.cursor()

        # 0) Resolve item header (title + subgroup) + last purchased
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @code nvarchar(128) = ?;

            WITH I AS (
              SELECT
                i.ITM_CODE,
                i.ITM_TITLE,
                i.ITM_DESCRIPTION,
                i.ITM_TYPE,
                LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpRaw,
                CASE
                  WHEN i.ITM_SUBGROUP IS NOT NULL AND i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%'
                    THEN CONVERT(int, i.ITM_SUBGROUP)
                  ELSE NULL
                END AS SubGrpID
              FROM dbo.ITEMS i
              WHERE i.ITM_CODE = @code
            ),
            J AS (
              SELECT
                I.ITM_CODE, I.ITM_TITLE, I.ITM_DESCRIPTION, I.ITM_TYPE,
                COALESCE(s_id.SubGrp_ID, s_nm.SubGrp_ID) AS ResolvedSubGrpID,
                LTRIM(RTRIM(COALESCE(s_id.SubGrp_Name, s_nm.SubGrp_Name, NULLIF(I.SubGrpRaw,N''), N'Unknown')))
                  COLLATE DATABASE_DEFAULT AS ResolvedSubgroup
              FROM I
              LEFT JOIN dbo.SUBGROUPS s_id ON s_id.SubGrp_ID = I.SubGrpID
              LEFT JOIN dbo.SUBGROUPS s_nm ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = I.SubGrpRaw
            )
            SELECT TOP 1
              J.ITM_CODE,
              J.ITM_TITLE,
              J.ITM_TYPE,
              J.ResolvedSubgroup
            FROM J;
        """, (code,))
        row = cur.fetchone()
        item_header = {
            "code": code,
            "title": (row.ITM_TITLE if row else None) or "",
            "type": (row.ITM_TYPE if row else None) or "",
            "subgroup": (row.ResolvedSubgroup if row else None) or "Unknown"
        }

        # 1) Summary over last N business days (time-shifted window)
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @code nvarchar(128) = ?;
            DECLARE @days int = ?;
            DECLARE @bizStart int = ?;

            DECLARE @now datetime = GETDATE();
            -- Shift window start by business start hour for grouping consistency
            DECLARE @windowStart datetime = DATEADD(DAY, -@days, DATEADD(HOUR, -@bizStart, @now));

            -- Last purchased across all time
            ;WITH LP AS (
              SELECT MAX(r.RCPT_DATE) AS LastPurchased
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              WHERE c.ITM_CODE = @code
            ),
            W AS (
              SELECT
                r.RCPT_ID,
                r.RCPT_DATE,
                c.ITM_QUANTITY,
                c.ITM_PRICE,
                CAST(DATEADD(HOUR, -@bizStart, r.RCPT_DATE) AS date) AS BizDate
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              WHERE c.ITM_CODE = @code
                AND DATEADD(HOUR, -@bizStart, r.RCPT_DATE) >= @windowStart
            )
            SELECT
              (SELECT LastPurchased FROM LP)              AS LastPurchased,
              COUNT(DISTINCT W.RCPT_ID)                  AS Receipts,
              SUM(CASE WHEN W.ITM_QUANTITY > 0 THEN W.ITM_QUANTITY ELSE 0 END)                              AS Units,
              SUM(CASE WHEN W.ITM_QUANTITY > 0 THEN W.ITM_QUANTITY * W.ITM_PRICE ELSE 0 END)                AS Amount,
              MIN(CASE WHEN W.ITM_QUANTITY > 0 AND W.ITM_PRICE > 0 THEN W.ITM_PRICE END)                    AS PriceMin,
              AVG(CASE WHEN W.ITM_QUANTITY > 0 AND W.ITM_PRICE > 0 THEN CAST(W.ITM_PRICE AS float) END)     AS PriceAvg,
              MAX(CASE WHEN W.ITM_QUANTITY > 0 AND W.ITM_PRICE > 0 THEN W.ITM_PRICE END)                    AS PriceMax
            FROM W;
        """, (code, int(days), int(biz_start_hour)))
        s = cur.fetchone()
        def _fmt_dt(dt):
            try:
                return dt.strftime('%Y-%m-%d %H:%M') if dt else None
            except Exception:
                return str(dt) if dt is not None else None

        summary = {
            "receipts": int(s.Receipts or 0) if s else 0,
            "units": int(s.Units or 0) if s else 0,
            "amount": float(s.Amount or 0) if s else 0.0,
            "price_min": float(s.PriceMin or 0) if s and s.PriceMin is not None else None,
            "price_avg": float(s.PriceAvg or 0) if s and s.PriceAvg is not None else None,
            "price_max": float(s.PriceMax or 0) if s and s.PriceMax is not None else None,
        }
        last_purchased = _fmt_dt(s.LastPurchased) if s else None
        item_header["last_purchased"] = last_purchased

        # 2) Daily series (qty, amount) per business day
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @code nvarchar(128) = ?;
            DECLARE @days int = ?;
            DECLARE @bizStart int = ?;

            DECLARE @now datetime = GETDATE();
            DECLARE @windowStart datetime = DATEADD(DAY, -@days, DATEADD(HOUR, -@bizStart, @now));

            SELECT
              CAST(DATEADD(HOUR, -@bizStart, r.RCPT_DATE) AS date) AS BizDate,
              SUM(CASE WHEN c.ITM_QUANTITY > 0 THEN c.ITM_QUANTITY ELSE 0 END)                          AS Qty,
              SUM(CASE WHEN c.ITM_QUANTITY > 0 THEN c.ITM_QUANTITY * c.ITM_PRICE ELSE 0 END)            AS Amount
            FROM dbo.HISTORIC_RECEIPT_CONTENTS c
            JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
            WHERE c.ITM_CODE = @code
              AND DATEADD(HOUR, -@bizStart, r.RCPT_DATE) >= @windowStart
            GROUP BY CAST(DATEADD(HOUR, -@bizStart, r.RCPT_DATE) AS date)
            ORDER BY BizDate ASC;
        """, (code, int(days), int(biz_start_hour)))
        series = []
        for r in cur.fetchall():
            series.append({
                "date": str(r.BizDate),
                "qty": int(r.Qty or 0),
                "amount": float(r.Amount or 0)
            })

        # 3) Recent (last 5 receipts containing this item)
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @code nvarchar(128) = ?;

            SELECT TOP (5)
              r.RCPT_ID,
              r.RCPT_DATE,
              SUM(CASE WHEN c.ITM_QUANTITY > 0 THEN c.ITM_QUANTITY ELSE 0 END)                      AS Qty,
              AVG(CASE WHEN c.ITM_QUANTITY > 0 AND c.ITM_PRICE > 0 THEN CAST(c.ITM_PRICE AS float) END) AS UnitPriceAvg,
              SUM(CASE WHEN c.ITM_QUANTITY > 0 THEN c.ITM_QUANTITY * c.ITM_PRICE ELSE 0 END)        AS LineTotal
            FROM dbo.HISTORIC_RECEIPT_CONTENTS c
            JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
            WHERE c.ITM_CODE = @code
            GROUP BY r.RCPT_ID, r.RCPT_DATE
            ORDER BY r.RCPT_DATE DESC;
        """, (code,))
        recent = []
        for r in cur.fetchall():
            recent.append({
                "rcpt_id": r.RCPT_ID,
                "rcpt_date": _fmt_dt(r.RCPT_DATE),
                "qty": int(r.Qty or 0),
                "unit_price": float(r.UnitPriceAvg or 0) if r.UnitPriceAvg is not None else None,
                "line_total": float(r.LineTotal or 0)
            })

    return {
        "item": item_header,
        "window": {
            "days": int(days),
            "biz_start_hour": int(biz_start_hour),
            "biz_end_hour": int(biz_end_hour)
        },
        "summary": summary,
        "series": series,
        "recent": recent
    }

 
def update_item_fields(code: str, title: str = None, subgroup: str = None, price: float = None):
    """
    Update title (dbo.ITEMS.ITM_TITLE),
           subgroup (dbo.ITEMS.ITM_SUBGROUP),
           and price (dbo.ITEM_BARCODE.ITM_PRICE)
    Handles mixed-type subgroup (int or nvarchar).
    """
    if not code:
        return False, "Missing item code"

    if title is None and subgroup is None and price is None:
        return False, "No fields to update"

    try:
        with _connect() as cn:
            cur = cn.cursor()

            # --- update dbo.ITEMS ---
            if title is not None or subgroup is not None:
                sets, params = [], []
                if title is not None:
                    sets.append("ITM_TITLE = ?")
                    params.append(title.strip())

                if subgroup is not None:
                    subgroup_value = subgroup.strip()
                    # Try to convert to int if it's numeric
                    if subgroup_value.isdigit():
                        sets.append("ITM_SUBGROUP = CAST(? AS int)")
                        params.append(subgroup_value)
                    else:
                        sets.append("ITM_SUBGROUP = ?")
                        params.append(int(subgroup))  # store as integer ID


                sql = f"UPDATE dbo.ITEMS SET {', '.join(sets)} WHERE ITM_CODE = ?"
                params.append(code)
                cur.execute(sql, tuple(params))

            # --- update dbo.ITEM_BARCODE price ---
            if price is not None:
                cur.execute("""
                    UPDATE dbo.ITEM_BARCODE
                    SET ITM_PRICE = ?
                    WHERE ITM_CODE = ?
                """, (float(price), code))

            cn.commit()
        return True, None

    except Exception as e:
        try:
            cn.rollback()
        except Exception:
            pass
        return False, str(e)

