"""Live stock math + batched POS units-sold query.

Pure-Python live computation (no DB/POS) plus ONE cached POS round-trip that
returns net units sold per item since each item's baseline business day.
POS is read-only and is NEVER used for stock levels (its stock field is unusable).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from cache_utils import ttl_cache


def latest_count(events: Iterable) -> Optional[object]:
    """Return the 'count' event with the greatest (event_date, created_at), or None."""
    counts = [e for e in events if e.event_type == "count"]
    if not counts:
        return None
    return max(counts, key=lambda e: (e.event_date, e.created_at))


def receives_after(events: Iterable, count_event) -> float:
    """Sum 'receive' deltas strictly after the baseline count event."""
    total = 0.0
    for e in events:
        if e.event_type != "receive":
            continue
        after = e.event_date > count_event.event_date or (
            e.event_date == count_event.event_date
            and e.created_at > count_event.created_at
        )
        if after:
            total += e.qty
    return total


def status_for(live: float, threshold: float) -> str:
    """Out (<=0), Low (<=threshold), else OK."""
    if live <= 0:
        return "out"
    if live <= threshold:
        return "low"
    return "ok"


def compute_live(events: Iterable, sold_units: float, threshold: float) -> dict:
    """Derive live stock for one item from its ledger + net units sold since baseline.

    live = q0 + receives_after - sold_units
    `events` is the full event list for the item; `sold_units` is the net units sold
    since the latest count's business day (queried separately, may be 0/negative).
    """
    events = list(events)
    c = latest_count(events)
    if c is None:
        return {"live": None, "status": "unknown", "q0": None, "d0": None,
                "receives": 0.0, "sold": 0.0, "has_baseline": False}
    r = receives_after(events, c)
    sold = sold_units or 0.0
    live = c.qty + r - sold
    return {"live": live, "status": status_for(live, threshold), "q0": c.qty,
            "d0": c.event_date, "receives": r, "sold": sold, "has_baseline": True}


def build_units_sold_query(pairs: Tuple[Tuple[str, object], ...]) -> Tuple[str, List[object]]:
    """Build the batched units-sold SQL + positional params for (itm_code, win_start) pairs.

    Returns ("", []) for no pairs. Each pair contributes one VALUES row; the join
    keeps RCPT_DATE sargable (>= per-item window start). Net SUM (returns subtract).
    """
    if not pairs:
        return "", []
    values_rows = ",".join(["(?, ?)"] * len(pairs))
    params: List[object] = []
    for code, start in pairs:
        params.append(str(code))
        params.append(start)
    sql = f"""
        SET NOCOUNT ON;
        SELECT v.itm_code AS itm_code, SUM(c.ITM_QUANTITY) AS sold
        FROM (VALUES {values_rows}) AS v(itm_code, win_start)
        JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.ITM_CODE = v.itm_code
        JOIN dbo.HISTORIC_RECEIPT r
          ON r.RCPT_ID = c.RCPT_ID AND r.RCPT_DATE >= v.win_start
        GROUP BY v.itm_code;
    """
    return sql, params


@ttl_cache(seconds=45)
def units_sold_since(pairs: Tuple[Tuple[str, object], ...]) -> Dict[str, float]:
    """Net units sold per item since each item's baseline business-day start.

    ONE batched POS round-trip (read-only). `pairs` MUST be a sorted tuple so the
    ttl_cache key is stable across reloads. Returns {} for no pairs. Missing items
    (no sales) simply won't appear in the dict -> treated as 0 by callers.
    """
    sql, params = build_units_sold_query(pairs)
    if not sql:
        return {}
    from helpers_intelligence import _connect  # lazy: avoids pyodbc import at module load
    out: Dict[str, float] = {}
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(sql, tuple(params))
        for row in cur.fetchall():
            out[str(row.itm_code)] = float(row.sold or 0.0)
    return out
