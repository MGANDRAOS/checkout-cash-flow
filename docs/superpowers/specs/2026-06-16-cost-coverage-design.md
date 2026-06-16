# Cost Coverage — "fix missing costs" worklist

**Date:** 2026-06-16
**Status:** Approved (brainstorming)

## Goal

A focused report that answers one question: **which items should I put a cost on first?**
35% of the active catalog (1,064 / 3,014 items) has no `ITM_COST`, and 133 of those
**sold in the last 90 days** — ~270.5M LBP of revenue the profit reports can't see.
This page ranks the uncosted-but-selling items by revenue-at-risk so the owner fixes
the highest-impact ones (in the POS — the app is read-only on POS data).

## Definitions

- **Uncosted item:** `ITM_COST IS NULL OR ITM_COST = 0`.
- **Active:** `ITM_ACTIVE = 1`.
- **Coverage %:** `(active − uncosted_active) / active × 100` (catalog-wide headline).
- **Revenue-at-risk:** revenue (within the window) from uncosted items shown in the worklist.
- **Window:** business-day window via `biz_date_range_7h`, default **90 days** back from today.

## Components

### 1. Pure summary — `helpers_intelligence._cost_coverage_summary`

DB-free, unit-testable:

```python
def _cost_coverage_summary(active, uncosted_active, dormant_uncosted, rows) -> dict:
    """
    rows: uncosted items that sold in the window
          [{item_code, item, subgroup, qty, revenue, avg_price, last_sold}, ...]
          (already sorted by revenue desc from SQL; re-sorted defensively)
    Returns:
      {
        "coverage": {"active", "uncosted_active", "coverage_pct"},
        "at_risk":  {"items": len(rows), "revenue": sum(row.revenue)},
        "dormant_uncosted": int,   # active+uncosted items that did NOT sell in window
        "rows": rows,
      }
    """
```

`coverage_pct = round((active − uncosted_active) / active × 100, 1)` if `active` else `0.0`.

### 2. SQL helper — `helpers_intelligence.get_cost_coverage(days=90, subgroup_label=None)`

`days` clamped to 1..730. One `_connect()`, three statements:

1. **Coverage counts** (catalog-wide): `active`, `uncosted_active` from `dbo.ITEMS`.
2. **Worklist rows:** uncosted items (`ITM_COST IS NULL OR =0`) that sold in the window —
   `SUM(qty)`, `SUM(qty*price)` AS revenue, `revenue/qty` AS avg_price,
   `MAX(RCPT_DATE)` AS last_sold, subgroup (the proven resolution CTE). Optional subgroup
   filter applies here. `ORDER BY revenue DESC`.
3. **Dormant count:** active + uncosted items with `NOT EXISTS` a sale in the window.

Window bounds from `biz_date_range_7h(today - days + 1)` start .. `biz_date_range_7h(today)` end.
Python maps `last_sold` to `YYYY-MM-DD`, builds `rows`, calls `_cost_coverage_summary`,
adds `meta = {days, subgroup, generated_for: today.isoformat()}`.

### 3. Route — `routes/cost_coverage.py`

- `GET /reports/cost-coverage` → `render_template("report_cost_coverage.html")`.
- `GET /api/reports/cost-coverage` → JSON. Params: `days` (int, default 90, clamp 1..730),
  `subgroup` (optional). Adds `at_risk.revenue_usd` via `config.USD_EXCHANGE_RATE`.
  Structured `{"error": ...}` on failure (keep UI alive), mirroring `routes/items_sold.py`.
- `GET /api/reports/cost-coverage/export-csv` → CSV worklist:
  `item_code, item, subgroup, units, revenue, avg_price, last_sold`.
- Reuses existing `/api/reports/subgroups`. Registered in `main.py`.

### 4. Frontend — `report_cost_coverage.html` + `static/js/cost_coverage.js` + `static/css/cost_coverage.css`

Mobile-first, same `is-` design language. Build with frontend-design polish.
- **Coverage hero:** big `coverage_pct%` ("cost coverage") + subline
  "`uncosted_active` items missing cost · `at_risk.items` sold recently ·
  `at_risk.revenue` LBP (≈ USD) profit-blind". A thin coverage progress bar.
- **Controls:** window chips (30 / 90 / 180 / 365 days), subgroup `<select>`, live search box.
- **Worklist:** one row per uncosted-but-selling item — **item code shown prominently**
  (to find it in the POS), name, subgroup, units, **revenue-at-risk** (primary), avg sell
  price, last-sold date. Ranked by revenue. Top item gets the gold accent.
- **Dormant note:** "+`dormant_uncosted` uncosted items haven't sold in `days` days (low priority)."
- **Export CSV** button. Loading / empty ("Every item that sold has a cost — 100% covered 🎉") / error states.

### 5. Navigation — `templates/base.html`

Sidebar link **"Cost Coverage"** under **Items** (after *Items Sold*), icon `bi-clipboard-check`,
active on `request.path.startswith('/reports/cost-coverage')`.

### 6. Tests

- `tests/test_helpers_cost_coverage.py`: `_cost_coverage_summary` — coverage_pct math,
  at_risk derivation, empty rows, 100%-covered (uncosted_active=0).
- `tests/test_routes_cost_coverage.py`: `days` clamp + default, `revenue_usd` present,
  JSON shape, CSV header + rows (helper mocked).

## Out of scope (YAGNI)

- Editing costs from the app (POS is read-only).
- Listing the ~931 dormant uncosted items beyond the count.
- Per-subgroup coverage % (headline stays catalog-wide; subgroup filters the worklist).

## Verification

- Pure + route tests pass.
- Live smoke: `get_cost_coverage(90)` → coverage_pct ≈ 65%, ~133 rows, revenue-at-risk ≈ 270.5M LBP,
  top row a real seller (e.g. Fantasia XL).
- UI pass (inspect): hero, worklist, CSV, mobile + desktop layouts.
