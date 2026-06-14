"""Live stock math + batched POS units-sold query.

Pure-Python live computation (no DB/POS) plus ONE cached POS round-trip that
returns net units sold per item since each item's baseline business day.
POS is read-only and is NEVER used for stock levels (its stock field is unusable).
"""
from __future__ import annotations

from datetime import date as _date
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


def count_window_start(count_event) -> object:
    """Start of the 'units sold since' window for a count = the moment it was taken.

    Uses the count's `counted_at` (exact local timestamp) when present, so a count
    taken at any time of day only deducts sales AFTER it. Falls back to the count's
    business-day 08:00 start for legacy counts saved before `counted_at` existed.
    """
    ca = getattr(count_event, "counted_at", None)
    if ca is not None:
        return ca
    from pos_dates import biz_date_range_8h  # lazy: keep this module import-light
    return biz_date_range_8h(count_event.event_date)[0]


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


# Days of demand a reorder suggestion aims to cover, on top of the alert threshold.
_REORDER_COVER_DAYS = 14


def latest_receive_cost_cents(events: Iterable) -> Optional[int]:
    """Most recent receive's unit_cost_cents (current cost basis), or None."""
    costed = [e for e in events
              if e.event_type == "receive" and getattr(e, "unit_cost_cents", None) is not None]
    if not costed:
        return None
    return max(costed, key=lambda e: (e.event_date, e.created_at)).unit_cost_cents


def stock_analytics(events: Iterable, info: dict, threshold: float,
                    today: Optional[object] = None) -> dict:
    """Derived per-item metrics from the ledger + a compute_live() result.

    Pure Python (no DB/POS). Returns sales velocity (units/day over the observed
    window), days of cover, a reorder suggestion, the current cost basis and the
    inventory value at that basis. Safe to call on items with no baseline.
    """
    events = list(events)
    receives = [e for e in events if e.event_type == "receive"]
    counts = [e for e in events if e.event_type == "count"]
    out = {
        "velocity": None, "days_cover": None, "days_since_baseline": None,
        "reorder_qty": 0, "needs_reorder": False,
        "last_cost_cents": latest_receive_cost_cents(events), "value_cents": None,
        "receive_count": len(receives), "count_count": len(counts),
        "received_since": float(info.get("receives", 0.0) or 0.0),
        "last_count_date": None,
    }

    if not info.get("has_baseline"):
        return out

    d0 = info.get("d0")
    out["last_count_date"] = str(d0) if d0 else None

    today = today or _date.today()
    try:
        days = max((today - d0).days, 0)
    except Exception:
        days = 0
    out["days_since_baseline"] = days

    sold = float(info.get("sold", 0.0) or 0.0)
    live = info.get("live")
    eff_days = max(days, 1)  # avoid div-by-zero and single-day velocity spikes
    velocity = sold / eff_days if sold > 0 else 0.0
    out["velocity"] = round(velocity, 3)

    if velocity > 0 and live is not None:
        out["days_cover"] = round(max(live, 0.0) / velocity, 1)
    # velocity == 0 with stock on hand -> cover is effectively infinite (left None)

    if out["last_cost_cents"] is not None and live is not None:
        out["value_cents"] = int(round(max(live, 0.0) * out["last_cost_cents"]))

    # Reorder when at/under the alert threshold or within the cover horizon.
    if live is not None:
        target = threshold + velocity * _REORDER_COVER_DAYS
        need = target - live
        within_horizon = out["days_cover"] is not None and out["days_cover"] <= _REORDER_COVER_DAYS
        if need > 0 and (live <= threshold or within_horizon):
            out["needs_reorder"] = True
            out["reorder_qty"] = int(need) + (1 if need > int(need) else 0)  # ceil
    return out


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
    # UNION ALL covers both today's live receipts (dbo.RECEIPT/RECEIPT_CONTENTS) and
    # finalized historical receipts (dbo.HISTORIC_RECEIPT/HISTORIC_RECEIPT_CONTENTS).
    # Without the live tables, today's sales would never deduct from stock until end-of-day.
    # CAST(c.ITM_CODE AS nvarchar(128)): ITM_CODE is not reliably string-typed in the POS
    # schema — every other query in this codebase casts it before comparing.
    sql = f"""
        SET NOCOUNT ON;
        SELECT v.itm_code AS itm_code, SUM(c.ITM_QUANTITY) AS sold
        FROM (VALUES {values_rows}) AS v(itm_code, win_start)
        JOIN (
            SELECT RCPT_ID, ITM_CODE, ITM_QUANTITY FROM dbo.HISTORIC_RECEIPT_CONTENTS
            UNION ALL
            SELECT RCPT_ID, ITM_CODE, ITM_QUANTITY FROM dbo.RECEIPT_CONTENTS
        ) c ON CAST(c.ITM_CODE AS nvarchar(128)) = v.itm_code
        JOIN (
            SELECT RCPT_ID, RCPT_DATE FROM dbo.HISTORIC_RECEIPT
            UNION ALL
            SELECT RCPT_ID, RCPT_DATE FROM dbo.RECEIPT
        ) r ON r.RCPT_ID = c.RCPT_ID AND r.RCPT_DATE >= v.win_start
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


@ttl_cache(seconds=30)
def live_last_sold(codes: Tuple[str, ...]) -> Dict[str, object]:
    """Most-recent sale datetime per item from TODAY's live receipts only.

    The Stock search's "last purchased" comes from helpers_items.list_items, whose
    query reads only the archived dbo.HISTORIC_RECEIPT* tables -> an item whose only
    sale is today (still in the live dbo.RECEIPT* tables) shows no date. This fills
    that gap, mirroring units_sold_since which already unions both table sets.

    `codes` MUST be a sorted tuple so the ttl_cache key is stable across reloads.
    Returns {} for no codes; items with no live sale simply won't appear in the dict.
    CAST(c.ITM_CODE AS nvarchar(128)): ITM_CODE is not reliably string-typed in the POS
    schema, so every comparison casts it first (same as build_units_sold_query).
    """
    codes = tuple(str(c) for c in codes if c not in (None, ""))
    if not codes:
        return {}
    placeholders = ",".join(["?"] * len(codes))
    sql = f"""
        SET NOCOUNT ON;
        SELECT CAST(c.ITM_CODE AS nvarchar(128)) AS itm_code, MAX(r.RCPT_DATE) AS last_sold
        FROM dbo.RECEIPT_CONTENTS c
        JOIN dbo.RECEIPT r ON r.RCPT_ID = c.RCPT_ID
        WHERE CAST(c.ITM_CODE AS nvarchar(128)) IN ({placeholders})
        GROUP BY CAST(c.ITM_CODE AS nvarchar(128));
    """
    from helpers_intelligence import _connect  # lazy: avoids pyodbc import at module load
    out: Dict[str, object] = {}
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(sql, codes)
        for row in cur.fetchall():
            if row.last_sold is not None:
                out[str(row.itm_code)] = row.last_sold
    return out
