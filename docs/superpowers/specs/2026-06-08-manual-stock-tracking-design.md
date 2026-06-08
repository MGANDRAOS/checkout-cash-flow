# Manual Stock Tracking — Design (Phase 1)

**Date:** 2026-06-08
**Status:** Approved
**Author:** brainstorming session

## Problem

The shop does a manual physical inventory check every day. There is no way in the
app to record stock-on-hand for an item and watch it draw down as the item sells.
The POS (MSSQL) cannot be used for stock: the user cannot enter stock there and its
stock field is always negative — so it must **never** be read or written for stock.

The owner wants to:
1. Hand-enter the on-hand quantity for ~50–70 important items today, and keep adding
   more items by hand week to week.
2. See live stock draw down automatically from the sales the app already reads from POS
   (e.g. Almaza 330 starts at 22, 4 sell today → shows 18).
3. Get alerts for near-out-of-stock and out-of-stock items.

## Scope & phasing

This is the first of two phases. Both ship back-to-back on a shared data model.

- **Phase 1 (this spec):** manual stock tracking — add items, set counts, live
  deduction from POS sales, per-item alerts.
- **Phase 2 (separate spec):** supplier-invoice OCR receiving — upload an invoice →
  Claude vision extracts line items → match to POS items → add `receive` events to
  stock. The data model below is built so Phase 2 slots in with **no migration**.

The supplier-invoice OCR feature was prototyped in a different clone and is **not**
present in this repository (verified across all local/remote branches, worktrees, and
reflog). Phase 2 rebuilds the stock-relevant slice of it natively here.

## Key decisions (from brainstorming)

- **Baseline + deduction model.** Entering a count is a baseline; live stock is that
  baseline minus units sold since.
- **Baseline = start of business day.** A count entered "today" deducts *all* of today's
  POS sales and every day after. Uses the **08:00** business-day boundary
  (`biz_date_range_8h`) — the same one the dashboard's daily sales use.
- **Per-item alert threshold with a tunable default** (`STOCK_DEFAULT_THRESHOLD`, default 5).
- **Restock = "Set count" (overwrite)** in Phase 1. Phase 2 adds invoice-driven
  `receive` deltas. Both are just events in the ledger.
- **Derived/live-compute (not stored balance).** Live quantity is always a pure function
  of the ledger + real POS sales, so it cannot drift and is self-healing.

## Data model (local SQLite, `models.py`)

All new tables live in the local SQLite DB alongside envelopes/payables. POS MSSQL stays
strictly read-only and is never touched for stock.

### `StockItem` — registry of tracked items

| Field | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `itm_code` | String(128), unique, indexed | POS item code |
| `title` | String(255) | cached POS title snapshot (render list without a POS hit) |
| `subgroup` | String(255) | cached subgroup name for display/grouping |
| `alert_threshold` | Integer | near-out-of-stock cutoff; defaults from setting |
| `active` | Boolean, default True | soft stop-tracking |
| `created_at` | DateTime | |

### `StockEvent` — the ledger

| Field | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `stock_item_id` | Integer FK → `StockItem.id`, indexed | |
| `event_type` | String(16) | `count` (absolute) \| `receive` (delta) |
| `qty` | Float | absolute for `count`, +delta for `receive`. Float allows weighed goods |
| `event_date` | Date, indexed | business day the event is "as of"; deduction anchors here |
| `source` | String(16) | `manual` \| `invoice` |
| `invoice_id` | Integer, nullable | **Phase 2 seam** — links a `receive` to a supplier invoice |
| `note` | String(255), nullable | |
| `created_at` | DateTime | tie-breaker for same-day event ordering |

### Setting

`STOCK_DEFAULT_THRESHOLD` (default `"5"`) stored via the existing `AppSetting` /
`get_setting` / `set_setting`.

## Live stock computation

For one tracked item:

1. **Latest count** `(Q0, D0)` = the `count` event with the greatest `event_date`,
   tie-broken by greatest `created_at`.
2. **Receives after the count** `R` = sum of `receive.qty` where
   `event_date > D0` **OR** (`event_date == D0` **AND** `created_at > count.created_at`).
   (Phase 1: always 0.)
3. **Net units sold since the count** `S` = `SUM(ITM_QUANTITY)` from POS for this
   `itm_code` where `RCPT_DATE >= biz_date_range_8h(D0).start`. Net (includes negatives)
   so returns add stock back.
4. **Live** = `Q0 + R − S`.

**Status** (per item, given `live` and `threshold`):
- `live <= 0` → **Out**
- `0 < live <= threshold` → **Low**
- else → **OK**

### Batched POS query (performance-critical)

All tracked items resolve their sales in **one** POS round-trip, not one query per item
(the landing page already risks thread-pool exhaustion / 502s per CLAUDE.md). The query
takes a list of `(itm_code, window_start)` pairs (each item has its own `D0`), builds a
`VALUES` table, joins `HISTORIC_RECEIPT` + `HISTORIC_RECEIPT_CONTENTS`, and returns
`SUM(ITM_QUANTITY)` grouped by `itm_code` where `RCPT_DATE >= window_start`. Parameters
are bound positionally (no string interpolation of values).

Wrapped in `ttl_cache` (~30–60s) keyed on the sorted `(code, start)` pairs so rapid
reloads and the alerts badge share one result. On query failure/timeout the page degrades
gracefully: it shows the baseline (`Q0 + R`) with a "live sales unavailable" flag rather
than returning a 502.

## Modules & routes

### `helpers_stock.py` (new)
Pure POS-read + compute, no Flask, no local-DB writes:
- `units_sold_since(pairs) -> dict[itm_code, float]` — the batched, cached POS query.
- `compute_live(stock_item, events, sold) -> {live, status, q0, d0, receives, sold}` —
  pure function over already-loaded ledger rows + the sold map.

Local SQLite CRUD lives in the route via `models` (consistent with `main.py`'s style for
closings/payables) — no separate data-access layer.

### `routes/stock.py` (new blueprint `stock_bp`)
| Method + path | Purpose |
|---|---|
| `GET /stock` | render `stock.html` |
| `GET /api/stock/subgroups` | subgroup filter options (reuse `helpers_items.list_subgroups`) |
| `GET /api/stock/search?q=&subgroup=` | search POS catalog for items to add (reuse `helpers_items.list_items`) |
| `GET /api/stock/list` | tracked items with live qty + status (batched deduction); Out/Low sorted first |
| `POST /api/stock/add` | `{itm_code, qty, threshold?}` → create `StockItem` (cache title/subgroup from POS) + initial `count` event (today, `manual`) |
| `POST /api/stock/set-count` | `{stock_item_id, qty}` → new `count` event dated today (recount / overwrite restock) |
| `POST /api/stock/set-threshold` | `{stock_item_id, threshold}` |
| `POST /api/stock/remove` | `{stock_item_id}` → soft-delete (`active=False`) |
| `GET /api/stock/alerts` | Low/Out items only (dashboard badge / alerts panel) |

Auth is automatic via the global `@app.before_request` login guard — no decorator needed.

Registered in `main.py` next to the other blueprints.

### Templates
- `templates/stock.html` extends `base.html` (block `content`):
  - **Add panel:** search box + subgroup filter → results with an "Add" action and a qty
    input (plus optional threshold).
  - **Tracked table:** item, subgroup, big color-coded live qty, status badge
    (OK/Low/Out), inline-editable threshold, "Set count" action, remove. Out/Low sorted to
    the top. An alerts summary banner ("3 low, 1 out").
  - Mobile-friendly (cards on small screens) — it's a phone-on-the-floor daily task.
- Sidebar nav link added in `base.html` ("Stock", with a Bootstrap icon), guarded so its
  active state doesn't collide with `/` other routes.

## Migration

Additive only. `db.create_all()` (the existing `reset_db.py` / app-startup path) creates
the two new tables; no existing table or data is touched. No destructive migration.

## Testing

- **Models:** create `StockItem` + `StockEvent`, FK relationship, defaults.
- **Live math (`compute_live`):** count-only (Phase 1) → `Q0 − S`; status thresholds
  (Out/Low/OK boundaries); net-of-returns (negative qty adds back); receive events
  (forward-compat) → `Q0 + R − S`; same-day count-then-receive ordering via `created_at`.
- **Batched query shape:** unit-test the pair→params/SQL builder with a fake cursor (no
  live POS), asserting positional binding and per-item window filtering.
- **Routes:** add → list → set-count → set-threshold → remove happy paths against an
  in-memory SQLite DB with the POS helper mocked; alerts endpoint returns only Low/Out.

## Out of scope (Phase 2)

Invoice upload, OCR (Claude vision), line-item parsing, item matching, `receive` events
from invoices, supplier/cost data. The `event_type='receive'` path and the nullable
`invoice_id` field are the ready seams — Phase 2 writes to them with no schema change.
