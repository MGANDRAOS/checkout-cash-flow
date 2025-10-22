# helpers_items.py
from helpers_intelligence import _connect

from helpers_intelligence import _connect

def list_items(page:int=1, page_size:int=25, q:str="", sort:str="", subgroup_id:int|None=None):
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
        cur.execute("""
            SET NOCOUNT ON;

            DECLARE @q     nvarchar(200) = ?;
            DECLARE @pat   nvarchar(210) = CASE WHEN @q = N'' THEN NULL ELSE N'%' + @q + N'%' END;
            DECLARE @sort  nvarchar(40)  = ?;
            DECLARE @dir   nvarchar(4)   = ?;
            DECLARE @sg    nvarchar(200) = ?;      -- text subgroup (fallback)
            DECLARE @sgid  int           = ?;      -- numeric subgroup id (primary)

            /* Base items */
            WITH I AS (
              SELECT
                i.ITM_CODE, i.ITM_TITLE, i.ITM_DESCRIPTION, i.ITM_TYPE,
                LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpRaw,
                CASE
                  WHEN i.ITM_SUBGROUP IS NOT NULL AND i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%'
                    THEN CONVERT(int, i.ITM_SUBGROUP)
                  ELSE NULL
                END AS SubGrpID
              FROM dbo.ITEMS i
            ),
            /* Resolve subgroup by ID first, else by name */
            J AS (
              SELECT
                I.ITM_CODE, I.ITM_TITLE, I.ITM_DESCRIPTION, I.ITM_TYPE, I.SubGrpRaw,
                COALESCE(s_id.SubGrp_ID, s_nm.SubGrp_ID)                                     AS ResolvedSubGrpID,
                LTRIM(RTRIM(COALESCE(s_id.SubGrp_Name, s_nm.SubGrp_Name, NULLIF(I.SubGrpRaw,N''), N'Unknown')))
                  COLLATE DATABASE_DEFAULT                                                    AS ResolvedSubgroup
              FROM I
              LEFT JOIN dbo.SUBGROUPS s_id ON s_id.SubGrp_ID = I.SubGrpID
              LEFT JOIN dbo.SUBGROUPS s_nm ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = I.SubGrpRaw
            ),
            /* Last purchase per item */
            LP AS (
              SELECT c.ITM_CODE, MAX(r.RCPT_DATE) AS LastPurchased
              FROM dbo.HISTORIC_RECEIPT_CONTENTS c
              JOIN dbo.HISTORIC_RECEIPT r ON r.RCPT_ID = c.RCPT_ID
              GROUP BY c.ITM_CODE
            ),
            /* Apply filters */
            F AS (
              SELECT
                J.ITM_CODE, J.ITM_TITLE, J.ITM_DESCRIPTION, J.ITM_TYPE,
                J.ResolvedSubGrpID, J.ResolvedSubgroup, LP.LastPurchased
              FROM J
              LEFT JOIN LP ON LP.ITM_CODE = J.ITM_CODE
              WHERE
                -- search
                (@pat IS NULL
                   OR (J.ITM_TITLE IS NOT NULL AND J.ITM_TITLE LIKE @pat)
                   OR (CAST(J.ITM_CODE AS nvarchar(128)) LIKE @pat)
                   OR (J.ResolvedSubgroup LIKE @pat))
                -- subgroup filter: prefer ID, else name
                AND (
                  @sgid IS NULL
                  OR J.ResolvedSubGrpID = @sgid
                )
                AND (
                  @sg = N'' OR UPPER(@sg) = N'ALL'
                  OR UPPER(J.ResolvedSubgroup) = UPPER(@sg)
                  OR (@sgid IS NOT NULL)    -- if id given, name test becomes irrelevant
                )
            ),
            B AS (
              SELECT
                F.ITM_CODE, F.ITM_TITLE, F.ITM_DESCRIPTION, F.ITM_TYPE,
                F.ResolvedSubgroup AS Subgroup, F.LastPurchased,
                ROW_NUMBER() OVER (
                  ORDER BY
                    CASE WHEN @sort='last_purchased' AND @dir='asc'  THEN CASE WHEN F.LastPurchased IS NULL THEN 1 ELSE 0 END END ASC,
                    CASE WHEN @sort='last_purchased' AND @dir='asc'  THEN F.LastPurchased END ASC,
                    CASE WHEN @sort='last_purchased' AND @dir='desc' THEN F.LastPurchased END DESC,

                    CASE WHEN @sort='code'    AND @dir='asc'  THEN F.ITM_CODE END ASC,
                    CASE WHEN @sort='code'    AND @dir='desc' THEN F.ITM_CODE END DESC,

                    CASE WHEN @sort='title'   AND @dir='asc'  THEN F.ITM_TITLE END ASC,
                    CASE WHEN @sort='title'   AND @dir='desc' THEN F.ITM_TITLE END DESC,

                    CASE WHEN @sort='type'    AND @dir='asc'  THEN F.ITM_TYPE END ASC,
                    CASE WHEN @sort='type'    AND @dir='desc' THEN F.ITM_TYPE END DESC,

                    CASE WHEN @sort='subgroup' AND @dir='asc' THEN F.ResolvedSubgroup END ASC,
                    CASE WHEN @sort='subgroup' AND @dir='desc' THEN F.ResolvedSubgroup END DESC,

                    -- default
                    CASE WHEN @sort='' THEN CASE WHEN F.LastPurchased IS NULL THEN 1 ELSE 0 END END ASC,
                    CASE WHEN @sort='' THEN F.LastPurchased END DESC,
                    F.ITM_TITLE ASC,
                    F.ITM_CODE  ASC
                ) AS rn,
                COUNT(1) OVER() AS total_count
              FROM F
            )
            SELECT ITM_CODE, ITM_TITLE, ITM_DESCRIPTION, ITM_TYPE, Subgroup, LastPurchased, rn, total_count
            FROM B
            WHERE rn BETWEEN ? AND ?
            ORDER BY rn;
        """, (q, sort_field, sort_dir, subgroup, subgroup_id, start_rn, end_rn))

        rows = cur.fetchall()
        items, total = [], 0
        for r in rows:
            total = int(r.total_count or 0)
            lp = None
            if getattr(r, 'LastPurchased', None) is not None:
                try: lp = r.LastPurchased.strftime('%Y-%m-%d %H:%M')
                except Exception: lp = str(r.LastPurchased)
            items.append({
                "code": r.ITM_CODE,
                "title": r.ITM_TITLE or "",
                "type": r.ITM_TYPE or "",
                "subgroup": r.Subgroup or "Unknown",
                "description": r.ITM_DESCRIPTION or "",
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

