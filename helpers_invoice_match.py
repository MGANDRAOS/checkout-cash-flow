"""Match invoice line text to POS items: alias memory + Python fuzzy ranking.

Matching runs against a catalog loaded with ONE cached POS query, so a multi-line
invoice stays a single POS round-trip (per CLAUDE.md 502-avoidance).
"""
from __future__ import annotations

import re
from typing import List, Optional

from cache_utils import ttl_cache
from models import db, StockItemAlias


def _tokens(text: str):
    return set(t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t)


def rank_match(raw_description: str, catalog: List[dict], limit: int = 5) -> List[dict]:
    """Pure token-overlap ranker. Returns best candidates (Jaccard score), highest first."""
    q = _tokens(raw_description)
    if not q:
        return []
    scored = []
    for it in catalog:
        c = _tokens(it.get("title")) | _tokens(it.get("code"))
        if not c:
            continue
        inter = q & c
        if not inter:
            continue
        score = len(inter) / len(q | c)
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"code": str(it["code"]), "title": it.get("title", ""),
             "subgroup": it.get("subgroup", ""), "score": round(s, 3)}
            for s, it in scored[:limit]]


@ttl_cache(seconds=120)
def load_catalog() -> List[dict]:
    """All POS items as [{code,title,subgroup}] — ONE cached query for fuzzy matching."""
    from helpers_intelligence import _connect  # lazy: avoid pyodbc import at module load
    rows = []
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            SELECT CAST(i.ITM_CODE AS nvarchar(128)) AS code,
                   LTRIM(RTRIM(COALESCE(i.ITM_TITLE, ''))) AS title,
                   LTRIM(RTRIM(COALESCE(s.SubGrp_Name, ''))) AS subgroup
            FROM dbo.ITEMS i
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)));
        """)
        for r in cur.fetchall():
            rows.append({"code": str(r.code), "title": r.title or "", "subgroup": r.subgroup or ""})
    return rows


def alias_lookup(raw_description: str) -> Optional[str]:
    a = StockItemAlias.query.filter_by(raw_description=(raw_description or "").strip()).first()
    return a.itm_code if a else None


def upsert_alias(raw_description: str, itm_code: str) -> None:
    """Add to the session (caller commits). Overwrites an existing alias for the same text."""
    desc = (raw_description or "").strip()
    if not desc or not itm_code:
        return
    a = StockItemAlias.query.filter_by(raw_description=desc).first()
    if a:
        a.itm_code = str(itm_code)
    else:
        db.session.add(StockItemAlias(raw_description=desc, itm_code=str(itm_code)))


def match_lines(lines: List[dict], catalog: List[dict]) -> List[dict]:
    """For each OCR line attach `match` (chosen item or None) and `candidates` (alternates)."""
    by_code = {str(it["code"]): it for it in catalog}
    out = []
    for ln in lines:
        desc = ln.get("raw_description", "")
        candidates = rank_match(desc, catalog)
        aliased = alias_lookup(desc)
        if aliased:
            cat = by_code.get(str(aliased))
            chosen = {"code": str(aliased), "title": cat["title"] if cat else "",
                      "subgroup": cat["subgroup"] if cat else "", "score": 1.0}
        else:
            chosen = candidates[0] if candidates else None
        out.append({**ln, "match": chosen, "candidates": candidates})
    return out
