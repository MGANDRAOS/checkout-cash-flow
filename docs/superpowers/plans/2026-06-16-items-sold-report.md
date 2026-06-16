# Items Sold Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mobile-first "Items Sold" page where the user picks a start/end date and an optional subgroup and sees every item sold in that window, grouped by subgroup, with subtotals, a grand total, and CSV export.

**Architecture:** A new backend aggregation helper (`get_items_sold_range`) over the POS MSSQL DB using the 07:00 business-day window, a pure summarizer (`_summarize_items_sold`) that adds revenue share + totals (independently unit-testable), a thin Flask blueprint (`routes/items_sold.py`) exposing page + JSON + CSV endpoints, and a custom-rendered mobile-first front end built with the frontend-design skill. Reuses the existing `/api/reports/subgroups` dropdown source.

**Tech Stack:** Python 3 / Flask blueprints, pyodbc (MSSQL, read-only), pytest + `unittest.mock`, Jinja2 templates extending `base.html`, Bootstrap 5 + vanilla JS (matching the `snap-*` Sales Snapshot pattern).

**Verification reality:** Tests run with the project venv `C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe` (has pyodbc/flask). Root `conftest.py` injects dummy env vars so `config` imports without a `.env`. POS queries are NOT hit in pytest — POS-dependent functions are mocked at the route boundary (the established pattern in `tests/test_routes_stock.py`). The live SQL is verified by a best-effort dev smoke + the manual mobile UI pass.

**Refinement vs spec:** The spec's `totals.txns` grand total is intentionally dropped — summing per-item `COUNT(DISTINCT RCPT_ID)` double-counts receipts that contain multiple items. Per-row `txns` is retained (receipts an item appeared on); KPI totals are `items` / `qty` / `revenue` (+ `revenue_usd`).

---

## File Structure

- **Create** `helpers_intelligence.py` additions: `_summarize_items_sold(raw_rows)` (pure) + `get_items_sold_range(start_date, end_date, subgroup_label=None)` (SQL). Lives beside `get_item_trends` — reuses `_connect()` and the subgroup-resolution CTE.
- **Create** `routes/items_sold.py`: blueprint with `/reports/items-sold`, `/api/reports/items-sold`, `/api/reports/items-sold/export-csv`.
- **Modify** `main.py`: import + register `items_sold_bp`.
- **Modify** `templates/base.html`: sidebar link under **Items**, after *Item Trends*.
- **Create** `templates/report_items_sold.html`: page markup.
- **Create** `static/js/items_sold.js`: fetch + render + interactions.
- **Create** `static/css/items_sold.css` (or append a scoped block to `static/main.css`, matching how `snap-*` lives in `main.css` — prefer a new file linked from the template's `{% block head %}` to keep it isolated).
- **Create** `tests/test_helpers_items_sold.py`: unit tests for `_summarize_items_sold`.
- **Create** `tests/test_routes_items_sold.py`: route validation + JSON shape + CSV tests (helper mocked).

---

## Task 1: Pure summarizer `_summarize_items_sold`

**Files:**
- Modify: `helpers_intelligence.py` (add function near `get_item_trends`)
- Test: `tests/test_helpers_items_sold.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_helpers_items_sold.py`:

```python
from helpers_intelligence import _summarize_items_sold


def test_empty_rows_returns_zero_totals():
    out = _summarize_items_sold([])
    assert out["rows"] == []
    assert out["totals"] == {"items": 0, "qty": 0.0, "revenue": 0.0}


def test_computes_share_totals_and_sorts_by_revenue_desc():
    raw = [
        {"subgroup": "Beer", "item_code": "A", "item": "Almaza",
         "qty": 10.0, "revenue": 300.0, "avg_price": 30.0, "txns": 7},
        {"subgroup": "Soft", "item_code": "B", "item": "Cola",
         "qty": 40.0, "revenue": 100.0, "avg_price": 2.5, "txns": 20},
    ]
    out = _summarize_items_sold(raw)
    # sorted by revenue desc -> Almaza first
    assert [r["item"] for r in out["rows"]] == ["Almaza", "Cola"]
    assert out["rows"][0]["share"] == 75.0
    assert out["rows"][1]["share"] == 25.0
    assert out["totals"] == {"items": 2, "qty": 50.0, "revenue": 400.0}
    # shares sum to ~100
    assert round(sum(r["share"] for r in out["rows"]), 1) == 100.0


def test_zero_revenue_has_no_divide_by_zero():
    raw = [{"subgroup": "X", "item_code": "Z", "item": "Free",
            "qty": 0.0, "revenue": 0.0, "avg_price": 0.0, "txns": 1}]
    out = _summarize_items_sold(raw)
    assert out["rows"][0]["share"] == 0.0
    assert out["totals"]["revenue"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/test_helpers_items_sold.py -v`
Expected: FAIL — `ImportError: cannot import name '_summarize_items_sold'`.

- [ ] **Step 3: Implement the pure summarizer**

Add to `helpers_intelligence.py` (just above `get_item_trends`):

```python
def _summarize_items_sold(raw_rows: List[Dict]) -> Dict:
    """
    Pure aggregation over already-aggregated per-item rows.

    Input rows: [{subgroup, item_code, item, qty, revenue, avg_price, txns}, ...]
    - Adds `share` (= item revenue / total revenue * 100) to each row.
    - Sorts rows by revenue DESC, then item ASC.
    - Computes grand totals (items = distinct rows, qty, revenue).

    No DB access — unit-testable in isolation.
    """
    rows = [dict(r) for r in raw_rows]
    total_revenue = sum(float(r.get("revenue") or 0.0) for r in rows)
    total_qty = sum(float(r.get("qty") or 0.0) for r in rows)

    for r in rows:
        rev = float(r.get("revenue") or 0.0)
        r["qty"] = float(r.get("qty") or 0.0)
        r["revenue"] = rev
        r["avg_price"] = float(r.get("avg_price") or 0.0)
        r["txns"] = int(r.get("txns") or 0)
        r["share"] = round((rev / total_revenue) * 100, 1) if total_revenue else 0.0

    rows.sort(key=lambda r: (-r["revenue"], str(r.get("item") or "")))

    return {
        "rows": rows,
        "totals": {
            "items": len(rows),
            "qty": total_qty,
            "revenue": total_revenue,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/test_helpers_items_sold.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add helpers_intelligence.py tests/test_helpers_items_sold.py
git commit -m "feat(items-sold): pure summarizer for per-item sales totals + share"
```

---

## Task 2: SQL helper `get_items_sold_range`

**Files:**
- Modify: `helpers_intelligence.py` (add below `_summarize_items_sold`)

No pytest unit test (hits MSSQL); verified by best-effort dev smoke in this task and by the manual UI pass in Task 5. Mirrors `get_item_trends`' subgroup-resolution CTE and `biz_date_range_7h` windowing.

- [ ] **Step 1: Ensure the import is present**

At the top of `helpers_intelligence.py`, confirm/add:

```python
from pos_dates import biz_date_range_7h
```

(`cutoff_dt_7h` is already imported from `pos_dates`; add `biz_date_range_7h` to that import line.)

- [ ] **Step 2: Implement the helper**

Add to `helpers_intelligence.py` (below `_summarize_items_sold`):

```python
def get_items_sold_range(start_date, end_date, subgroup_label: Optional[str] = None) -> Dict:
    """
    Flat per-item sales aggregation over an inclusive 07:00 business-day range,
    optionally filtered to a single subgroup.

    Window: business day [start_date] 07:00  ->  [end_date + 1] 07:00 (exclusive),
    which is index-friendly on RCPT_DATE (see pos_dates.biz_date_range_7h).

    Returns:
      {
        "rows": [{subgroup, item_code, item, qty, revenue, avg_price, txns, share}, ...],
        "totals": {items, qty, revenue},
        "meta": {start_date, end_date, subgroup, days},
      }
    """
    win_start, _ = biz_date_range_7h(start_date)
    _, win_end_exclusive = biz_date_range_7h(end_date)

    subgroup_filter_sql = ""
    subgroup_params: List = []
    if subgroup_label and str(subgroup_label).strip():
        subgroup_filter_sql = (
            " AND UPPER(LTRIM(RTRIM(subgroup_label))) = UPPER(LTRIM(RTRIM(?))) "
        )
        subgroup_params.append(subgroup_label.strip())

    sql = f"""
        SET NOCOUNT ON;

        WITH Lines AS (
          SELECT
            CAST(c.ITM_CODE AS nvarchar(128)) AS item_code,

            CAST(
              CASE
                WHEN i.ITM_TITLE IS NOT NULL AND LTRIM(RTRIM(i.ITM_TITLE)) <> N''
                  THEN i.ITM_TITLE
                ELSE CAST(c.ITM_CODE AS nvarchar(128))
              END
            AS nvarchar(128)) AS item_label,

            COALESCE(
              s_id.SubGrp_Name,
              s_nm.SubGrp_Name,
              NULLIF(x.SubGrpText, N''),
              N'Unknown'
            ) AS subgroup_label,

            CAST(c.ITM_QUANTITY AS float) AS qty,
            CAST(c.ITM_QUANTITY AS float) * CAST(c.ITM_PRICE AS float) AS revenue,
            c.RCPT_ID AS rcpt_id

          FROM dbo.HISTORIC_RECEIPT r
          JOIN dbo.HISTORIC_RECEIPT_CONTENTS c ON c.RCPT_ID = r.RCPT_ID
          LEFT JOIN dbo.ITEMS i ON i.ITM_CODE = c.ITM_CODE

          CROSS APPLY (
            SELECT
              CASE
                WHEN i.ITM_SUBGROUP IS NULL THEN NULL
                WHEN LTRIM(RTRIM(i.ITM_SUBGROUP)) = N'' THEN NULL
                WHEN i.ITM_SUBGROUP NOT LIKE N'%[^0-9]%' THEN CONVERT(int, i.ITM_SUBGROUP)
                ELSE NULL
              END AS SubGrpID,
              LTRIM(RTRIM(i.ITM_SUBGROUP)) AS SubGrpText
          ) AS x

          LEFT JOIN dbo.SUBGROUPS AS s_id ON s_id.SubGrp_ID = x.SubGrpID
          LEFT JOIN dbo.SUBGROUPS AS s_nm
            ON LTRIM(RTRIM(s_nm.SubGrp_Name)) = x.SubGrpText

          WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?
        ),

        Filtered AS (
          SELECT * FROM Lines
          WHERE 1=1
          {subgroup_filter_sql}
        )

        SELECT
          subgroup_label                AS subgroup,
          item_code,
          item_label                    AS item,
          SUM(qty)                      AS qty,
          SUM(revenue)                  AS revenue,
          CASE WHEN SUM(qty) = 0 THEN 0 ELSE SUM(revenue) / SUM(qty) END AS avg_price,
          COUNT(DISTINCT rcpt_id)       AS txns
        FROM Filtered
        GROUP BY subgroup_label, item_code, item_label
        ORDER BY revenue DESC, item ASC;
    """

    params: List = [win_start, win_end_exclusive]
    params.extend(subgroup_params)

    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    raw = [
        {
            "subgroup": str(r.subgroup),
            "item_code": str(r.item_code),
            "item": str(r.item),
            "qty": float(r.qty or 0.0),
            "revenue": float(r.revenue or 0.0),
            "avg_price": float(r.avg_price or 0.0),
            "txns": int(r.txns or 0),
        }
        for r in rows
    ]

    summary = _summarize_items_sold(raw)
    summary["meta"] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "subgroup": subgroup_label.strip() if (subgroup_label and subgroup_label.strip()) else None,
        "days": (end_date - start_date).days + 1,
    }
    return summary
```

- [ ] **Step 3: Best-effort live smoke (skip if dev cannot reach POS DB)**

Run (PowerShell):

```
& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -c "import os; from dotenv import load_dotenv; load_dotenv(r'C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.env'); from datetime import date, timedelta; from helpers_intelligence import get_items_sold_range; d=get_items_sold_range(date.today()-timedelta(days=7), date.today()); print('rows', len(d['rows']), 'totals', d['totals']); print('share_sum', round(sum(r['share'] for r in d['rows']),1)); print(d['rows'][:2])"
```

Expected: prints a row count, totals dict, `share_sum` ≈ 100.0 (or 0.0 if no sales), and two sample rows with keys `subgroup,item_code,item,qty,revenue,avg_price,txns,share`. If the DB is unreachable from dev, note it and rely on Task 5's UI pass.

- [ ] **Step 4: Commit**

```bash
git add helpers_intelligence.py
git commit -m "feat(items-sold): MSSQL range aggregation helper (07:00 biz-day window)"
```

---

## Task 3: Blueprint `routes/items_sold.py` + registration

**Files:**
- Create: `routes/items_sold.py`
- Modify: `main.py` (import line near line 41; register near line 367)
- Test: `tests/test_routes_items_sold.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/test_routes_items_sold.py`:

```python
import os
from unittest.mock import patch

import pytest
from flask import Flask

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE = {
    "rows": [
        {"subgroup": "Beer", "item_code": "A", "item": "Almaza",
         "qty": 10.0, "revenue": 300.0, "avg_price": 30.0, "txns": 7, "share": 75.0},
        {"subgroup": "Soft", "item_code": "B", "item": "Cola",
         "qty": 40.0, "revenue": 100.0, "avg_price": 2.5, "txns": 20, "share": 25.0},
    ],
    "totals": {"items": 2, "qty": 50.0, "revenue": 400.0},
    "meta": {"start_date": "2026-06-01", "end_date": "2026-06-07",
             "subgroup": None, "days": 7},
}


@pytest.fixture
def client():
    app = Flask(__name__,
                template_folder=os.path.join(_REPO_ROOT, "templates"),
                static_folder=os.path.join(_REPO_ROOT, "static"))
    app.config["TESTING"] = True
    from routes.items_sold import items_sold_bp
    app.register_blueprint(items_sold_bp)
    return app.test_client()


def test_missing_dates_returns_400(client):
    r = client.get("/api/reports/items-sold")
    assert r.status_code == 400
    assert "required" in r.get_json()["error"]


def test_bad_date_format_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2026/06/01&end_date=2026-06-07")
    assert r.status_code == 400
    assert "YYYY-MM-DD" in r.get_json()["error"]


def test_start_after_end_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2026-06-07&end_date=2026-06-01")
    assert r.status_code == 400


def test_range_too_large_returns_400(client):
    r = client.get("/api/reports/items-sold?start_date=2020-01-01&end_date=2026-06-07")
    assert r.status_code == 400
    assert "too large" in r.get_json()["error"].lower()


def test_happy_path_returns_rows_and_usd(client):
    with patch("routes.items_sold.get_items_sold_range", return_value=dict(_FAKE)) as m:
        r = client.get("/api/reports/items-sold?start_date=2026-06-01&end_date=2026-06-07")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["rows"]) == 2
    assert body["totals"]["revenue"] == 400.0
    # USD added by the route (89000 from tests/conftest env)
    assert round(body["totals"]["revenue_usd"], 6) == round(400.0 / 89000.0, 6)
    m.assert_called_once()


def test_csv_export_has_header_and_total(client):
    with patch("routes.items_sold.get_items_sold_range", return_value=dict(_FAKE)):
        r = client.get("/api/reports/items-sold/export-csv?start_date=2026-06-01&end_date=2026-06-07")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    assert "subgroup,item_code,item,qty,avg_price,revenue,share_pct" in text
    assert "Almaza" in text
    assert "TOTAL" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/test_routes_items_sold.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes.items_sold'`.

- [ ] **Step 3: Create the blueprint**

Create `routes/items_sold.py`:

```python
# routes/items_sold.py
# Items Sold report: pick a date range + optional subgroup, list everything sold.
import csv
import io
from datetime import datetime

from flask import Blueprint, render_template, jsonify, request, Response

import config
from helpers_intelligence import get_items_sold_range

items_sold_bp = Blueprint("items_sold", __name__)

MAX_RANGE_DAYS = 730  # 24 months — protects MSSQL from accidental huge scans


def _parse_params():
    """Returns ((start_date, end_date, subgroup_or_None), None) or (None, (msg, status))."""
    start_s = (request.args.get("start_date") or "").strip()
    end_s = (request.args.get("end_date") or "").strip()
    subgroup = (request.args.get("subgroup") or "").strip()

    if not start_s or not end_s:
        return None, ("start_date and end_date are required", 400)
    try:
        start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_s, "%Y-%m-%d").date()
    except Exception:
        return None, ("Invalid date format. Use YYYY-MM-DD", 400)
    if start_d > end_d:
        return None, ("start_date must be <= end_date", 400)
    if (end_d - start_d).days > MAX_RANGE_DAYS:
        return None, (f"Date range too large. Max {MAX_RANGE_DAYS} days.", 400)

    return (start_d, end_d, subgroup or None), None


@items_sold_bp.route("/reports/items-sold")
def items_sold_page():
    """Renders the report shell; data is fetched client-side from the API."""
    return render_template("report_items_sold.html")


@items_sold_bp.route("/api/reports/items-sold")
def api_items_sold():
    parsed, err = _parse_params()
    if err:
        return jsonify({"error": err[0]}), err[1]
    start_d, end_d, subgroup = parsed

    try:
        data = get_items_sold_range(start_d, end_d, subgroup_label=subgroup)
    except Exception as e:  # keep the UI alive — return a structured error
        return jsonify({
            "rows": [], "totals": {"items": 0, "qty": 0.0, "revenue": 0.0},
            "meta": {}, "error": str(e),
        }), 500

    rate = float(config.USD_EXCHANGE_RATE or 0)
    data["totals"]["revenue_usd"] = (data["totals"]["revenue"] / rate) if rate else 0.0
    return jsonify(data)


@items_sold_bp.route("/api/reports/items-sold/export-csv")
def api_items_sold_csv():
    parsed, err = _parse_params()
    if err:
        return Response(err[0], status=err[1], mimetype="text/plain")
    start_d, end_d, subgroup = parsed

    try:
        data = get_items_sold_range(start_d, end_d, subgroup_label=subgroup)
    except Exception as e:
        return Response(f"Failed to build CSV: {e}", status=500, mimetype="text/plain")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["subgroup", "item_code", "item", "qty", "avg_price", "revenue", "share_pct"])
    for r in data["rows"]:
        w.writerow([
            r["subgroup"], r["item_code"], r["item"],
            r["qty"], round(r["avg_price"], 2), round(r["revenue"], 2), r["share"],
        ])
    t = data["totals"]
    w.writerow([])
    w.writerow(["TOTAL", "", "", t["qty"], "", round(t["revenue"], 2), 100.0])

    sub = (subgroup or "all").replace(" ", "-")
    fname = f"items_sold_{start_d}_to_{end_d}_{sub}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
```

- [ ] **Step 4: Register the blueprint in `main.py`**

Add to the import block (after `from routes.stock import stock_bp`, ~line 41):

```python
from routes.items_sold import items_sold_bp
```

Add to the registration block (after `app.register_blueprint(stock_bp)`, ~line 367):

```python
app.register_blueprint(items_sold_bp)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/test_routes_items_sold.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add routes/items_sold.py main.py tests/test_routes_items_sold.py
git commit -m "feat(items-sold): blueprint (page + JSON + CSV) and registration"
```

---

## Task 4: Sidebar navigation link

**Files:**
- Modify: `templates/base.html` (Items section, after the Item Trends link, ~line 91)

- [ ] **Step 1: Add the nav link**

In `templates/base.html`, immediately after the Item Trends `<a>` block (the one linking to `/reports/item-trends`), insert:

```html
      <a href="/reports/items-sold"
        class="sidebar-link {% if request.path.startswith('/reports/items-sold') %}active{% endif %}">
        <i class="bi bi-card-checklist"></i><span>Items Sold</span>
      </a>
```

- [ ] **Step 2: Verify the template still renders (no syntax error)**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/test_routes_items_sold.py -v`
(The page route renders `report_items_sold.html` which extends `base.html`; this is created in Task 5. For now just confirm existing tests still pass.)
Expected: still passing.

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "feat(items-sold): sidebar nav link under Items"
```

---

## Task 5: Front end (template + JS + CSS) — frontend-design skill

**Files:**
- Create: `templates/report_items_sold.html`
- Create: `static/js/items_sold.js`
- Create: `static/css/items_sold.css`

> **REQUIRED SUB-SKILL for this task:** Use `frontend-design:frontend-design` to produce distinctive, production-grade, mobile-first markup/CSS. The contract below is binding (IDs, data shape, behavior); the visual execution is the skill's job. Match the existing `snap-*` Sales Snapshot language (DM Sans, slate light theme, rounded cards, grain overlay already global) so the page feels native.

### Data contract (consumed by the JS)

- `GET /api/reports/subgroups` → `[{id, name}, ...]` (existing endpoint) — populates the subgroup `<select>` (first option: "All subgroups", value `""`).
- `GET /api/reports/items-sold?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&subgroup=<name>` →
  `{ rows: [{subgroup,item_code,item,qty,revenue,avg_price,txns,share}], totals: {items,qty,revenue,revenue_usd}, meta: {start_date,end_date,subgroup,days}, error? }`
- CSV: navigate to `/api/reports/items-sold/export-csv?…same params…`.

### Behavior contract

1. On load: default range = **last 7 days** (To = today, From = today−6). Populate subgroup dropdown, then fetch + render.
2. Quick-range chips set From/To and refetch: **Today**, **Yesterday**, **Last 7**, **Last 30**, **This Month**.
3. Changing From / To / Subgroup, or clicking **Apply**, refetches.
4. **Grouping:** build subgroup groups client-side from `rows`. Each group = collapsible card with a header showing subgroup name, group unit subtotal, group revenue subtotal, and group % of grand total. Groups sorted by group revenue DESC; items within a group sorted by revenue DESC (already sorted by the API). If a single subgroup is filtered, expand its card by default; otherwise collapse all but the top group.
5. **Item search box:** filters the rendered rows client-side by item name / code (no refetch); hides empty groups.
6. **KPI hero:** distinct items (`totals.items`), total units (`totals.qty`), total revenue (`totals.revenue` LBP primary, `totals.revenue_usd` USD secondary).
7. **Export CSV** button → navigates to the CSV endpoint with current params.
8. States: loading skeleton while fetching; empty state "No items sold in this range." when `rows` is empty; error banner showing `error` text on non-200 / `error` field.
9. Numbers formatted with thousands separators; revenue rounded to whole LBP, USD to 2 dp; share as `xx.x%`.

### Required element IDs / hooks (so JS and tests stay stable)

`#isFrom`, `#isTo`, `#isSubgroup`, `#isSearch`, `#isApply`, `#isExport`, quick chips `.is-chip[data-quick]`, KPI targets `#isKpiItems`, `#isKpiUnits`, `#isKpiRevLbp`, `#isKpiRevUsd`, results container `#isResults`, status/empty container `#isStatus`.

- [ ] **Step 1: Create `templates/report_items_sold.html`**

Extend `base.html`; in `{% block head %}` link the new CSS; in `{% block content %}` render the header, quick chips, filter strip, KPI hero, results container, and status container using the IDs above; at the end of content load `static/js/items_sold.js` and call its `init()` on `DOMContentLoaded` (mirror how `sales_snapshot.html` wires `SalesSnapshotModule.init()`). Build the actual markup with the frontend-design skill.

- [ ] **Step 2: Create `static/css/items_sold.css`**

Scoped, mobile-first styles (single-column < 768px; richer grouped table layout ≥ 768px). Reuse the visual tokens of `snap-*` (card radius, shadows, slate palette, DM Sans). Build with the frontend-design skill.

- [ ] **Step 3: Create `static/js/items_sold.js`**

Implement an `ItemsSoldModule` object (or equivalent) exposing `init()`, fulfilling the behavior contract. Vanilla JS + fetch (jQuery is available but not required). Format numbers with `Intl.NumberFormat`.

- [ ] **Step 4: Manual verification (mobile-first)**

Bring the app up locally (worktree has no `.env` — copy it in first, run, then remove it; per CLAUDE.md):

```
Copy-Item "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.env" ".\.env"
& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" main.py
```

Then in a browser at a narrow (≈390px) viewport, load `http://127.0.0.1:5000/reports/items-sold` and confirm:
- Default last-7-days data loads; KPI hero shows items/units/revenue (LBP + USD).
- Quick chips change the range and refetch.
- Subgroup dropdown filters; single-subgroup card expands by default.
- Expand/collapse subgroup cards works; item search filters live.
- Export CSV downloads a file with a TOTAL row.
- Empty range shows the empty state; a forced error shows the error banner.
- Looks polished on mobile AND desktop widths.

Stop the server and remove the copied `.env`:

```
Remove-Item ".\.env"
```

(Do NOT commit `.env` — it is tracked; ensure `git status` shows it untouched.)

- [ ] **Step 5: Commit**

```bash
git add templates/report_items_sold.html static/js/items_sold.js static/css/items_sold.css
git commit -m "feat(items-sold): mobile-first report UI (grouped cards, KPI hero, CSV)"
```

---

## Task 6: Full-suite verification + branch wrap-up

- [ ] **Step 1: Run the entire test suite (no regressions)**

Run: `& "C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest -q`
Expected: all tests pass (the new `test_helpers_items_sold.py` + `test_routes_items_sold.py` included; pre-existing suites unaffected).

- [ ] **Step 2: Confirm no stray tracked-file changes**

Run: `git status --porcelain`
Expected: clean working tree; no `.env` or `routes/__pycache__/*.pyc` staged (per CLAUDE.md git caveats).

- [ ] **Step 3: Confirm the working tree is on the feature branch and summarize**

The feature is complete: page at `/reports/items-sold`, JSON + CSV APIs, nav link, mobile-first UI. Ready for review / merge per the finishing-a-development-branch skill.

---

## Self-Review (author checklist)

- **Spec coverage:** date range + optional subgroup (Task 2/3), grouped-by-subgroup UI (Task 5), qty + revenue (Task 1/2/5), CSV export (Task 3/5), mobile-first best UI (Task 5 via frontend-design), nav (Task 4), business-day 07:00 window + 730-day clamp (Task 2/3), reuse `/api/reports/subgroups` (Task 5). ✓
- **Spec deviation documented:** `totals.txns` dropped (double-count) — noted at top + Task 1. ✓
- **Placeholders:** none — every code/test step has full content. ✓
- **Type consistency:** `_summarize_items_sold` returns `{rows, totals{items,qty,revenue}}`; `get_items_sold_range` adds `meta` + per-row `share`; route adds `totals.revenue_usd`; JS/CSV consume exactly these keys. ✓
