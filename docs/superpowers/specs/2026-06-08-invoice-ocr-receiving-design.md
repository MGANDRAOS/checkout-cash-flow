# Invoice OCR Receiving — Design (Phase 2)

**Date:** 2026-06-08
**Status:** Approved (owner authorized autonomous build: spec → plan → code → test → ping)
**Builds on:** [Phase 1 manual stock tracking](2026-06-08-manual-stock-tracking-design.md)

## Problem

The owner restocks (e.g. Thursdays) and wants to add received quantities to the stock
tracker by **uploading a photo of the supplier invoice** instead of hand-typing each item.
The app should read the invoice, let the owner review/correct the matches, then add the
quantities to stock. This is the primary restock flow; Phase 1's manual "Set count" is the
fallback.

## Locked decisions (from brainstorming)

- **OCR engine: OpenAI vision**, reusing the existing `client = OpenAI(...)` in the codebase
  ([helpers_ai.py](../../../helpers_ai.py)). `OPENAI_API_KEY` is already required + configured;
  **no new dependency, no new required config key** (per CLAUDE.md, a new required key crashes
  every deploy whose `.env` lacks it). The vision model is a single configurable constant.
- **Input: phone photos only (JPG/PNG).** No PDF. Image is processed in memory and **not
  persisted** (the owner did not ask for a browsable receiving log).
- **Capture per line: item + quantity + unit cost.** Cost stored as integer cents
  (`unit_cost_cents`) on the receive event — enables future margin/price features without
  building them now.
- **Mandatory human review.** OCR is never trusted blind: extracted lines + auto-matched POS
  items are shown for correction before anything writes to stock.

## Flow

```
Upload photo ──> OpenAI vision ──> extracted lines ──> auto-match to POS items
   (in memory)     (JSON)            [{desc,qty,cost}]    (alias + fuzzy)
                                                              │
                                                              ▼
Owner reviews/corrects (fix match, edit qty/cost, drop line) ──> Confirm
                                                              │
                                                              ▼
              Write receive events into the stock ledger (one batch),
              remember corrected matches as aliases, refresh stock.
```

Server holds **no state** between scan and confirm — the browser carries the reviewed lines
and posts the final, corrected set to confirm. The uploaded image is discarded after OCR.

## Data model changes (local SQLite, `models.py`)

Additive only.

### `StockEvent` — add two nullable columns
| Field | Type | Notes |
|---|---|---|
| `unit_cost_cents` | Integer, nullable | per-unit cost from the invoice (cents); null for manual counts |
| `batch_id` | String(36), nullable, indexed | groups all events from one invoice import (enables undo) |

(The existing nullable `invoice_id` column stays unused in Phase 2; `batch_id` is the grouping key.)

### `StockItemAlias` — new table (matching memory)
| Field | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `raw_description` | String(255), unique, indexed | the invoice's text for an item |
| `itm_code` | String(128) | the POS item it maps to |
| `created_at` | DateTime | |

When the owner corrects a match, the (raw_description → itm_code) pair is remembered so the
next invoice with that text auto-matches instantly. Global (not per-supplier) — the owner
chose not to track suppliers.

## Receive semantics (the ledger wiring)

For each confirmed line `{itm_code, title, subgroup, qty, unit_cost}` (cost → `unit_cost_cents`):

- **Item already tracked** → append a `receive` event: `+qty`, `event_date=today`,
  `source='invoice'`, `unit_cost_cents`, `batch_id`. Live stock rises by `qty`
  (`compute_live` already sums receives after the latest count).
- **Item not tracked yet** → create the `StockItem` (cached title/subgroup, default threshold)
  and write an initial `count` event = `qty` (the delivery becomes the baseline), same
  `event_date`/`source`/`cost`/`batch_id`. Flagged "New" in review so the owner knows it
  starts tracking now.

`event_date = today` (the receiving day). The OCR'd invoice date, if any, is kept only as a
note — the ledger math only requires receives to fall on/after the latest count's day, which
"today" always satisfies.

**Undo:** `POST /api/stock/receive/undo {batch_id}` deletes that batch's events. If a deletion
leaves a StockItem with no events (it was created solely by this import), it is removed. Lets
the owner reverse a bad OCR import as a unit.

## Modules

### `helpers_invoice_ocr.py` (new)
- `extract_invoice_lines(image_bytes, media_type, model=...) -> list[dict]` — calls OpenAI
  vision (Responses API, base64 `input_image` content block), instructs strict JSON, parses
  defensively (strip code fences, `json.loads`, validate shape; raise `ValueError` on bad
  output). Returns `[{raw_description, qty, unit_cost}]`. The OpenAI client call is isolated so
  tests mock it (no live API).
- Model from `config.OCR_MODEL` (optional env, default a vision-capable model constant).

### `helpers_invoice_match.py` (new)
- `load_catalog() -> list[dict]` — ONE cached POS query (`@ttl_cache`) returning
  `[{code,title,subgroup}]` for all items; fuzzy matching happens in Python so a multi-line
  invoice is still one POS round-trip (per CLAUDE.md 502-avoidance).
- `rank_match(raw_description, catalog, limit=5) -> list[dict]` — pure token-overlap ranker;
  returns best candidates with a score.
- `alias_lookup(raw_description) -> str|None`, `upsert_alias(raw_description, itm_code)` —
  local SQLite alias memory.
- `match_lines(lines, catalog) -> list[dict]` — per line: alias hit → exact match; else top
  fuzzy candidate + alternates + `tracked` flag.

### `routes/stock.py` (extend the existing blueprint)
| Method + path | Purpose |
|---|---|
| `GET /stock/receive` | render the receive/review page |
| `POST /api/stock/receive/scan` | multipart image → OCR → match → return reviewed lines (no DB write); size-guarded |
| `POST /api/stock/receive/confirm` | `{lines:[...]}` → write receive/count events under one `batch_id`, upsert aliases |
| `POST /api/stock/receive/undo` | `{batch_id}` → reverse a batch |

Auth is automatic via the global `before_request`.

### Templates
- `templates/stock_receive.html` — upload control → review table (raw text, qty, cost, matched
  item with search-to-correct, New/Tracked badge, drop) → Confirm; success shows a summary +
  Undo. Mobile-friendly.
- A "Receive from invoice" button on `stock.html` linking to `/stock/receive`.

### Config
- `OCR_MODEL` — **optional** env (`os.getenv` with a default constant). NOT added to
  `_REQUIRED_KEYS` (avoids the deploy-crash risk). Reuses `OPENAI_API_KEY`.

## Migration

Additive. `db.create_all()` creates `stock_item_aliases` and (on a fresh DB) the new
`StockEvent` columns. Phase 1 + Phase 2 ship together before deploy, so a fresh `create_all`
covers it; if the Phase-1 tables already exist in a DB, the two new nullable `StockEvent`
columns must be added (documented in the plan; `reset_db.py` recreates cleanly in dev).

## Testing

- **Models:** new columns nullable + default; `StockItemAlias` uniqueness.
- **Matching (pure):** ranker prefers token overlap; alias lookup/upsert; `match_lines` uses
  alias before fuzzy; `tracked` flag correctness.
- **OCR parsing:** mocked OpenAI client → valid JSON parsed; code-fenced JSON stripped;
  malformed output raises `ValueError`; the request includes the image as a base64 data URL.
- **Routes:** scan (OCR+catalog mocked) returns reviewed lines; confirm writes correct
  receive vs count events with cost + batch_id and upserts aliases; untracked item is created
  with a count baseline; undo reverses a batch; bad/oversized upload rejected (400/413).

## Out of scope (future)

PDF input, supplier records / browsable receiving history, cost-change & margin dashboards,
price recommendations, multi-page stitching. The captured `unit_cost_cents` is the seam for
the cost/margin work.
