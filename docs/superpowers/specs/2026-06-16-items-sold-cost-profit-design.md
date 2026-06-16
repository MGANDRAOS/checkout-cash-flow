# Items Sold — Cost, Profit & Margin (extension)

**Date:** 2026-06-16
**Status:** Approved (brainstorming)
**Extends:** [Items Sold Report](2026-06-16-items-sold-report-design.md)

## Goal

Add per-item **cost**, **profit**, and **margin %** to the existing Items Sold report.
Cost is pulled from the POS `ITEMS` table and converted to LBP via the `CURRENCY` table.

## Data source & currency (verified against live POS)

- Unit cost: `dbo.ITEMS.ITM_COST` (stored in the item's **buy currency**).
- Buy currency: `dbo.ITEMS.ITM_BUYCURRENCY` → `dbo.CURRENCY.CURR_ID`.
- Conversion to LBP: multiply by `dbo.CURRENCY.CURR_PURCHASE_PARITY`
  (`CURR_ID 0 = LL` parity `1.0`; `CURR_ID 1 = USD` parity `89000`).
- Receipt-contents has **no** cost column, so cost is the item's *current* cost
  (not cost-at-time-of-sale) — surfaced as a caveat.
- Verified: USD-bought item code `2098` → `ITM_COST 0.31 × 89000 = 27,590 LBP`.
  All items sold in the last 45 days are `buycur=0` (LL, ×1), but USD items must
  still convert correctly whenever they sell.

### Cost rule

```
unit_cost_lbp = ITM_COST × COALESCE(NULLIF(CURR_PURCHASE_PARITY, 0), 1.0)
```

- `ITM_COST` of `0` or `NULL` → **cost unknown** (`None`): UI shows "—", row is
  excluded from all profit/margin math and from profit totals.
- Missing/zero parity → defaults to ×1.0 (treat as LBP) so cost is never silently zeroed.

## Components

### 1. SQL — `helpers_intelligence.get_items_sold_range`

- Add `LEFT JOIN dbo.CURRENCY cu ON cu.CURR_ID = i.ITM_BUYCURRENCY`.
- Select per item:
  `MAX(CAST(i.ITM_COST AS float) * COALESCE(NULLIF(CAST(cu.CURR_PURCHASE_PARITY AS float), 0), 1.0)) AS unit_cost`
  (MAX is safe — one `ITEMS` row per `item_code`).
- Raw row gains `unit_cost`: a float, or `None` when `ITM_COST` is `0`/`NULL`
  (mapped in Python: `unit_cost = v if v and v > 0 else None`).

### 2. Pure summarizer — `helpers_intelligence._summarize_items_sold`

For each row, when `unit_cost` is not None:
- `total_cost = unit_cost × qty`
- `profit = revenue − total_cost`
- `margin = round(profit / revenue × 100, 1)` if `revenue` else `0.0`

When `unit_cost` is None → `total_cost`, `profit`, `margin` all `None`.

Grand totals (added to existing `items/qty/revenue`):
- `cost` = Σ `total_cost` over costed rows
- `profit` = Σ `profit` over costed rows
- `costed_revenue` = Σ `revenue` over costed rows
- `margin` = `round(profit / costed_revenue × 100, 1)` if `costed_revenue` else `0.0`
- `uncosted_items` = count of rows with `unit_cost is None`

### 3. Route — `routes/items_sold.py`

- `api_items_sold`: after existing `revenue_usd`, add
  `data["totals"]["profit_usd"] = (totals["profit"] / rate) if rate else 0.0`.
- `api_items_sold_csv`: header becomes
  `subgroup,item_code,item,qty,unit_cost,avg_price,revenue,total_cost,profit,margin_pct,share_pct`.
  Per row: blank cost fields render as empty strings when `None`.
  TOTAL row: `qty`, `revenue`, `cost`, `profit`, `margin`, `100.0` in matching columns.

### 4. Frontend

- **KPI hero** (`report_items_sold.html` + js + css): add a **Profit** block
  (`#isKpiProfitLbp` LBP primary, `#isKpiProfitUsd` USD secondary) with a
  `#isKpiMargin` margin-% label. Place beside Revenue; Units/Items move down a row.
- **Item row:** show `unit cost` and a **color-coded margin %**:
  emerald (`--emerald`) when `margin > 0`, crimson (`--crimson`) when `margin < 0`
  (sold below cost), muted "—" when cost unknown. Desktop columns:
  `name · units · cost · avg price · revenue · margin%`. Mobile keeps the stacked
  layout (cost + margin join the stats line).
- **Subgroup card header:** add the group's margin % to the subtotal line
  (group margin = group profit ÷ group costed-revenue).
- **Caveat line** under results: "Profit uses each item's current cost. N items have no cost set." (hidden when `uncosted_items == 0`).
- JS computes group-level cost/profit/margin from the per-row fields (mirrors the
  server's costed-revenue rule); rows with `unit_cost == null` are skipped from group profit.

### 5. Tests

- `tests/test_helpers_items_sold.py`: cost math, unknown-cost (None) handling,
  margin on costed revenue, negative margin (loss), `uncosted_items` count.
- `tests/test_routes_items_sold.py`: `profit_usd` present and correct; CSV header
  has the new columns and a TOTAL row with profit.

## Out of scope (YAGNI)

No cost editing, no historical cost-at-sale reconstruction, no profit charts.

## Verification

- Summarizer + route tests pass (`pytest tests/`).
- Live smoke: real range returns `unit_cost`/`profit`/`margin`; grand `cost`/`profit`
  consistent with `revenue`; a USD-bought item (if present) converts via parity.
- UI pass (computed-style/inspect): Profit KPI renders, item rows show cost + colored
  margin, mobile + desktop layouts intact, CSV downloads with new columns.
