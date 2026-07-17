# Supplier Reorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the two supplier price-list spreadsheets into a local catalog, link catalog items to tracked stock items, and ship a "Supplier Reorder" page that shows what needs restocking, at what price, from which supplier, with an exportable order list.

**Architecture:** Two new SQLAlchemy models (`Supplier`, `SupplierItem`) hold the imported price catalog. A one-time standalone script parses both xlsx files into those tables. Reorder quantities are NOT reimplemented — `helpers_stock.stock_analytics()` (already live on `/stock`) is reused as-is; this feature only adds price/supplier data on top via a new `helpers_supplier_reorder.py`. A single mobile-first page (`/supplier-reorder`) renders a KPI strip, a "Reorder Now" worklist, and a "Browse Full Catalog" search, sharing one client-side "picked order" state with a sticky per-supplier total bar and CSV export. A separate small page (`/supplier-reorder/match`) lets the owner link catalog rows to tracked `StockItem`s via the existing fuzzy-match helper.

**Tech Stack:** Flask blueprint + Jinja2 template + vanilla JS (no framework — matches `cost_coverage`/`stock` conventions), Flask-SQLAlchemy models, `openpyxl` for the one-time import (new dependency), plain CSS classes layered on the existing `static/css/items_sold.css` (`is-`) design system.

**Correction (added after Task 1's code review):** `CLAUDE.md`'s "no test suite" claim is stale — a real, git-tracked `pytest` suite exists at `tests/` (109 passing tests as of this writing: `conftest.py` + ~15 `test_*.py` files covering models, helpers, and routes). Every remaining task below (2 onward) should add tests under `tests/`, following the two established conventions found in that directory:
- **Model/DB-backed helper tests**: use `tests/conftest.py`'s `app` fixture (in-memory SQLite, `db.create_all()` inside `app_context()`) — see `tests/test_models_stock.py` for the pattern.
- **Route tests**: define a local `client` fixture in the test file that registers only the blueprint under test, and `unittest.mock.patch` the underlying helper function rather than hitting a real DB or POS — see `tests/test_routes_cost_coverage.py` for the pattern.
- No JS test framework exists in this repo — front-end `static/js/*.js` tasks (8, 9) stay manually/browser-verified, consistent with how `stock.js`/`cost_coverage.js` are handled.

The manual verification steps written into each task below are still valid and should still be run — they just no longer replace automated tests, they supplement them. (Task 1 itself shipped without tests before this was caught; a small follow-up test file for `Supplier`/`SupplierItem` was added retroactively.)

---

### Task 1: Data model + production table auto-creation fix

**Files:**
- Modify: `models.py` (append after `StockItemAlias`, ~line 139)
- Modify: `main.py:66-85` (`_ensure_schema_migrations` block)

- [ ] **Step 1: Add the `Supplier` and `SupplierItem` models**

Append to `models.py`:

```python
class Supplier(db.Model):
    """A goods supplier whose price catalog is imported/maintained locally."""
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    items = db.relationship("SupplierItem", backref="supplier",
                            cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<Supplier {self.name}>"


class SupplierItem(db.Model):
    """One catalog line from a supplier's price list.

    Prices are USD cents (the source spreadsheets' native currency; LBP is
    derived at render time via config.USD_EXCHANGE_RATE, not stored). itm_code
    links to StockItem.itm_code once matched via the /supplier-reorder/match
    screen; NULL means unmatched (catalog-only, not tied to tracked stock).
    """
    __tablename__ = "supplier_items"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(128), nullable=False, default="")
    format_label = db.Column(db.String(64), nullable=False, default="")
    case_price_usd_cents = db.Column(db.Integer, nullable=True)
    unit_price_usd_cents = db.Column(db.Integer, nullable=False)
    source_ref = db.Column(db.String(64), nullable=True)
    source_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    itm_code = db.Column(db.String(128), nullable=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SupplierItem {self.name!r} supplier={self.supplier_id} ${self.unit_price_usd_cents/100:.2f}>"
```

- [ ] **Step 2: Make new tables auto-create on server restart (not just `python main.py`)**

`main.py` currently only calls `db.create_all()` inside `if __name__ == "__main__":` (line 385-388), which the production `run_waitress.py` never triggers (it does `from main import app`, not `python main.py`). Only column-level ALTERs run at import time via `_ensure_schema_migrations()`. Since `create_all()` is additive and safe to call unconditionally (it only creates tables that don't yet exist; it never drops or alters), move it into the same import-time-safe block so this feature's new tables — and any future model's — get created automatically after `git pull` + restart, without needing `reset_db.py` (which does `drop_all()` first and would wipe existing data).

In `main.py`, change:

```python
with app.app_context():
    _ensure_schema_migrations()
```

to:

```python
with app.app_context():
    db.create_all()  # additive only — creates any new tables; never touches existing ones
    _ensure_schema_migrations()
```

- [ ] **Step 3: Verify — models import cleanly and tables are created**

Run:

```bash
cd "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow"
"./.venv/Scripts/python.exe" -c "
from main import app, db
from models import Supplier, SupplierItem
with app.app_context():
    s = Supplier(name='__verify_test__', active=True)
    db.session.add(s)
    db.session.flush()
    it = SupplierItem(supplier_id=s.id, name='Test Item', unit_price_usd_cents=150)
    db.session.add(it)
    db.session.commit()
    assert SupplierItem.query.filter_by(name='Test Item').first().unit_price_usd_cents == 150
    db.session.delete(it)
    db.session.delete(s)
    db.session.commit()
    print('OK: Supplier/SupplierItem create/query/delete round-trip works')
"
```

Expected: `OK: Supplier/SupplierItem create/query/delete round-trip works`, no traceback. (Note: this needs a local `.env` copied into the repo root per `CLAUDE.md`'s local-dev instructions if one isn't already present, since `config.py` validates required env vars at import time.)

- [ ] **Step 4: Commit**

```bash
git add models.py main.py
git commit -m "feat(supplier-reorder): add Supplier/SupplierItem models, fix prod table auto-create"
```

---

### Task 2: One-time xlsx import script

**Files:**
- Modify: `requirements.txt`
- Create: `import_supplier_catalog.py`

- [ ] **Step 1: Add the new dependency**

In `requirements.txt`, add a line:

```
openpyxl
```

- [ ] **Step 2: Install it locally**

```bash
cd "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow"
"./.venv/Scripts/python.exe" -m pip install -r requirements.txt -q
```

- [ ] **Step 3: Write the import script**

Create `import_supplier_catalog.py`:

```python
"""
One-time import of supplier master price lists (xlsx) into the local DB.

Usage:
    python import_supplier_catalog.py "Box4Less" path\to\box4less.xlsx "Nice Food" path\to\nicefood.xlsx

Each pair is: <supplier name> <xlsx path>. Re-running is idempotent — an
existing (supplier, item name) row is updated in place rather than duplicated,
so a corrected spreadsheet can be safely re-imported.

Expects the first worksheet in this positional column layout (both known
source files match this; header text differs slightly between them, so
columns are read by position, not by header name):
    A: item name (or a category label when B/C/D are all empty)
    B: format / pack size
    C: case price (USD)
    D: unit price (USD)
    E: unit price (LBP) -- ignored, derived from a rate cell, not imported
    F: source invoice / receipt reference
    G: source date (DD/MM/YYYY)
    H: notes
Row 1 is a rate cell, row 2 a title, then a blank row, then a header row
(column A == "Item") before the data starts.
"""
from __future__ import annotations

import sys
from datetime import datetime

import openpyxl

from main import app, db
from models import Supplier, SupplierItem


def _to_cents(value):
    if value is None:
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.date() if hasattr(value, "hour") else value
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_workbook(path):
    """Yield one dict per item row from the first worksheet at `path`."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    category = ""
    header_seen = False
    for row in ws.iter_rows(min_row=1, values_only=True):
        padded = list(row) + [None] * (8 - len(row))
        item, fmt, case_price, unit_price, _lbp, source_ref, source_date, notes = padded[:8]
        if item is None:
            continue
        if not header_seen:
            if isinstance(item, str) and item.strip().lower() == "item":
                header_seen = True
            continue
        if fmt is None and case_price is None and unit_price is None:
            category = str(item).strip()
            continue
        if unit_price is None:
            continue
        yield {
            "name": str(item).strip(),
            "category": category,
            "format_label": str(fmt).strip() if fmt else "",
            "case_price_usd_cents": _to_cents(case_price),
            "unit_price_usd_cents": _to_cents(unit_price),
            "source_ref": str(source_ref).strip() if source_ref else None,
            "source_date": _parse_date(source_date),
            "notes": str(notes).strip() if notes else None,
        }


def import_supplier(name, path):
    supplier = Supplier.query.filter_by(name=name).first()
    if supplier is None:
        supplier = Supplier(name=name, active=True)
        db.session.add(supplier)
        db.session.flush()

    count = 0
    for row in parse_workbook(path):
        existing = SupplierItem.query.filter_by(supplier_id=supplier.id, name=row["name"]).first()
        if existing is None:
            existing = SupplierItem(supplier_id=supplier.id, name=row["name"],
                                    unit_price_usd_cents=row["unit_price_usd_cents"])
            db.session.add(existing)
        existing.category = row["category"]
        existing.format_label = row["format_label"]
        existing.case_price_usd_cents = row["case_price_usd_cents"]
        existing.unit_price_usd_cents = row["unit_price_usd_cents"]
        existing.source_ref = row["source_ref"]
        existing.source_date = row["source_date"]
        existing.notes = row["notes"]
        existing.active = True
        count += 1
    db.session.commit()
    return count


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2 or len(args) % 2 != 0:
        print("Usage: python import_supplier_catalog.py <Supplier Name> <path.xlsx> "
              "[<Supplier Name> <path.xlsx> ...]")
        sys.exit(1)
    with app.app_context():
        db.create_all()
        for i in range(0, len(args), 2):
            supplier_name, path = args[i], args[i + 1]
            n = import_supplier(supplier_name, path)
            print(f"{supplier_name}: {n} items imported from {path}")
```

- [ ] **Step 4: Run it against the two real price lists and verify counts**

```bash
cd "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow"
"./.venv/Scripts/python.exe" import_supplier_catalog.py ^
  "Box4Less" "C:\Users\majd\Downloads\box4less_master_price_list.xlsx" ^
  "Nice Food" "C:\Users\majd\Downloads\nice_food_master_price_list.xlsx"
```

(Use `\` line continuation instead of `^` if running from the Bash tool rather than PowerShell/cmd.)

Expected output:
```
Box4Less: 75 items imported from C:\Users\majd\Downloads\box4less_master_price_list.xlsx
Nice Food: 101 items imported from C:\Users\majd\Downloads\nice_food_master_price_list.xlsx
```

These counts (75, 101) are the known totals from the source spreadsheets — a mismatch means the positional-column parsing broke on that file and needs investigating before moving on.

- [ ] **Step 5: Spot-check a couple of parsed prices**

```bash
"./.venv/Scripts/python.exe" -c "
from main import app
from models import SupplierItem
with app.app_context():
    it = SupplierItem.query.filter_by(name='Almaza Can 33cl').first()
    print(it.name, it.unit_price_usd_cents, it.category, it.supplier.name)
"
```

Expected: a row with `unit_price_usd_cents` around `104` (Box4Less, ~\$1.04/unit) or `92` (Nice Food, ~\$0.92/unit) depending on which supplier matched first — confirm it's in the right ballpark versus the source spreadsheet, not that it's an exact literal (both suppliers carry this item at different prices).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt import_supplier_catalog.py
git commit -m "feat(supplier-reorder): one-time xlsx import script for supplier price catalogs"
```

---

### Task 3: Matching helpers

**Files:**
- Create: `helpers_supplier_reorder.py`

- [ ] **Step 1: Write the matching functions**

Create `helpers_supplier_reorder.py`:

```python
"""Supplier catalog logic: matching to tracked stock, reorder-now, browse, CRUD."""
from __future__ import annotations

from typing import List, Optional

from models import db, StockItem, SupplierItem
from helpers_invoice_match import rank_match


def tracked_catalog() -> List[dict]:
    """Active StockItems as [{code,title,subgroup}], the pool matching is scored against."""
    return [{"code": s.itm_code, "title": s.title, "subgroup": s.subgroup}
            for s in StockItem.query.filter_by(active=True).all()]


def unmatched_items() -> List[dict]:
    """Active SupplierItems with no itm_code yet, each with top fuzzy-match candidates."""
    catalog = tracked_catalog()
    items = (SupplierItem.query
             .filter_by(active=True, itm_code=None)
             .order_by(SupplierItem.category, SupplierItem.name)
             .all())
    out = []
    for item in items:
        out.append({
            "id": item.id, "name": item.name, "supplier": item.supplier.name,
            "category": item.category, "unit_price_usd_cents": item.unit_price_usd_cents,
            "candidates": rank_match(item.name, catalog, limit=5),
        })
    return out


def set_match(supplier_item_id: int, itm_code: Optional[str]) -> bool:
    """Confirm (or clear, with itm_code=None) a SupplierItem -> StockItem link."""
    item = db.session.get(SupplierItem, supplier_item_id)
    if item is None:
        return False
    item.itm_code = itm_code or None
    db.session.commit()
    return True
```

- [ ] **Step 2: Verify against the imported catalog**

```bash
"./.venv/Scripts/python.exe" -c "
from main import app
from helpers_supplier_reorder import unmatched_items
with app.app_context():
    rows = unmatched_items()
    print('unmatched:', len(rows))
    if rows:
        r = rows[0]
        print('example:', r['name'], '->', [c['title'] for c in r['candidates'][:3]])
"
```

Expected: no traceback, prints an unmatched count (likely close to 176 if no `StockItem`s exist locally yet, since nothing can match) and, if any tracked `StockItem`s exist locally, at least some candidate suggestions.

- [ ] **Step 3: Commit**

```bash
git add helpers_supplier_reorder.py
git commit -m "feat(supplier-reorder): fuzzy-matching helpers for catalog -> stock linking"
```

---

### Task 4: Matching review page + blueprint registration

**Files:**
- Create: `routes/supplier_reorder.py`
- Create: `templates/supplier_reorder_match.html`
- Create: `static/js/supplier_reorder_match.js`
- Create: `static/css/supplier_reorder.css`
- Modify: `main.py` (imports + `register_blueprint`)

- [ ] **Step 1: Create the blueprint with the matching endpoints**

Create `routes/supplier_reorder.py`:

```python
from flask import Blueprint, render_template, jsonify, request

from config import CURRENCY
from helpers_supplier_reorder import unmatched_items, set_match

supplier_reorder_bp = Blueprint("supplier_reorder", __name__)


def _body():
    return request.get_json(silent=True) or request.form


@supplier_reorder_bp.get("/supplier-reorder/match")
def supplier_reorder_match_page():
    return render_template("supplier_reorder_match.html")


@supplier_reorder_bp.get("/api/supplier-reorder/match/unmatched")
def api_supplier_reorder_unmatched():
    return jsonify({"items": unmatched_items()})


@supplier_reorder_bp.post("/api/supplier-reorder/match/confirm")
def api_supplier_reorder_confirm():
    data = _body()
    try:
        supplier_item_id = int(data.get("supplier_item_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "supplier_item_id required"}), 400
    itm_code = (str(data.get("itm_code") or "")).strip() or None
    if not set_match(supplier_item_id, itm_code):
        return jsonify({"ok": False, "error": "item not found"}), 404
    return jsonify({"ok": True})
```

- [ ] **Step 2: Register the blueprint**

In `main.py`, add near the other route imports (around line 39-43):

```python
from routes.supplier_reorder import supplier_reorder_bp
```

And near the other `register_blueprint` calls (around line 371):

```python
app.register_blueprint(supplier_reorder_bp)
```

- [ ] **Step 3: Create the page-specific CSS**

Create `static/css/supplier_reorder.css`:

```css
/* supplier_reorder.css — layers on static/css/items_sold.css (is- base tokens) */

.sup-reorder-list, .sup-catalog-list, .sup-match-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.sup-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 10px 12px;
}

.sup-card__top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.sup-card__title {
  font-weight: 600;
}

.sup-card__meta {
  color: var(--text-3);
  font-size: 0.8rem;
}

.sup-card__price {
  text-align: right;
}

.sup-card__price-alt {
  text-decoration: line-through;
  color: var(--text-3);
  font-size: 0.8rem;
  margin-left: 4px;
}

.sup-card__row {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
  margin-top: 8px;
}

.sup-qty-input {
  width: 70px;
  padding: 4px 6px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
}

.sup-line-total {
  font-weight: 600;
}

.sup-order-bar {
  position: sticky;
  bottom: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 10px 12px;
  margin-top: 12px;
}

.sup-order-totals {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 0.85rem;
  color: var(--text-2);
  margin-bottom: 8px;
}

.sup-search {
  width: 100%;
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
}

.sup-match-row {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 8px 10px;
}

.sup-match-name { flex: 1; }
.sup-match-supplier { color: var(--text-3); font-size: 0.8rem; margin-left: 6px; }

.sup-add-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 10px 12px;
  margin: 8px 0 16px;
}

.sup-add-panel input, .sup-add-panel select {
  padding: 6px 8px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
}
```

- [ ] **Step 4: Create the matching page template**

Create `templates/supplier_reorder_match.html`:

```html
{% extends "base.html" %}
{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/items_sold.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/supplier_reorder.css') }}">
{% endblock %}
{% block content %}
<div id="supplierMatch" class="is-page">
  <div class="is-header">
    <div class="is-title-block">
      <h1>Match Supplier Items</h1>
      <p class="is-hint">Link each supplier catalog item to a tracked stock item, or leave it unmatched if it's not one you track.</p>
    </div>
  </div>
  <div id="supMatchList" class="sup-match-list"></div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/supplier_reorder_match.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create the matching page JS**

Create `static/js/supplier_reorder_match.js`:

```js
(() => {
  const API_LIST = "/api/supplier-reorder/match/unmatched";
  const API_CONFIRM = "/api/supplier-reorder/match/confirm";
  const list = document.getElementById("supMatchList");

  function esc(s) {
    return (s ?? "").toString().replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function rowHtml(item) {
    const candidates = item.candidates.map(c =>
      `<option value="${esc(c.code)}">${esc(c.title)} (${Math.round(c.score * 100)}%)</option>`
    ).join("");
    return `
      <div class="sup-match-row" data-id="${item.id}">
        <div class="sup-match-name">${esc(item.name)}<span class="sup-match-supplier">${esc(item.supplier)}</span></div>
        <select class="sup-match-select">
          <option value="">-- no match --</option>
          ${candidates}
        </select>
        <button class="sup-match-confirm" type="button">Confirm</button>
      </div>`;
  }

  async function load() {
    const r = await fetch(API_LIST);
    const body = await r.json();
    list.innerHTML = body.items.map(rowHtml).join("") || "<p>No unmatched items.</p>";
  }

  list.addEventListener("click", async (e) => {
    const btn = e.target.closest(".sup-match-confirm");
    if (!btn) return;
    const row = btn.closest(".sup-match-row");
    const id = row.dataset.id;
    const itm_code = row.querySelector(".sup-match-select").value;
    await fetch(API_CONFIRM, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ supplier_item_id: Number(id), itm_code }),
    });
    row.remove();
  });

  document.addEventListener("DOMContentLoaded", load);
})();
```

- [ ] **Step 6: Verify in the browser**

Start the app locally (`"./.venv/Scripts/python.exe" main.py`, or use the `preview_start` tool), navigate to `http://127.0.0.1:5000/supplier-reorder/match`, and confirm:
- The page loads without a console error.
- Unmatched items render as rows with a dropdown of candidate `StockItem`s.
- Picking a candidate and clicking "Confirm" removes that row from the list.
- Re-running the verify snippet from Task 3 Step 2 shows the unmatched count decreased by 1.

- [ ] **Step 7: Commit**

```bash
git add routes/supplier_reorder.py templates/supplier_reorder_match.html static/js/supplier_reorder_match.js static/css/supplier_reorder.css main.py
git commit -m "feat(supplier-reorder): matching review page, blueprint registered"
```

---

### Task 5: Reorder-now helper

**Files:**
- Modify: `helpers_supplier_reorder.py`

- [ ] **Step 1: Add the reorder-now builder**

Append to `helpers_supplier_reorder.py`:

```python
def _cheapest_first(itm_code: str) -> List[SupplierItem]:
    """All active matched SupplierItems for this itm_code, cheapest unit price first."""
    return (SupplierItem.query
            .filter_by(itm_code=itm_code, active=True)
            .order_by(SupplierItem.unit_price_usd_cents.asc())
            .all())


def reorder_now() -> dict:
    """StockItems needing reorder (per helpers_stock.stock_analytics — reused, not
    reimplemented), each priced from its cheapest matched SupplierItem, if any."""
    from models import StockEvent
    from helpers_stock import (
        units_sold_since, compute_live, latest_count, count_window_start, stock_analytics,
    )

    items = StockItem.query.filter_by(active=True).all()
    item_ids = [s.id for s in items]
    events_by_item = {s.id: [] for s in items}
    if item_ids:
        for ev in StockEvent.query.filter(StockEvent.stock_item_id.in_(item_ids)).all():
            events_by_item[ev.stock_item_id].append(ev)

    pairs = []
    for s in items:
        c = latest_count(events_by_item[s.id])
        if c is not None:
            pairs.append((s.itm_code, count_window_start(c)))

    sold_map, live_unavailable = {}, False
    try:
        sold_map = units_sold_since(tuple(sorted(pairs)))
    except Exception:
        live_unavailable = True

    rows = []
    totals_by_supplier_cents = {}
    for s in items:
        events = events_by_item[s.id]
        info = compute_live(events, sold_map.get(s.itm_code, 0.0), s.alert_threshold)
        a = stock_analytics(events, info, s.alert_threshold)
        if not a["needs_reorder"]:
            continue
        candidates = _cheapest_first(s.itm_code)
        options = [{"supplier_id": c.supplier_id, "supplier": c.supplier.name,
                    "unit_price_usd_cents": c.unit_price_usd_cents,
                    "supplier_item_id": c.id} for c in candidates]
        chosen = options[0] if options else None
        line_total_cents = (chosen["unit_price_usd_cents"] * a["reorder_qty"]) if chosen else None
        if chosen and line_total_cents is not None:
            totals_by_supplier_cents[chosen["supplier"]] = (
                totals_by_supplier_cents.get(chosen["supplier"], 0) + line_total_cents
            )
        rows.append({
            "stock_item_id": s.id, "itm_code": s.itm_code, "title": s.title,
            "live": info["live"], "days_cover": a["days_cover"],
            "reorder_qty": a["reorder_qty"], "options": options,
            "chosen_supplier_item_id": chosen["supplier_item_id"] if chosen else None,
            "line_total_cents": line_total_cents,
        })
    rows.sort(key=lambda r: (r["days_cover"] if r["days_cover"] is not None else -1))
    return {
        "items": rows, "live_unavailable": live_unavailable,
        "totals_by_supplier_cents": totals_by_supplier_cents,
        "unpriced_count": sum(1 for r in rows if not r["options"]),
    }
```

- [ ] **Step 2: Verify against `/stock`'s existing reorder count**

```bash
"./.venv/Scripts/python.exe" -c "
from main import app
from helpers_supplier_reorder import reorder_now
with app.app_context():
    result = reorder_now()
    print('needs reorder:', len(result['items']))
    print('unpriced:', result['unpriced_count'])
    print('totals:', result['totals_by_supplier_cents'])
"
```

Expected: no traceback; the `needs reorder` count should match what the `/stock` page currently flags with `needs_reorder: true` (cross-check via `GET /api/stock/list` and counting `needs_reorder === true` entries, or by eye on the `/stock` page).

- [ ] **Step 3: Commit**

```bash
git add helpers_supplier_reorder.py
git commit -m "feat(supplier-reorder): reorder-now builder joining stock_analytics with supplier prices"
```

---

### Task 6: Catalog browse helper

**Files:**
- Modify: `helpers_supplier_reorder.py`

- [ ] **Step 1: Add search/filter and categories helpers**

Append to `helpers_supplier_reorder.py`:

```python
def browse_catalog(q: str = "", category: str = "", page: int = 1, page_size: int = 30) -> dict:
    """Search/filter active SupplierItems across both suppliers, paginated."""
    query = SupplierItem.query.filter_by(active=True)
    if q:
        query = query.filter(SupplierItem.name.ilike(f"%{q.strip()}%"))
    if category:
        query = query.filter_by(category=category)
    total = query.count()
    items = (query.order_by(SupplierItem.category, SupplierItem.name)
             .offset((page - 1) * page_size).limit(page_size).all())
    rows = [{
        "id": it.id, "name": it.name, "category": it.category,
        "format_label": it.format_label, "supplier": it.supplier.name,
        "supplier_id": it.supplier_id, "unit_price_usd_cents": it.unit_price_usd_cents,
        "case_price_usd_cents": it.case_price_usd_cents, "itm_code": it.itm_code,
    } for it in items]
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def list_categories() -> List[str]:
    rows = (db.session.query(SupplierItem.category)
            .filter(SupplierItem.active.is_(True), SupplierItem.category != "")
            .distinct().order_by(SupplierItem.category).all())
    return [r[0] for r in rows]
```

- [ ] **Step 2: Verify**

```bash
"./.venv/Scripts/python.exe" -c "
from main import app
from helpers_supplier_reorder import browse_catalog, list_categories
with app.app_context():
    result = browse_catalog(q='almaza')
    print('almaza matches:', [(r['name'], r['supplier'], r['unit_price_usd_cents']) for r in result['items']])
    print('categories:', list_categories())
"
```

Expected: several "Almaza..." rows from both Box4Less and Nice Food with distinct prices; a non-empty category list including "BEER", "ENERGY DRINKS", etc.

- [ ] **Step 3: Commit**

```bash
git add helpers_supplier_reorder.py
git commit -m "feat(supplier-reorder): catalog search/filter helper"
```

---

### Task 7: Main page routes + template shell + nav link

**Files:**
- Modify: `routes/supplier_reorder.py`
- Create: `templates/supplier_reorder.html`
- Modify: `templates/base.html`

- [ ] **Step 1: Add the page + data routes**

In `routes/supplier_reorder.py`, update the import line and append routes:

```python
from helpers_supplier_reorder import (
    unmatched_items, set_match, reorder_now, browse_catalog, list_categories,
)
from models import Supplier
```

Append:

```python
@supplier_reorder_bp.get("/supplier-reorder")
def supplier_reorder_page():
    return render_template("supplier_reorder.html", currency=CURRENCY)


@supplier_reorder_bp.get("/api/supplier-reorder/reorder-now")
def api_supplier_reorder_now():
    return jsonify(reorder_now())


@supplier_reorder_bp.get("/api/supplier-reorder/catalog")
def api_supplier_reorder_catalog():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    return jsonify(browse_catalog(q=q, category=category, page=page))


@supplier_reorder_bp.get("/api/supplier-reorder/categories")
def api_supplier_reorder_categories():
    return jsonify({"categories": list_categories()})


@supplier_reorder_bp.get("/api/supplier-reorder/suppliers")
def api_supplier_reorder_suppliers():
    rows = Supplier.query.filter_by(active=True).order_by(Supplier.name).all()
    return jsonify({"suppliers": [{"id": s.id, "name": s.name} for s in rows]})
```

- [ ] **Step 2: Create the page template shell**

Create `templates/supplier_reorder.html`:

```html
{% extends "base.html" %}
{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/items_sold.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/supplier_reorder.css') }}">
{% endblock %}
{% block content %}
<div id="supplierReorder" class="is-page" data-currency="{{ currency }}">
  <div class="is-header">
    <div class="is-title-block">
      <h1>Supplier Reorder</h1>
      <p class="is-hint">What needs restocking, from which supplier, and what it costs.</p>
    </div>
    <a href="/supplier-reorder/match" class="is-ghost-btn">
      <i class="bi bi-link-45deg"></i><span id="supUnmatchedLabel">Unmatched items</span>
    </a>
  </div>

  <div class="is-kpi-hero">
    <div class="is-kpi-grid">
      <div class="is-kpi-card">
        <div class="is-kpi-number" id="supKpiCount">&mdash;</div>
        <div class="is-kpi-label">need reorder</div>
      </div>
      <div class="is-kpi-card">
        <div class="is-kpi-number" id="supKpiTotal">&mdash;</div>
        <div class="is-kpi-label">est. total (USD)</div>
      </div>
      <div class="is-kpi-card">
        <div class="is-kpi-number" id="supKpiUnpriced">&mdash;</div>
        <div class="is-kpi-label">no supplier price</div>
      </div>
    </div>
  </div>

  <div class="is-results-bar">
    <div class="is-results-title">Reorder Now</div>
  </div>
  <div id="supReorderList" class="sup-reorder-list"></div>

  <div class="is-results-bar">
    <div class="is-results-title">Browse Full Catalog</div>
  </div>
  <div class="sup-catalog-filters">
    <input id="supCatalogSearch" class="sup-search" type="search" placeholder="Search catalog...">
    <select id="supCatalogCategory" class="sup-search"><option value="">All categories</option></select>
  </div>
  <div id="supCatalogList" class="sup-catalog-list"></div>

  <button id="supAddItemBtn" class="is-ghost-btn" type="button">
    <i class="bi bi-plus-lg"></i><span>Add catalog item</span>
  </button>
  <section id="supAddItemPanel" class="sup-add-panel" hidden>
    <select id="supAddSupplier"></select>
    <input id="supAddName" type="text" placeholder="Item name">
    <input id="supAddCategory" type="text" placeholder="Category">
    <input id="supAddPrice" type="number" step="0.01" min="0" placeholder="Unit price (USD)">
    <button id="supAddSave" class="is-export-btn" type="button">Save</button>
  </section>

  <div id="supOrderBar" class="sup-order-bar">
    <div id="supOrderTotals" class="sup-order-totals"><span>No items picked yet.</span></div>
    <button id="supExportBtn" class="is-export-btn" type="button">
      <i class="bi bi-download"></i><span>Export Orders</span>
    </button>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/supplier_reorder.js') }}"></script>
{% endblock %}
```

- [ ] **Step 3: Add the nav link**

In `templates/base.html`, near the Cost Coverage link (around line 96-99), add:

```html
<a href="/supplier-reorder"
  class="sidebar-link {% if request.path.startswith('/supplier-reorder') %}active{% endif %}">
  <i class="bi bi-truck"></i><span>Supplier Reorder</span>
</a>
```

- [ ] **Step 4: Verify the routes respond**

With the app running locally:

```bash
"./.venv/Scripts/python.exe" -c "
import requests
for path in ['/api/supplier-reorder/reorder-now', '/api/supplier-reorder/catalog?q=beer', '/api/supplier-reorder/categories', '/api/supplier-reorder/suppliers']:
    r = requests.get(f'http://127.0.0.1:5000{path}')
    print(path, r.status_code, len(r.text))
"
```

(This will 302-redirect to `/login` if the session isn't authenticated — in that case, verify via a logged-in browser tab instead: load `/supplier-reorder` and confirm the sidebar shows a "Supplier Reorder" link with a truck icon, and the page renders the KPI strip skeleton with `&mdash;` placeholders and no console errors before the JS from Task 8 exists to populate them.)

- [ ] **Step 5: Commit**

```bash
git add routes/supplier_reorder.py templates/supplier_reorder.html templates/base.html
git commit -m "feat(supplier-reorder): main page routes, template shell, nav link"
```

---

### Task 8: Reorder Now front-end

**Files:**
- Create: `static/js/supplier_reorder.js`

- [ ] **Step 1: Write the JS module — KPI strip, Reorder Now cards, order state scaffold**

Create `static/js/supplier_reorder.js`:

```js
(() => {
  const root = document.getElementById("supplierReorder");

  const el = {
    kpiCount: document.getElementById("supKpiCount"),
    kpiTotal: document.getElementById("supKpiTotal"),
    kpiUnpriced: document.getElementById("supKpiUnpriced"),
    unmatchedLabel: document.getElementById("supUnmatchedLabel"),
    reorderList: document.getElementById("supReorderList"),
    catalogList: document.getElementById("supCatalogList"),
    catalogSearch: document.getElementById("supCatalogSearch"),
    orderTotals: document.getElementById("supOrderTotals"),
    exportBtn: document.getElementById("supExportBtn"),
  };

  const nfUsd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

  // order state: Map<lineKey, {supplier_item_id, supplier, unit_price_usd_cents, qty, name}>
  const order = new Map();

  function esc(s) {
    return (s ?? "").toString().replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function usd(cents) {
    return nfUsd.format((cents || 0) / 100);
  }

  function renderTotals() {
    const bySupplier = new Map();
    for (const line of order.values()) {
      const cents = line.unit_price_usd_cents * line.qty;
      bySupplier.set(line.supplier, (bySupplier.get(line.supplier) || 0) + cents);
    }
    if (bySupplier.size === 0) {
      el.orderTotals.innerHTML = "<span>No items picked yet.</span>";
      return;
    }
    el.orderTotals.innerHTML = [...bySupplier.entries()]
      .map(([supplier, cents]) => `<span>${esc(supplier)}: ${usd(cents)}</span>`)
      .join("");
  }

  function reorderRowHtml(row) {
    const chosen = row.options.find(o => o.supplier_item_id === row.chosen_supplier_item_id);
    const alt = row.options.find(o => o.supplier_item_id !== row.chosen_supplier_item_id);
    const priceHtml = chosen
      ? `<div class="sup-card__title">${esc(chosen.supplier)}</div>
         <div>${usd(chosen.unit_price_usd_cents)}/u${alt ? ` <span class="sup-card__price-alt">${usd(alt.unit_price_usd_cents)}</span>` : ""}</div>`
      : `<div class="sup-card__meta">no supplier price &mdash; <a href="/supplier-reorder/match">match it</a></div>`;
    const supplierSelect = row.options.length > 1
      ? `<select class="sup-supplier-select">
           ${row.options.map(o => `<option value="${o.supplier_item_id}" ${o.supplier_item_id === row.chosen_supplier_item_id ? "selected" : ""}>${esc(o.supplier)} (${usd(o.unit_price_usd_cents)})</option>`).join("")}
         </select>`
      : "";
    return `
      <div class="sup-card" data-stock-item-id="${row.stock_item_id}">
        <div class="sup-card__top">
          <div>
            <div class="sup-card__title">${esc(row.title || row.itm_code)}</div>
            <div class="sup-card__meta">${row.live ?? "?"} left &middot; ${row.days_cover ?? "?"} days cover</div>
          </div>
          <div class="sup-card__price">${priceHtml}</div>
        </div>
        ${chosen ? `
        <div class="sup-card__row">
          ${supplierSelect}
          <input class="sup-qty-input" type="number" min="0" step="1" value="${row.reorder_qty}">
          <div class="sup-line-total">${usd(chosen.unit_price_usd_cents * row.reorder_qty)}</div>
        </div>` : ""}
      </div>`;
  }

  function syncReorderLine(cardEl) {
    const row = cardEl._row;
    const qtyInput = cardEl.querySelector(".sup-qty-input");
    if (!qtyInput) return;
    const select = cardEl.querySelector(".sup-supplier-select");
    const qty = Math.max(0, parseInt(qtyInput.value, 10) || 0);
    const supplierItemId = select ? Number(select.value) : row.chosen_supplier_item_id;
    const chosen = row.options.find(o => o.supplier_item_id === supplierItemId);
    const key = `stock:${row.stock_item_id}`;
    if (qty > 0 && chosen) {
      order.set(key, {
        supplier_item_id: chosen.supplier_item_id, supplier: chosen.supplier,
        unit_price_usd_cents: chosen.unit_price_usd_cents, qty, name: row.title || row.itm_code,
      });
    } else {
      order.delete(key);
    }
    const totalEl = cardEl.querySelector(".sup-line-total");
    if (totalEl && chosen) totalEl.textContent = usd(chosen.unit_price_usd_cents * qty);
    renderTotals();
  }

  async function loadReorderNow() {
    const r = await fetch("/api/supplier-reorder/reorder-now");
    const body = await r.json();
    el.kpiCount.textContent = body.items.length;
    const totalCents = Object.values(body.totals_by_supplier_cents || {}).reduce((a, b) => a + b, 0);
    el.kpiTotal.textContent = usd(totalCents);
    el.kpiUnpriced.textContent = body.unpriced_count;

    el.reorderList.innerHTML = body.items.map(reorderRowHtml).join("") || "<p>Nothing needs reordering right now.</p>";
    [...el.reorderList.children].forEach((cardEl, i) => {
      if (!body.items[i]) return;
      cardEl._row = body.items[i];
      syncReorderLine(cardEl);
    });
  }

  el.reorderList.addEventListener("input", (e) => {
    const card = e.target.closest(".sup-card");
    if (card) syncReorderLine(card);
  });
  el.reorderList.addEventListener("change", (e) => {
    const card = e.target.closest(".sup-card");
    if (card) syncReorderLine(card);
  });

  async function loadUnmatchedCount() {
    const r = await fetch("/api/supplier-reorder/match/unmatched");
    const body = await r.json();
    el.unmatchedLabel.textContent = `${body.items.length} unmatched items`;
  }

  window.SupplierReorder = { esc, usd, renderTotals, order, loadReorderNow, loadUnmatchedCount, el };

  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadUnmatchedCount();
  });
})();
```

Note: this exposes `window.SupplierReorder` deliberately so Task 9 and Task 11 can extend the same module (adding catalog/export/CRUD behavior) by appending to this file without redeclaring `el`, `order`, `esc`, `usd`, `renderTotals`.

- [ ] **Step 2: Verify in the browser**

Load `/supplier-reorder`. Confirm:
- The three KPI numbers populate (not stuck on `&mdash;`).
- The "Reorder Now" section lists a card per item `/stock` currently flags as needing reorder (cross-check the count against `/stock`).
- Editing a quantity input updates that card's line total immediately.
- If an item has two matched suppliers, a dropdown appears and switching it updates the price and line total.

- [ ] **Step 3: Commit**

```bash
git add static/js/supplier_reorder.js
git commit -m "feat(supplier-reorder): Reorder Now front-end (KPIs, cards, qty/supplier sync)"
```

---

### Task 9: Browse Catalog front-end + sticky order bar

**Files:**
- Modify: `static/js/supplier_reorder.js`
- Modify: `static/css/supplier_reorder.css`
- Modify: `templates/supplier_reorder.html` (category `<select>` added above)

- [ ] **Step 1: Append catalog rendering, search, and the picked-order wiring**

Append to `static/js/supplier_reorder.js` (inside the same IIFE, before the final `document.addEventListener("DOMContentLoaded", ...)` block — move that block to the bottom after this addition, calling all three loaders):

```js
  function catalogRowHtml(item) {
    return `
      <div class="sup-card" data-supplier-item-id="${item.id}">
        <div class="sup-card__top">
          <div>
            <div class="sup-card__title">${esc(item.name)}</div>
            <div class="sup-card__meta">${esc(item.supplier)} &middot; ${esc(item.category)}</div>
          </div>
          <div class="sup-card__price">${usd(item.unit_price_usd_cents)}/u</div>
        </div>
        <div class="sup-card__row">
          <input class="sup-qty-input sup-catalog-qty" type="number" min="0" step="1" value="0">
        </div>
      </div>`;
  }

  const catalogCategorySel = document.getElementById("supCatalogCategory");

  let catalogItems = [];
  async function loadCatalog(q = "") {
    const category = catalogCategorySel.value;
    const params = new URLSearchParams({ q, category, page: "1" });
    const r = await fetch(`/api/supplier-reorder/catalog?${params.toString()}`);
    const body = await r.json();
    catalogItems = body.items;
    el.catalogList.innerHTML = catalogItems.map(catalogRowHtml).join("") || "<p>No matching items.</p>";
  }

  async function loadCategories() {
    const r = await fetch("/api/supplier-reorder/categories");
    const body = await r.json();
    catalogCategorySel.innerHTML = '<option value="">All categories</option>' +
      body.categories.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }

  let searchTimer;
  el.catalogSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadCatalog(el.catalogSearch.value.trim()), 250);
  });
  catalogCategorySel.addEventListener("change", () => loadCatalog(el.catalogSearch.value.trim()));

  el.catalogList.addEventListener("input", (e) => {
    if (!e.target.classList.contains("sup-catalog-qty")) return;
    const card = e.target.closest(".sup-card");
    const id = Number(card.dataset.supplierItemId);
    const item = catalogItems.find(it => it.id === id);
    if (!item) return;
    const qty = Math.max(0, parseInt(e.target.value, 10) || 0);
    const key = `catalog:${id}`;
    if (qty > 0) {
      order.set(key, {
        supplier_item_id: id, supplier: item.supplier,
        unit_price_usd_cents: item.unit_price_usd_cents, qty, name: item.name,
      });
    } else {
      order.delete(key);
    }
    renderTotals();
  });
```

Then replace the existing bottom block:

```js
  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadUnmatchedCount();
  });
})();
```

with:

```js
  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadCatalog();
    loadCategories();
    loadUnmatchedCount();
    renderTotals();
  });
})();
```

- [ ] **Step 2: Add a small CSS rule for the filter row**

Append to `static/css/supplier_reorder.css`:

```css
.sup-catalog-filters {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.sup-catalog-filters .sup-search {
  margin-bottom: 0;
}

.sup-catalog-filters #supCatalogCategory {
  flex: 0 0 auto;
  max-width: 160px;
}
```

- [ ] **Step 3: Verify in the browser**

Load `/supplier-reorder`. Confirm:
- "Browse Full Catalog" lists items (default, unfiltered) grouped alphabetically within category order.
- The category dropdown populates with real category names (e.g. "BEER", "CHOCOLATE BARS") and selecting one filters the list.
- Typing in the search box (e.g. "chocolate") filters the list after a short debounce, combining with any selected category.
- Setting a quantity on a catalog card adds it to the sticky bottom bar's per-supplier totals; setting it back to 0 removes it.
- The sticky bar stays pinned to the bottom of the viewport while scrolling the page.

- [ ] **Step 4: Commit**

```bash
git add static/js/supplier_reorder.js static/css/supplier_reorder.css templates/supplier_reorder.html
git commit -m "feat(supplier-reorder): Browse Catalog front-end + category filter + shared picked-order state"
```

---

### Task 10: CSV export

**Files:**
- Modify: `routes/supplier_reorder.py`
- Modify: `static/js/supplier_reorder.js`

- [ ] **Step 1: Add the export endpoint**

In `routes/supplier_reorder.py`, add to the imports:

```python
import csv
import io
from flask import Response
```

Append the route:

```python
@supplier_reorder_bp.post("/api/supplier-reorder/export")
def api_supplier_reorder_export():
    data = _body()
    lines = data.get("lines") if isinstance(data, dict) else None
    if not lines:
        return jsonify({"ok": False, "error": "no lines to export"}), 400

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["supplier", "item", "qty", "unit_price_usd", "line_total_usd"])
    totals = {}
    for ln in lines:
        supplier = str(ln.get("supplier") or "")
        name = str(ln.get("name") or "")
        try:
            qty = int(ln.get("qty"))
            unit_cents = int(ln.get("unit_price_usd_cents"))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        line_total = qty * unit_cents / 100
        totals[supplier] = totals.get(supplier, 0) + line_total
        w.writerow([supplier, name, qty, f"{unit_cents/100:.2f}", f"{line_total:.2f}"])
    w.writerow([])
    for supplier, total in totals.items():
        w.writerow([supplier, "TOTAL", "", "", f"{total:.2f}"])

    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="supplier_orders.csv"'},
    )
```

(A POST + JSON body is used here instead of the `window.location.href` GET pattern other reports use, because the export payload here — the picked order lines with quantities — is client-side state, not something the server already knows from query params.)

- [ ] **Step 2: Wire up the Export button**

Append to `static/js/supplier_reorder.js` (before the final `document.addEventListener`):

```js
  el.exportBtn.addEventListener("click", async () => {
    const lines = [...order.values()];
    if (lines.length === 0) return;
    const r = await fetch("/api/supplier-reorder/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lines }),
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "supplier_orders.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
```

- [ ] **Step 3: Verify**

On `/supplier-reorder`, set a quantity on at least one Reorder Now card and one Browse Catalog card, click "Export Orders", and confirm a `supplier_orders.csv` file downloads. Open it and confirm: one row per picked line with correct qty/unit price/line total, and a `TOTAL` row per supplier matching the sticky bar's totals.

- [ ] **Step 4: Commit**

```bash
git add routes/supplier_reorder.py static/js/supplier_reorder.js
git commit -m "feat(supplier-reorder): CSV export of the picked order"
```

---

### Task 11: In-app catalog editing (add / edit price / deactivate)

**Files:**
- Modify: `routes/supplier_reorder.py`
- Modify: `static/js/supplier_reorder.js`
- Modify: `templates/supplier_reorder.html` (already has the Add Item panel from Task 7 — this task wires it up)

- [ ] **Step 1: Add the CRUD endpoints**

Append to `routes/supplier_reorder.py`:

```python
from models import db, SupplierItem


@supplier_reorder_bp.post("/api/supplier-reorder/item")
def api_supplier_reorder_item_create():
    data = _body()
    try:
        supplier_id = int(data.get("supplier_id"))
        unit_price_usd_cents = int(round(float(data.get("unit_price_usd")) * 100))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "supplier_id and unit_price_usd required"}), 400
    name = (str(data.get("name") or "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if db.session.get(Supplier, supplier_id) is None:
        return jsonify({"ok": False, "error": "supplier not found"}), 404
    item = SupplierItem(
        supplier_id=supplier_id, name=name,
        category=(str(data.get("category") or "")).strip(),
        format_label=(str(data.get("format_label") or "")).strip(),
        unit_price_usd_cents=unit_price_usd_cents,
        active=True,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"ok": True, "id": item.id})


@supplier_reorder_bp.put("/api/supplier-reorder/item/<int:item_id>")
def api_supplier_reorder_item_update(item_id):
    item = db.session.get(SupplierItem, item_id)
    if item is None:
        return jsonify({"ok": False, "error": "item not found"}), 404
    data = _body()
    if "name" in data and str(data.get("name") or "").strip():
        item.name = str(data.get("name")).strip()
    if "category" in data:
        item.category = (str(data.get("category") or "")).strip()
    if "unit_price_usd" in data:
        try:
            item.unit_price_usd_cents = int(round(float(data.get("unit_price_usd")) * 100))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "unit_price_usd must be a number"}), 400
    if "notes" in data:
        item.notes = (str(data.get("notes") or "")).strip() or None
    db.session.commit()
    return jsonify({"ok": True})


@supplier_reorder_bp.post("/api/supplier-reorder/item/<int:item_id>/deactivate")
def api_supplier_reorder_item_deactivate(item_id):
    item = db.session.get(SupplierItem, item_id)
    if item is None:
        return jsonify({"ok": False, "error": "item not found"}), 404
    item.active = False
    db.session.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 2: Extend the catalog card markup with edit/deactivate controls**

In `static/js/supplier_reorder.js`, replace the `catalogRowHtml` function body (from Task 9) with:

```js
  function catalogRowHtml(item) {
    return `
      <div class="sup-card" data-supplier-item-id="${item.id}">
        <div class="sup-card__top">
          <div>
            <div class="sup-card__title">${esc(item.name)}</div>
            <div class="sup-card__meta">${esc(item.supplier)} &middot; ${esc(item.category)}</div>
          </div>
          <div class="sup-card__price">
            <span class="sup-price-display">${usd(item.unit_price_usd_cents)}/u</span>
            <input class="sup-price-edit" type="number" step="0.01" min="0" hidden value="${(item.unit_price_usd_cents / 100).toFixed(2)}">
          </div>
        </div>
        <div class="sup-card__row">
          <input class="sup-qty-input sup-catalog-qty" type="number" min="0" step="1" value="0">
          <button class="sup-edit-btn" type="button" title="Edit price"><i class="bi bi-pencil"></i></button>
          <button class="sup-deactivate-btn" type="button" title="Remove from catalog"><i class="bi bi-trash"></i></button>
        </div>
      </div>`;
  }
```

- [ ] **Step 3: Wire up edit/deactivate clicks and the Add Item panel**

Append to `static/js/supplier_reorder.js` (before the final `document.addEventListener`):

```js
  el.catalogList.addEventListener("click", async (e) => {
    const card = e.target.closest(".sup-card");
    if (!card) return;
    const id = Number(card.dataset.supplierItemId);

    if (e.target.closest(".sup-edit-btn")) {
      const display = card.querySelector(".sup-price-display");
      const editInput = card.querySelector(".sup-price-edit");
      if (editInput.hidden) {
        display.hidden = true;
        editInput.hidden = false;
        editInput.focus();
        return;
      }
      const r = await fetch(`/api/supplier-reorder/item/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unit_price_usd: editInput.value }),
      });
      const body = await r.json();
      if (body.ok) loadCatalog(el.catalogSearch.value.trim());
      return;
    }

    if (e.target.closest(".sup-deactivate-btn")) {
      if (!confirm("Remove this item from the catalog?")) return;
      await fetch(`/api/supplier-reorder/item/${id}/deactivate`, { method: "POST" });
      loadCatalog(el.catalogSearch.value.trim());
    }
  });

  const addBtn = document.getElementById("supAddItemBtn");
  const addPanel = document.getElementById("supAddItemPanel");
  const addSupplierSel = document.getElementById("supAddSupplier");

  addBtn.addEventListener("click", () => { addPanel.hidden = !addPanel.hidden; });

  async function loadSuppliersForAdd() {
    const r = await fetch("/api/supplier-reorder/suppliers");
    const body = await r.json();
    addSupplierSel.innerHTML = body.suppliers
      .map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  }

  document.getElementById("supAddSave").addEventListener("click", async () => {
    const payload = {
      supplier_id: Number(addSupplierSel.value),
      name: document.getElementById("supAddName").value.trim(),
      category: document.getElementById("supAddCategory").value.trim(),
      unit_price_usd: document.getElementById("supAddPrice").value,
    };
    if (!payload.name || !payload.unit_price_usd) return;
    const r = await fetch("/api/supplier-reorder/item", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json();
    if (body.ok) {
      addPanel.hidden = true;
      document.getElementById("supAddName").value = "";
      document.getElementById("supAddPrice").value = "";
      loadCatalog(el.catalogSearch.value.trim());
    }
  });
```

And update the final `DOMContentLoaded` block to also call `loadSuppliersForAdd()`:

```js
  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadCatalog();
    loadUnmatchedCount();
    loadSuppliersForAdd();
    renderTotals();
  });
})();
```

- [ ] **Step 4: Verify**

On `/supplier-reorder`: click the pencil icon on a catalog card, change the price, confirm it saves and the card refreshes with the new price. Click the trash icon, confirm the item disappears from the catalog after confirming the prompt. Click "Add catalog item", fill the panel, save, and confirm a new card appears in the catalog list.

- [ ] **Step 5: Commit**

```bash
git add routes/supplier_reorder.py static/js/supplier_reorder.js
git commit -m "feat(supplier-reorder): in-app catalog CRUD (add, edit price, deactivate)"
```

---

### Task 12: End-to-end walkthrough

**Files:** none (verification only)

- [ ] **Step 1: Full-flow manual QA**

With both spreadsheets imported (Task 2) and at least a few items matched (Task 4):

1. Load `/supplier-reorder`. Confirm KPI numbers, Reorder Now cards, and Browse Catalog all populate correctly.
2. Pick quantities across both Reorder Now and Browse Catalog sections; confirm the sticky bar totals sum correctly per supplier.
3. Export and confirm the CSV matches what's on screen.
4. Visit `/supplier-reorder/match`, confirm any remaining unmatched items list correctly and confirming one updates the main page's "unmatched items" count on next load.
5. Confirm the sidebar nav highlights "Supplier Reorder" as active only on `/supplier-reorder` pages, and that `/stock` and `/reorder-radar` still work unchanged (regression check — this feature reuses their logic but must not have modified their files).
6. Resize the browser to a mobile width (375px) and confirm the layout holds up (matches the approved Option A mockup: KPI strip → Reorder Now → Browse Catalog → sticky bottom bar, all single-column).

- [ ] **Step 2: Report back to the user**

Summarize what was built, note the two manual deployment steps from the spec (`pip install -r requirements.txt` on the server after deploy; copying the two xlsx files to the server and running `import_supplier_catalog.py` there once), and ask the user to try the page themselves.
