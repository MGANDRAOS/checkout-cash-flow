# helpers_items.py
from helpers_intelligence import _connect  # reuse the same connection helper

def list_items(page:int=1, page_size:int=25, q:str=""):
    page = max(1, int(page))
    page_size = min(200, max(5, int(page_size)))
    start_rn = (page - 1) * page_size + 1
    end_rn = page * page_size
    q = (q or "").strip()

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @q nvarchar(200) = ?;
            DECLARE @pat nvarchar(210) = CASE WHEN @q = N'' THEN NULL ELSE N'%' + @q + N'%' END;

            /* Base item info */
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
            ),
            J AS (
              SELECT
                I.ITM_CODE, I.ITM_TITLE, I.ITM_DESCRIPTION, I.ITM_TYPE, I.SubGrpRaw,
                COALESCE(s_id.SubGrp_Name, s_nm.SubGrp_Name) AS SubGrp_Name
              FROM I
              LEFT JOIN dbo.SUBGROUPS s_id ON s_id.SubGrp_ID = I.SubGrpID
              LEFT JOIN dbo.SUBGROUPS s_nm ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = I.SubGrpRaw
            ),

            /* Last purchase datetime per item (from receipts/contents) */
            LP AS (
              SELECT c.ITM_CODE, MAX(r.RCPT_DATE) AS LastPurchased
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              GROUP BY c.ITM_CODE
            ),

            /* Filter by search */
            F AS (
              SELECT
                J.ITM_CODE,
                J.ITM_TITLE,
                J.ITM_DESCRIPTION,
                J.ITM_TYPE,
                COALESCE(J.SubGrp_Name, NULLIF(J.SubGrpRaw, N''), N'Unknown') AS Subgroup,
                LP.LastPurchased
              FROM J
              LEFT JOIN LP ON LP.ITM_CODE = J.ITM_CODE
              WHERE (@pat IS NULL
                     OR (J.ITM_TITLE IS NOT NULL AND J.ITM_TITLE LIKE @pat)
                     OR (CAST(J.ITM_CODE AS nvarchar(128)) LIKE @pat)
                     OR (J.SubGrp_Name IS NOT NULL AND J.SubGrp_Name LIKE @pat))
            ),

            /* Page it */
            B AS (
              SELECT
                F.*,
                ROW_NUMBER() OVER (
                  ORDER BY
                    CASE WHEN F.LastPurchased IS NULL THEN 1 ELSE 0 END,  -- items never sold go last
                    F.LastPurchased DESC,                                 -- newest first
                    CASE WHEN F.ITM_TITLE IS NULL OR LTRIM(RTRIM(F.ITM_TITLE))=N'' THEN 1 ELSE 0 END,
                    F.ITM_TITLE,
                    F.ITM_CODE
                ) AS rn,
                COUNT(1) OVER() AS total_count
              FROM F
            )
            SELECT ITM_CODE, ITM_TITLE, ITM_DESCRIPTION, ITM_TYPE, Subgroup, LastPurchased, rn, total_count
            FROM B
            WHERE rn BETWEEN ? AND ?
            ORDER BY rn;
        """, (q, start_rn, end_rn))

        rows = cur.fetchall()
        items = []
        total = 0
        for r in rows:
            total = int(r.total_count or 0)
            # r.LastPurchased is a datetime or None
            lp = None
            if getattr(r, 'LastPurchased', None) is not None:
                try:
                    lp = r.LastPurchased.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    lp = str(r.LastPurchased)
            items.append({
                "code": r.ITM_CODE,
                "title": r.ITM_TITLE or "",
                "type": r.ITM_TYPE or "",
                "subgroup": r.Subgroup or "Unknown",
                "description": r.ITM_DESCRIPTION or "",
                "last_purchased": lp  # string or null
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}