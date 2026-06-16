# Items Sold Report — Design Spec

**Date:** 2026-06-16
**Status:** Approved (brainstorming)

## Goal

A dedicated page where the user picks a **start date** and **end date**, optionally
picks **one subgroup**, and sees **everything that was sold** in that window —
grouped by subgroup, each item showing **units + revenue**, with subgroup subtotals,
a grand total, and **CSV export**. Mobile-first, best-in-class UI consistent with the
existing app design system.

This fills the gap between the two existing reports:
- `get_items_sold(date)` — flat per-item list but **single day only**.
- `/reports/item-trends` — date range + subgroup but **time-bucketed top-N trends** (heavier/analytical).

## Non-goals (YAGNI)

- No daily/weekly/monthly time-buckets (that is Item Trends).
- No multi-subgroup selection (single optional subgroup, as requested).
- No charts/graphs — a fast, readable "what sold" list.
- No new subgroup endpoint — reuse the existing `/api/reports/subgroups`.

## Business rules

- **Business-day window:** uses the app's 07:00 boundary via `DATEADD(HOUR, -7, RCPT_DATE)`,
  consistent with `get_item_trends` and `helpers_intelligence`. Date range is **inclusive**
  of both start and end business days: `[start 00:00, end+1 00:00)` applied to the
  business-date shift.
- **Safety clamp:** reject ranges longer than **730 days** (mirrors Item Trends).
- **Subgroup resolution:** reuse the proven CTE from `get_item_trends` — resolves
  `ITM_SUBGROUP` whether it is a numeric `SubGrp_ID`, a `SubGrp_Name`, or free text;
  falls back to `'Unknown'`.
- **Money:** per-item revenue shown in the primary POS currency (LBP). USD is shown
  only on the KPI hero and grand total, using `USD_EXCHANGE_RATE` (same convention as
  Sales Snapshot). Per-item rows stay single-currency to avoid clutter.

## Components (each isolated, one responsibility)

### 1. Backend helper — `helpers_intelligence.py`

```python
def get_items_sold_range(start_date, end_date, subgroup_label=None) -> dict:
    """
    Flat per-item sales aggregation over an inclusive business-day range,
    optionally filtered to one subgroup.

    Returns:
      {
        "rows": [
          { "subgroup": str, "item_code": str, "item": str,
            "qty": float, "revenue": float, "avg_price": float,
            "txns": int, "share": float },   # share = % of total revenue
          ...
        ],
        "totals": { "items": int, "qty": float, "revenue": float, "txns": int },
        "meta": { "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",
                  "subgroup": str|None, "days": int }
      }
    """
```

- One row per `item_code` aggregated across the range.
- `qty = SUM(ITM_QUANTITY)`, `revenue = SUM(ITM_QUANTITY * ITM_PRICE)`,
  `avg_price = revenue / NULLIF(qty,0)`, `txns = COUNT(DISTINCT RCPT_ID)`.
- Rows sorted by `revenue DESC, item ASC`.
- `share` = item revenue / total revenue * 100 (computed in Python from the row set).
- Reuses `_connect()` (login + per-query timeout already configured).
- `@ttl_cache` if the existing decorator is used by sibling functions (keep parity).

### 2. Blueprint — `routes/items_sold.py`

- `GET /reports/items-sold` → `render_template("report_items_sold.html")`
- `GET /api/reports/items-sold` → JSON. Params: `start_date`, `end_date` (both
  required, `YYYY-MM-DD`), `subgroup` (optional label). Validates dates, ordering,
  and the 730-day clamp exactly like `routes/item_trends.py`; returns structured
  `{"error": ...}` with a 400 on bad input rather than crashing the UI.
- `GET /api/reports/items-sold/export-csv` → `text/csv` attachment. Columns:
  `subgroup, item_code, item, qty, avg_price, revenue, share`, with a trailing
  `TOTAL` row (mirrors the Sales Snapshot CSV export shape).
- Subgroup dropdown is fed by the **existing** `/api/reports/subgroups`.
- Register the blueprint in `main.py` alongside the other report blueprints.

### 3. Frontend — `templates/report_items_sold.html` + `static/js/items_sold.js` + scoped CSS

Mobile-first, custom-rendered (not DataTables/AG Grid — neither groups gracefully on a
phone). Built with the **frontend-design** skill, matching the `snap-*` visual language.

Layout (top → bottom, single column on mobile):
- **Header:** title "Items Sold" + one-line subtitle.
- **Quick-range chips:** Today · Yesterday · Last 7 · Last 30 · This Month (set From/To).
- **Filter strip:** From → To date inputs, subgroup `<select>` (default "All subgroups"),
  live client-side item-search box, Apply button.
- **KPI hero:** distinct items · total units · total revenue (LBP primary, USD secondary).
- **Results = collapsible subgroup cards:** each card = one subgroup with a subtotal
  header (units + revenue + % of grand total). Tap to expand item rows
  (name · qty · revenue · avg price · share). Groups sorted by subtotal revenue DESC;
  items within a group sorted by revenue DESC. When a single subgroup is filtered, that
  card is expanded by default. On desktop the cards expand into a richer grouped table.
- **Sticky footer / action bar:** Export CSV button + grand-total line.
- **States:** loading skeleton, empty ("No items sold in this range."), and error.

### 4. Navigation — `templates/base.html`

Add sidebar link **"Items Sold"** under the **Items** section, immediately after
*Item Trends*, icon `bi-card-checklist`, active when `request.path.startswith('/reports/items-sold')`.

## Data flow

1. Page loads → JS sets default range (Last 7 days), fetches `/api/reports/subgroups`
   to populate the dropdown, then fetches `/api/reports/items-sold`.
2. User changes dates / subgroup / quick-chip → JS re-fetches the JSON endpoint and
   re-renders the grouped cards + KPI hero. Item-search filters the rendered set
   client-side (no refetch).
3. Export CSV → browser navigates to the export endpoint with the current params.

## Error handling

- API validates inputs; bad input → 400 with `{"error": ...}`; JS shows the message
  inline (never a blank page).
- MSSQL errors are caught and returned as a structured error payload (like
  `api_sales_summary_range`), keeping the UI responsive.
- Query timeout is inherited from `_connect()`.

## Testing

- `python -c "import main"` from the server-equivalent venv to confirm no import/registration error.
- Smoke the helper against the POS DB for a known range (with and without a subgroup);
  confirm row shape, totals, and that `share` sums to ~100.
- Manual UI pass on a narrow (mobile) viewport: chips, date change, subgroup filter,
  expand/collapse, search, CSV export, empty/error states.
