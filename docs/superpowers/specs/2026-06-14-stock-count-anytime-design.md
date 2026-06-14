# Stock: allow Set Count at any time of day

**Date:** 2026-06-14
**Status:** Approved (owner)

## Problem

`Set Count` records a manual stock-take that becomes the baseline for live stock:

```
live = latest_count.qty + receives_after_count − units_sold_since(window_start)
```

Today `window_start` is forced to the count's business day at **08:00**
(`biz_date_range_8h(event_date)`), because `StockEvent` only stores `event_date`
(a date), not the moment of the count. Consequence: if the owner counts mid-day,
every sale that happened earlier that day (08:00 → count time) is subtracted *on
top of* the freshly counted number, so live reads low until the next day's count.

The owner wants to **Set Count whenever they want** and have it be correct: the
count becomes the new baseline and only sales **after that exact date/time** are
deducted.

## Design (anchor the window to the count moment)

Store the actual moment of each count and start the "units sold since" window
there instead of at 08:00.

### Data model
- Add `counted_at DATETIME NULL` to `stock_events` (`models.py`).
- Nullable so legacy rows (which predate the column) keep working via fallback.
- Stamped with **local** `datetime.now()` (not UTC `created_at`) so it is directly
  comparable to POS `RCPT_DATE`. The existing 08:00 logic already assumes
  app-local == POS-local time; this is consistent. (If the app server and POS box
  are ever in different timezones, switch to stamping from the POS via
  `SELECT GETDATE()`.)

### Write path
Set `counted_at = datetime.now()` on every **count** event:
- `POST /api/stock/set-count` (`api_stock_set_count`)
- `POST /api/stock/add` (`api_stock_add`)
- invoice first-delivery baseline (`api_stock_receive_confirm`, the `event_type == "count"` branch)

`receive` events are unchanged (they are deltas, not baselines; `counted_at` stays NULL).

### Read path
New pure helper in `helpers_stock.py`:

```python
def count_window_start(count_event):
    """Window start for 'units sold since' = the moment the count was taken.
    Uses counted_at when present; falls back to the count's business-day 08:00
    start for legacy counts that predate counted_at."""
    ca = getattr(count_event, "counted_at", None)
    if ca is not None:
        return ca
    from pos_dates import biz_date_range_8h
    return biz_date_range_8h(count_event.event_date)[0]
```

`_serialize_items` in `routes/stock.py` uses `count_window_start(c)` to build the
per-item `(itm_code, window_start)` pairs. The deduction SQL
(`build_units_sold_query`, `>= win_start`) is untouched.

### Migration (no Alembic; `create_all()` does not add columns; waitress skips the `__main__` block)
Add an idempotent, module-level migration in `main.py` (after `db.init_app(app)`):
PRAGMA-check `stock_events` and `ALTER TABLE ... ADD COLUMN counted_at DATETIME`
if the column is missing. Runs on import → self-applies on the server's
`git pull` + waitress restart, and on local dev, with no data loss and no manual
step. No-op when the column already exists or the table does not yet exist.

## Result
Count at 15:00 → window starts 15:00 → only post-15:00 sales deduct. Morning
sales are already reflected in the counted number. Correct immediately and on
every later day, until the next count rebaselines.

## Out of scope (YAGNI)
- Backdating a count to an arbitrary past moment (counts are always "now").
- Per-count shift/boundary selection in the UI.

## Tests
- `count_window_start`: returns `counted_at` when set; falls back to 08:00 when None.
- Route: `set-count` / `add` persist a non-null `counted_at`.
- Plumbing: `/api/stock/list` passes the count's `counted_at` as the window start
  to `units_sold_since` (assert on the captured pairs).
- Fix: mock `live_last_sold` in `test_search_marks_tracked_items` (currently makes a
  real POS connection attempt → ~10s hang).
