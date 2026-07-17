# Supplier Reorder — Design Spec

Date: 2026-07-14
Status: Approved (brainstorm), pending implementation plan

## Problem

The owner has two supplier master price lists (Box4Less, Nice Food — Excel files
compiled by hand from historical invoices) but no way to connect them to what's
actually running low in the shop. Deciding what to reorder, how much, and from
which supplier is currently manual: cross-referencing a spreadsheet against
memory of what's selling.

The app already has everything needed to know **what** needs reordering and
**how much** — `helpers_stock.py`'s `stock_analytics()` computes `needs_reorder`
and `reorder_qty` per tracked `StockItem` from the local stock ledger, and this
already powers the `/stock` page. What's missing is supplier **pricing** and a
workflow to turn "these items are low" into "here's what to order from whom, and
what it costs."

## Goals

- Import both supplier price lists into the local DB as a queryable, editable
  catalog (not static spreadsheets).
- Link supplier catalog items to the existing tracked `StockItem`s so reorder
  suggestions carry a price and a cheapest-supplier recommendation.
- One page: shows what needs reordering now (qty + cost + supplier), lets the
  owner adjust quantities/supplier choice, and lets them browse/add from the
  full two-supplier catalog (including items not currently tracked as stock).
- Produce an exportable order list (per supplier) to send out.

## Non-goals (this phase)

- No persisted "order" entity / order history / order status tracking — export
  is the end of the app's involvement, per the owner's explicit choice.
- No recurring/automatic re-sync from the xlsx files — this is a one-time
  import; all price maintenance after that happens in-app.
- No support for suppliers beyond these two (though the data model doesn't
  hard-code a count of 2).
- No POS-side stock reads (per existing project rule: POS stock field is
  unusable and must never be read/written).
- Doesn't touch or fix `reorder_radar.py` (existing velocity/anomaly report,
  including its known SQL bug at line 356-358) — that page answers a different
  question (what's moving fast catalog-wide) and stays as-is, unrelated to
  this feature.

## Data model (`models.py`)

Two new tables, following the existing `StockItem`/`StockEvent` style (integer
cents, `active` soft-delete flag, `created_at`):

```python
class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class SupplierItem(db.Model):
    __tablename__ = "supplier_items"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(128), nullable=False, default="")   # e.g. "BEER" — display grouping only
    format_label = db.Column(db.String(64), nullable=False, default="")  # e.g. "case of 24"
    case_price_usd_cents = db.Column(db.Integer, nullable=True)
    unit_price_usd_cents = db.Column(db.Integer, nullable=False)
    source_ref = db.Column(db.String(64), nullable=True)    # invoice # / "POS 13-May"
    source_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    itm_code = db.Column(db.String(128), nullable=True, index=True)  # set once matched to a StockItem
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

Prices are stored in **USD cents** (the source data's native currency — both
xlsx files derive their LBP column from a rate cell, so USD is the actual
source of truth). LBP display, where needed, is computed at render time via
`config.USD_EXCHANGE_RATE`, matching how `cost_coverage`/`invoices` already
convert cost — no stale LBP snapshot stored.

`itm_code` is a loose reference (string, like `StockItem.itm_code`), not a
foreign key to `StockItem.id` — consistent with `StockItemAlias`'s existing
pattern of keying by the POS item code rather than a hard FK, since a
`StockItem` can be deactivated/recreated independently.

## One-time import

A standalone script, `import_supplier_catalog.py` (same style as `reset_db.py` —
run manually with `python import_supplier_catalog.py <box4less.xlsx>
<nicefood.xlsx>`, not part of the web app):

- Opens each workbook with `openpyxl` (new dependency — not currently in
  `requirements.txt`).
- Reads the first worksheet positionally: skips the rate-cell row and title
  row, finds the header row (col A == "Item"), then walks rows. A row where
  columns B/C (format/case price) are both empty is a **category header**
  (e.g. "BEER") — remembered and applied to subsequent items until the next
  category row. A row with a value in column A and a unit price in column D is
  an **item row**.
- Creates one `Supplier` row per file (name derived from the sheet title, e.g.
  "Box4Less", "Nice Food") and one `SupplierItem` per item row.
- Idempotent by `(supplier_id, name)`: re-running updates existing rows rather
  than duplicating (safe if the owner needs to re-run after fixing a parse
  issue, even though recurring sync isn't a supported workflow).
- Prints a summary (rows imported per supplier, per category) for manual
  sanity-checking against the known counts (75 for Box4Less, 101 for Nice
  Food).

## Matching flow

After import, a review screen (`GET /supplier-reorder/match`) lists every
`SupplierItem` with `itm_code IS NULL`, alongside the top fuzzy-matched
candidate from the **tracked `StockItem` set only** (not the full POS catalog
— reusing `rank_match()` from `helpers_invoice_match.py`, scored against
`{itm_code, title, subgroup}` built from `StockItem.query.filter_by(active=True)`).

- Owner confirms a suggested match, picks a different `StockItem` from a
  search box, or marks "no match" (expected for most Nice Food spirits/mixers/
  groceries — they simply remain unlinked and only show up in the catalog
  browser, not in reorder suggestions).
- Confirming writes `itm_code` directly onto the `SupplierItem` row — no
  separate alias table needed here, since each `SupplierItem` is a stable
  catalog row (not a repeating raw-OCR string like `StockItemAlias` handles).
- This screen is reachable any time (not just post-import) via the KPI strip's
  "N unmatched" link on the main page, so newly-tracked `StockItem`s or newly
  added `SupplierItem`s can be linked later.

## Supplier Reorder page

New blueprint `routes/supplier_reorder.py` (`supplier_reorder_bp`), single
page at `GET /supplier-reorder`, template `templates/supplier_reorder.html`.
Mobile-first single scrolling layout (Option A from the mockup review):

**KPI strip** — items needing reorder, estimated total cost (sum of cheaper-
supplier line totals), unmatched `SupplierItem` count (links to the matching
screen).

**Reorder Now** — one card per `StockItem` where `stock_analytics().
needs_reorder` is true (identical logic already live on `/stock` — reused, not
reimplemented) AND at least one active `SupplierItem` is matched to it.
`StockItem`s needing reorder with **no** matched supplier item still show, but
flagged "no supplier price — match it" instead of a price, linking to the
matching screen. Each card:
- Current stock, days-of-cover (from existing `stock_analytics` fields).
- Cheapest active matched `SupplierItem`'s unit price, with any other
  supplier's price for the same `StockItem` shown struck through for
  comparison.
- A quantity input pre-filled with `reorder_qty`, editable.
- A supplier toggle if more than one is matched (defaults to cheapest).
- Line total (qty × chosen supplier's unit price).

**Browse Full Catalog** — search box + category filter over all active
`SupplierItem`s (matched or not), grouped by category, both suppliers' prices
shown side by side when both carry a name-matching item (same `itm_code`, or
close text match for unlinked items — display-only comparison, doesn't require
a stored link). Selecting an item here with a quantity adds it to the same
running order as the Reorder Now section, for ad-hoc additions.

**Sticky bottom bar** — running total per supplier from all picks (Reorder Now
+ Browse Catalog), "Export Orders" button.

**Export** (`POST /api/supplier-reorder/export`, body = the picked lines: item
id, qty, chosen supplier) returns CSV (reusing the `cost_coverage.py`
csv/`Response` pattern): item, qty, unit price, line total, per-supplier
order total. Nothing is persisted — this is a generate-and-download action.

**In-app editing** — small forms (likely a modal or a dedicated `/supplier-
reorder/catalog` admin view) to add a new `SupplierItem`, edit price/notes/
category on an existing one, or deactivate one. Same page also exposes
add/edit for `Supplier` itself (name, active), though only 2 rows are expected
initially.

## API surface (draft — finalized in the implementation plan)

- `GET /supplier-reorder` — page
- `GET /api/supplier-reorder/reorder-now` — JSON: reorder cards (joins
  `StockItem` + `stock_analytics` + matched `SupplierItem`s)
- `GET /api/supplier-reorder/catalog` — JSON: searchable/filterable full
  catalog, paginated
- `POST /api/supplier-reorder/item` / `PUT .../item/<id>` / `POST
  .../item/<id>/deactivate` — catalog CRUD
- `GET /supplier-reorder/match`, `POST /api/supplier-reorder/match` — matching
  review screen + confirm action
- `POST /api/supplier-reorder/export` — CSV/text generation from picked lines

## Relationship to existing features

- **`reorder_radar`**: unrelated, untouched. It's a POS-wide velocity/anomaly
  signal with no cost or supplier concept; this feature is scoped to the
  ~50-70 tracked `StockItem`s plus the two-supplier catalog. They can coexist
  as two different lenses (`reorder_radar` = "what's moving," this = "what's
  low and what it costs to restock").
- **`/stock`**: source of truth for `needs_reorder`/`reorder_qty` — reused via
  `helpers_stock.stock_analytics()`, not duplicated.
- **Invoice-OCR receiving (`/stock/receive`)**: unrelated on the input side
  (that flow captures a *paid* invoice after the fact); it does share the
  `rank_match()` fuzzy-matching helper, reused here for a different pairing
  (supplier catalog → StockItem instead of OCR text → StockItem).

## Deployment notes

- **New dependency**: `openpyxl` must be added to `requirements.txt` (only
  needed for the one-time import script; the live app doesn't import xlsx
  files at runtime). Per `CLAUDE.md`, this means `pip install -r
  requirements.txt` must be re-run in the server venv after deploying — a
  missing dep there would crash the whole app on next restart, not just this
  feature, so this step is not optional.
- **New tables won't auto-create in production as-is**: `main.py` currently
  only calls `db.create_all()` inside `if __name__ == "__main__":`, which
  waitress skips (it imports `main.app` directly). Only column-level
  migrations run at import time, via `_ensure_schema_migrations()`
  (`main.py:66-85`). Since `db.create_all()` is additive and safe to call
  every time (it never drops/alters existing tables), this feature's plan
  includes moving/adding a `db.create_all()` call into that same
  import-time-safe path so new tables (here, and for any future model) get
  created automatically on server restart after `git pull` — without needing
  to run `reset_db.py` (which does `drop_all()` first and would wipe existing
  data).
- **Data transfer to production**: the two xlsx files live in the owner's
  local Downloads folder, not in the repo (kept out of git — they're
  business-sensitive supplier pricing data, and the repo's git history is
  already flagged for accidentally-committed secrets in `CLAUDE.md`). The
  owner will need to copy the two files to the server and run
  `import_supplier_catalog.py` there once too, since the production SQLite DB
  (`instance/checkout.db` on the server) is separate from the local dev one
  (`instance/` is gitignored).

## Testing / verification

No test suite exists in this project (per `CLAUDE.md`); verification is
manual, consistent with how `cost_coverage` and `stock` were built:
- Run `import_supplier_catalog.py` against a local copy of the DB, confirm
  row counts match the known totals (75 / 101) and spot-check a few parsed
  prices against the source spreadsheet.
- Walk the matching screen for a handful of items with obvious matches (e.g.
  "Almaza Can 33cl") and confirm the suggested `StockItem` is correct.
- Load `/supplier-reorder` in the browser preview, confirm the Reorder Now
  list matches what `/stock` currently flags as needing reorder, confirm
  price math (qty × unit price = line total, sums roll up correctly per
  supplier), and confirm the cheaper-supplier logic picks correctly for an
  item both suppliers carry.
- Exercise the CSV export and confirm it opens cleanly and totals match the
  page.
