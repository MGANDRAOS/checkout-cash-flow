# Invoices Page — Insight Layer

**Date:** 2026-07-05
**Status:** Approved, ready to build
**Scope:** Enhance the existing Invoices listing page (`/invoices`) with cost/profit insight. No new pages, no schema changes.

## Goal

Turn the Invoices page from a plain receipt/day list into something that tells the
owner *how much money was made*, not just how much was rung up. Add cost, profit,
and margin at three levels: a summary strip, per-row columns, and totals footers.

## Current state

- `routes/invoices.py` — page + 4 JSON endpoints.
- `templates/invoices.html` — filters, two tabs (Invoices, Daily Items), shared modal.
- `static/js/invoices.js` — client-side pagination, renders both tables, opens modals.
- `helpers_intelligence.py` — `get_invoices_list`, `get_daily_items_summary` (the two
  queries we enrich), plus detail helpers (unchanged).

Data model: `HISTORIC_RECEIPT` (RCPT_ID, RCPT_DATE, RCPT_AMOUNT) →
`HISTORIC_RECEIPT_CONTENTS` (RCPT_ID, ITM_CODE, ITM_QUANTITY) → `ITEMS`
(ITM_COST, ITM_BUYCURRENCY) → `CURRENCY` (CURR_PURCHASE_PARITY).

BizDate = `RCPT_DATE` shifted −7 hours, cast to date.

## Cost convention (reused verbatim from items-sold)

```
unit_cost = ITM_COST * COALESCE(NULLIF(CURRENCY.CURR_PURCHASE_PARITY, 0), 1.0)
```
A line is **uncosted** when `ITM_COST` is 0/NULL (→ unit_cost 0/NULL). Uncosted lines
are excluded from cost sums.

## Features

### 1. KPI summary strip
A row of cards above the tabs, recomputed client-side whenever the filter changes,
from the loaded invoice dataset (single source of truth):

- **Receipts** — count of receipts in range
- **Total Sales** — Σ RCPT_AMOUNT
- **Avg Ticket** — Total Sales / Receipts
- **Items Sold** — Σ qty across all lines
- **Cost** — Σ line cost over costed lines
- **Profit** — Σ (amount − cost) over **fully-costed receipts only**
- **Margin %** — Profit / (Σ amount over fully-costed receipts)

Caveat line under the strip: *"N of M receipts fully costed (X%)."*

### 2. Per-row profit columns

**Invoices tab** — add `Cost`, `Profit`, `Margin` after `Amount`:
- Cost: always shown (dimmed), Σ costed-line cost for that receipt.
- Profit / Margin: shown only when the receipt is **fully costed**
  (`uncosted_lines == 0`); otherwise `—` with a small "partly costed" amber dot
  (tooltip: "X of Y lines have no cost").
- Margin color scale matches items-sold (green ≥ threshold → amber → red).

**Daily tab** — add `Cost`, `Profit`, `Margin` after `Total sales`:
- Cost: Σ costed-line cost that day.
- Profit / Margin: computed on that day's **fully-costed receipts** subset
  (profit = costed_sales − cost; margin = profit / costed_sales).

### 3. Totals footer row
Sticky `<tfoot>` on each table summing numeric columns over the loaded set.
Invoices: Amount, Lines, Cost, Profit. Daily: unique items (blank/—), qty,
receipts, sales, cost, profit. Margin cell shows the blended margin.

## Backend changes

### `get_invoices_list`
Replace the correlated `lines_count` subquery with one set-based CTE aggregating
`HISTORIC_RECEIPT_CONTENTS c LEFT JOIN ITEMS i LEFT JOIN CURRENCY cu` grouped by
RCPT_ID, yielding per receipt:
- `lines_count` = COUNT(*)
- `total_qty` = Σ ITM_QUANTITY
- `cost` = Σ (ITM_QUANTITY × unit_cost) where unit_cost > 0
- `uncosted_lines` = count of lines with unit_cost 0/NULL

New row fields: `total_qty`, `cost`, `uncosted_lines`. Profit/margin derived
client-side (keeps money math in one place, honors the fully-costed rule).

### `get_daily_items_summary`
Add per-day: `cost` (Σ costed line cost), `costed_sales` (Σ RCPT_AMOUNT of
fully-costed receipts that day), `costed_receipts`. Compute via a receipt-level
CTE (per-receipt uncosted flag) then aggregate to day. Profit/margin derived
client-side.

Both queries keep the `@ttl_cache` pattern if the originals use it, keep the
30s query timeout, and remain single-round-trip (no per-row correlated subqueries).

## Frontend changes (`invoices.js`, `invoices.html`)

- Add KPI strip markup (hidden until first load) + a `renderKpis(invoiceRows)` fn.
- Extend `renderInvoices` / `renderDailyItems` with the new columns + `<tfoot>`.
- Add `marginClass(m)` helper (port the items-sold thresholds).
- Add `fullyCosted` / partly-costed marker rendering.
- Recompute KPIs + footers inside `runAll` after both datasets load.

## Non-goals (YAGNI)

- No richer line-item modal (not requested).
- No server-side aggregate endpoint — client sums the already-loaded rows.
- No changes to filters, deep-linking, or the daily-detail / invoice-detail modals.
- No schema or POS-write changes (POS stays read-only).

## Testing

- Unit-ish: verify the new SQL returns expected fields against the POS DB
  (`db_test.py`-style smoke via the venv python + a scratch script).
- Manual: run the app, load Yesterday and This Month ranges, confirm KPI strip,
  columns, footers, margin colors, and the partly-costed markers render and
  reconcile (invoice total sales == daily total sales).
- Regression: existing modals still open; deep-link `?item_code=` still works.
