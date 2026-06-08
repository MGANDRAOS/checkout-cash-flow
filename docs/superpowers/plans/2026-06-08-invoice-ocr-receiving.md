# Invoice OCR Receiving (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Upload a phone photo of a supplier invoice → OpenAI vision reads the line items → owner reviews/corrects matches → confirmed quantities (with unit cost) are added to the Phase 1 stock ledger as `receive` events.

**Architecture:** Extends Phase 1. Two new helper modules (OCR via the existing OpenAI client; catalog load + fuzzy matching + alias memory), two new `StockEvent` columns (`unit_cost_cents`, `batch_id`), one new table (`StockItemAlias`), four new routes on the existing `stock_bp`, and a receive/review page. Image is processed in memory, never persisted. One cached POS query per scan (matching is in Python).

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite), OpenAI Python SDK (already a dep; `OPENAI_API_KEY` already configured), pyodbc (read-only POS), pytest, Jinja2 + Bootstrap.

**Run tests with the venv python:**
`"C:\Users\majd\Documents\PyCharm Projects\checkout-cash-flow\.venv\Scripts\python.exe" -m pytest tests/ -q`

---

## File Structure
- **Create** `helpers_invoice_ocr.py` — OpenAI vision call + defensive JSON parse (client isolated for mocking).
- **Create** `helpers_invoice_match.py` — cached catalog load (one POS query) + pure fuzzy ranker + alias lookup/upsert + match_lines.
- **Create** `templates/stock_receive.html` — upload + review table.
- **Modify** `models.py` — add `unit_cost_cents`, `batch_id` to `StockEvent`; add `StockItemAlias`.
- **Modify** `config.py` — add OPTIONAL `OCR_MODEL` (not required).
- **Modify** `routes/stock.py` — add 4 receive routes.
- **Modify** `templates/stock.html` — "Receive from invoice" button.
- **Tests:** `tests/test_models_stock_phase2.py`, `tests/test_helpers_invoice_match.py`, `tests/test_helpers_invoice_ocr.py`, `tests/test_routes_stock_receive.py`.

Conventions: money = integer cents (`int(round(x*100))`). Lazy `from helpers_intelligence import _connect` inside functions. Mock POS/OpenAI in tests. Auth is global (no decorator).

---

## Task 1: Schema — cost + batch on StockEvent, StockItemAlias table

**Files:**
- Modify: `models.py`
- Test: `tests/test_models_stock_phase2.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_models_stock_phase2.py`

```python
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from models import db, StockItem, StockEvent, StockItemAlias


def test_stock_event_cost_and_batch_nullable(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", alert_threshold=5)
        db.session.add(si)
        db.session.flush()
        # manual count: cost+batch null
        db.session.add(StockEvent(stock_item_id=si.id, event_type="count", qty=10,
                                  event_date=date.today(), source="manual"))
        # invoice receive: cost+batch set
        db.session.add(StockEvent(stock_item_id=si.id, event_type="receive", qty=24,
                                  event_date=date.today(), source="invoice",
                                  unit_cost_cents=150, batch_id="batch-xyz"))
        db.session.commit()
        evs = StockEvent.query.filter_by(stock_item_id=si.id).order_by(StockEvent.id).all()
        assert evs[0].unit_cost_cents is None and evs[0].batch_id is None
        assert evs[1].unit_cost_cents == 150 and evs[1].batch_id == "batch-xyz"


def test_alias_unique(app):
    with app.app_context():
        db.session.add(StockItemAlias(raw_description="ALMAZA 33CL", itm_code="ALM330"))
        db.session.commit()
        db.session.add(StockItemAlias(raw_description="ALMAZA 33CL", itm_code="OTHER"))
        with pytest.raises(IntegrityError):
            db.session.commit()
```

- [ ] **Step 2: Run, verify FAIL**
`...python.exe -m pytest tests/test_models_stock_phase2.py -v` → ImportError (StockItemAlias) / unexpected kwargs.

- [ ] **Step 3: Implement** — in `models.py`, add two columns to `StockEvent` (after `invoice_id`) and append a new class.

In `StockEvent`, after the `invoice_id` column line, add:
```python
    unit_cost_cents = db.Column(db.Integer, nullable=True)   # per-unit cost from invoice (Phase 2)
    batch_id = db.Column(db.String(36), nullable=True, index=True)  # groups one invoice import
```

Append after `StockEvent`:
```python
class StockItemAlias(db.Model):
    """Remembers that an invoice's printed item text maps to a POS item code.

    Lets repeat invoices auto-match instantly. Global (not per-supplier) by design.
    """
    __tablename__ = "stock_item_aliases"

    id = db.Column(db.Integer, primary_key=True)
    raw_description = db.Column(db.String(255), nullable=False, unique=True, index=True)
    itm_code = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<StockItemAlias {self.raw_description!r} -> {self.itm_code}>"
```

- [ ] **Step 4: Run, verify PASS (2 passed)**
`...python.exe -m pytest tests/test_models_stock_phase2.py -v`

- [ ] **Step 5: Commit**
```bash
git add models.py tests/test_models_stock_phase2.py
git commit -m "feat(stock): StockEvent cost+batch columns, StockItemAlias table"
```

---

## Task 2: Matching helper (`helpers_invoice_match.py`)

**Files:**
- Create: `helpers_invoice_match.py`
- Test: `tests/test_helpers_invoice_match.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_helpers_invoice_match.py`

```python
from helpers_invoice_match import rank_match, alias_lookup, upsert_alias, match_lines
from models import db, StockItemAlias

CATALOG = [
    {"code": "ALM330", "title": "ALMAZA BEER 330ML", "subgroup": "Beer"},
    {"code": "PEP1L", "title": "PEPSI 1L", "subgroup": "Soda"},
    {"code": "WTR05", "title": "WATER 500ML", "subgroup": "Water"},
]


def test_rank_match_prefers_token_overlap():
    out = rank_match("ALMAZA 33", CATALOG)
    assert out[0]["code"] == "ALM330"
    assert out[0]["score"] > 0


def test_rank_match_no_overlap_returns_empty():
    assert rank_match("ZZZ NOTHING", CATALOG) == []


def test_alias_lookup_and_upsert(app):
    with app.app_context():
        assert alias_lookup("ALMAZA 33CL") is None
        upsert_alias("ALMAZA 33CL", "ALM330")
        db.session.commit()
        assert alias_lookup("ALMAZA 33CL") == "ALM330"
        # upsert overwrites
        upsert_alias("ALMAZA 33CL", "PEP1L")
        db.session.commit()
        assert alias_lookup("ALMAZA 33CL") == "PEP1L"
        assert StockItemAlias.query.count() == 1


def test_match_lines_uses_alias_before_fuzzy(app):
    with app.app_context():
        upsert_alias("FUNNY NAME", "WTR05")
        db.session.commit()
        lines = [{"raw_description": "FUNNY NAME", "qty": 5, "unit_cost": 1.0},
                 {"raw_description": "PEPSI 1L", "qty": 2, "unit_cost": 2.0}]
        out = match_lines(lines, CATALOG)
        assert out[0]["match"]["code"] == "WTR05"   # alias wins despite no token overlap
        assert out[1]["match"]["code"] == "PEP1L"   # fuzzy
        assert out[0]["qty"] == 5
```

- [ ] **Step 2: Run, verify FAIL**
`...python.exe -m pytest tests/test_helpers_invoice_match.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement** — create `helpers_invoice_match.py`

```python
"""Match invoice line text to POS items: alias memory + Python fuzzy ranking.

Matching runs against a catalog loaded with ONE cached POS query, so a multi-line
invoice stays a single POS round-trip (per CLAUDE.md 502-avoidance).
"""
from __future__ import annotations

import re
from typing import List, Optional

from cache_utils import ttl_cache
from models import db, StockItemAlias


def _tokens(text: str):
    return set(t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t)


def rank_match(raw_description: str, catalog: List[dict], limit: int = 5) -> List[dict]:
    """Pure token-overlap ranker. Returns best candidates (Jaccard score), highest first."""
    q = _tokens(raw_description)
    if not q:
        return []
    scored = []
    for it in catalog:
        c = _tokens(it.get("title")) | _tokens(it.get("code"))
        if not c:
            continue
        inter = q & c
        if not inter:
            continue
        score = len(inter) / len(q | c)
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"code": str(it["code"]), "title": it.get("title", ""),
             "subgroup": it.get("subgroup", ""), "score": round(s, 3)}
            for s, it in scored[:limit]]


@ttl_cache(seconds=120)
def load_catalog() -> List[dict]:
    """All POS items as [{code,title,subgroup}] — ONE cached query for fuzzy matching."""
    from helpers_intelligence import _connect  # lazy: avoid pyodbc import at module load
    rows = []
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("""
            SET NOCOUNT ON;
            SELECT CAST(i.ITM_CODE AS nvarchar(128)) AS code,
                   LTRIM(RTRIM(COALESCE(i.ITM_TITLE, ''))) AS title,
                   LTRIM(RTRIM(COALESCE(s.SubGrp_Name, ''))) AS subgroup
            FROM dbo.ITEMS i
            LEFT JOIN dbo.SUBGROUPS s
              ON (TRY_CAST(i.ITM_SUBGROUP AS int) = s.SubGrp_ID
                  OR LTRIM(RTRIM(i.ITM_SUBGROUP)) = LTRIM(RTRIM(s.SubGrp_Name)));
        """)
        for r in cur.fetchall():
            rows.append({"code": str(r.code), "title": r.title or "", "subgroup": r.subgroup or ""})
    return rows


def alias_lookup(raw_description: str) -> Optional[str]:
    a = StockItemAlias.query.filter_by(raw_description=(raw_description or "").strip()).first()
    return a.itm_code if a else None


def upsert_alias(raw_description: str, itm_code: str) -> None:
    """Add to the session (caller commits). Overwrites an existing alias for the same text."""
    desc = (raw_description or "").strip()
    if not desc or not itm_code:
        return
    a = StockItemAlias.query.filter_by(raw_description=desc).first()
    if a:
        a.itm_code = str(itm_code)
    else:
        db.session.add(StockItemAlias(raw_description=desc, itm_code=str(itm_code)))


def match_lines(lines: List[dict], catalog: List[dict]) -> List[dict]:
    """For each OCR line attach `match` (chosen item or None) and `candidates` (alternates)."""
    by_code = {str(it["code"]): it for it in catalog}
    out = []
    for ln in lines:
        desc = ln.get("raw_description", "")
        candidates = rank_match(desc, catalog)
        aliased = alias_lookup(desc)
        if aliased:
            cat = by_code.get(str(aliased))
            chosen = {"code": str(aliased), "title": cat["title"] if cat else "",
                      "subgroup": cat["subgroup"] if cat else "", "score": 1.0}
        else:
            chosen = candidates[0] if candidates else None
        out.append({**ln, "match": chosen, "candidates": candidates})
    return out
```

- [ ] **Step 4: Run, verify PASS (4 passed)**
`...python.exe -m pytest tests/test_helpers_invoice_match.py -v`

- [ ] **Step 5: Commit**
```bash
git add helpers_invoice_match.py tests/test_helpers_invoice_match.py
git commit -m "feat(stock): invoice line matching (fuzzy + alias memory)"
```

---

## Task 3: OCR helper (`helpers_invoice_ocr.py`)

**Files:**
- Create: `helpers_invoice_ocr.py`
- Modify: `config.py` (optional `OCR_MODEL`)
- Test: `tests/test_helpers_invoice_ocr.py`

- [ ] **Step 1: Add `OCR_MODEL` to `config.py`**

In `config.py`, in the `# ---- Optional ----` section (after the `DATABASE_URL` line), add:
```python
OCR_MODEL: str = os.getenv("OCR_MODEL", "gpt-4o")  # vision model for invoice OCR (not required)
```
Do NOT add it to `_REQUIRED_KEYS`.

- [ ] **Step 2: Write failing tests** — create `tests/test_helpers_invoice_ocr.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from helpers_invoice_ocr import _parse_lines, extract_invoice_lines


def test_parse_plain_json():
    txt = '{"lines": [{"raw_description": "ALMAZA 33CL", "qty": 24, "unit_cost": 1.5}]}'
    out = _parse_lines(txt)
    assert out == [{"raw_description": "ALMAZA 33CL", "qty": 24.0, "unit_cost": 1.5}]


def test_parse_strips_code_fences():
    txt = '```json\n{"lines": [{"raw_description": "PEPSI 1L", "qty": 6, "unit_cost": null}]}\n```'
    out = _parse_lines(txt)
    assert out[0]["raw_description"] == "PEPSI 1L"
    assert out[0]["qty"] == 6.0
    assert out[0]["unit_cost"] is None


def test_parse_skips_blank_descriptions_and_bad_numbers():
    txt = '{"lines": [{"raw_description": "", "qty": 1}, {"raw_description": "X", "qty": "abc", "unit_cost": "2"}]}'
    out = _parse_lines(txt)
    assert len(out) == 1
    assert out[0]["raw_description"] == "X"
    assert out[0]["qty"] is None
    assert out[0]["unit_cost"] == 2.0


def test_parse_bad_json_raises():
    with pytest.raises(ValueError):
        _parse_lines("not json at all")
    with pytest.raises(ValueError):
        _parse_lines('{"nope": 1}')


def test_extract_sends_image_and_parses(app=None):
    fake_resp = MagicMock()
    fake_resp.output_text = '{"lines": [{"raw_description": "WATER 500ML", "qty": 12, "unit_cost": 0.3}]}'
    fake_client = MagicMock()
    fake_client.responses.create.return_value = fake_resp
    with patch("helpers_invoice_ocr._get_client", return_value=fake_client):
        out = extract_invoice_lines(b"\xff\xd8fakejpeg", media_type="image/jpeg")
    assert out[0]["raw_description"] == "WATER 500ML"
    # the call included an input_image data URL
    kwargs = fake_client.responses.create.call_args.kwargs
    content = kwargs["input"][0]["content"]
    assert any(c.get("type") == "input_image" and c["image_url"].startswith("data:image/jpeg;base64,")
               for c in content)


def test_extract_empty_image_raises():
    with pytest.raises(ValueError):
        extract_invoice_lines(b"", media_type="image/jpeg")
```

- [ ] **Step 3: Run, verify FAIL**
`...python.exe -m pytest tests/test_helpers_invoice_ocr.py -v` → ModuleNotFoundError.

- [ ] **Step 4: Implement** — create `helpers_invoice_ocr.py`

```python
"""Read a supplier-invoice photo with OpenAI vision and return structured line items.

Reuses the project's OpenAI dependency (OPENAI_API_KEY already configured). The client
is isolated behind `_get_client()` so tests mock it (no live API). The image is passed
in memory as a base64 data URL and never persisted.
"""
from __future__ import annotations

import base64
import json
from typing import List, Optional

import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


_PROMPT = """You are reading a phone photo of a supplier delivery invoice for a Lebanese mini-market.
Extract every product line item. Return STRICT JSON only — no prose, no code fences — shaped exactly:
{"lines": [{"raw_description": "<item text exactly as printed>", "qty": <number or null>, "unit_cost": <number or null>}]}
Rules:
- raw_description: the item text exactly as printed.
- qty: quantity received as a number; null if unreadable.
- unit_cost: per-unit price/cost as a number (no currency symbols); null if not shown.
- Skip non-item lines (totals, taxes, headers, signatures, dates).
- If the invoice is unreadable, return {"lines": []}.
"""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_lines(text: str) -> List[dict]:
    """Parse the model's JSON reply into [{raw_description, qty, unit_cost}]. Raises ValueError."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:4].lower() == "json":
            s = s[4:].strip()
    try:
        data = json.loads(s)
    except (ValueError, TypeError) as e:
        raise ValueError(f"OCR did not return valid JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise ValueError("OCR JSON missing a 'lines' list")
    out = []
    for ln in data["lines"]:
        if not isinstance(ln, dict):
            continue
        desc = str(ln.get("raw_description") or "").strip()
        if not desc:
            continue
        out.append({"raw_description": desc, "qty": _num(ln.get("qty")),
                    "unit_cost": _num(ln.get("unit_cost"))})
    return out


def extract_invoice_lines(image_bytes: bytes, media_type: str = "image/jpeg",
                          model: Optional[str] = None) -> List[dict]:
    """OCR a supplier invoice image into structured line items via OpenAI vision."""
    if not image_bytes:
        raise ValueError("No image provided")
    data_url = f"data:{media_type};base64," + base64.b64encode(image_bytes).decode("ascii")
    resp = _get_client().responses.create(
        model=model or config.OCR_MODEL,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": _PROMPT},
            {"type": "input_image", "image_url": data_url},
        ]}],
        max_output_tokens=3000,
    )
    return _parse_lines(resp.output_text)
```

- [ ] **Step 5: Run, verify PASS (6 passed)**
`...python.exe -m pytest tests/test_helpers_invoice_ocr.py -v`

- [ ] **Step 6: Commit**
```bash
git add helpers_invoice_ocr.py config.py tests/test_helpers_invoice_ocr.py
git commit -m "feat(stock): OpenAI-vision invoice OCR helper"
```

---

## Task 4: Receive routes (extend `routes/stock.py`)

**Files:**
- Modify: `routes/stock.py`
- Test: `tests/test_routes_stock_receive.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_routes_stock_receive.py`

```python
import io
from datetime import date
from unittest.mock import patch

from models import db, StockItem, StockEvent, StockItemAlias

CATALOG = [
    {"code": "ALM330", "title": "ALMAZA BEER 330ML", "subgroup": "Beer"},
    {"code": "PEP1L", "title": "PEPSI 1L", "subgroup": "Soda"},
]


def _scan(client, lines):
    # mock OCR + catalog so no network/POS
    with patch("routes.stock.extract_invoice_lines", return_value=lines), \
         patch("routes.stock.load_catalog", return_value=CATALOG):
        return client.post("/api/stock/receive/scan",
                           data={"image": (io.BytesIO(b"\xff\xd8jpeg"), "inv.jpg")},
                           content_type="multipart/form-data")


def test_scan_returns_matched_lines(client):
    r = _scan(client, [{"raw_description": "ALMAZA 33", "qty": 24, "unit_cost": 1.5}])
    assert r.status_code == 200
    lines = r.get_json()["lines"]
    assert lines[0]["match"]["code"] == "ALM330"
    assert lines[0]["qty"] == 24


def test_scan_rejects_missing_image(client):
    r = client.post("/api/stock/receive/scan", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_confirm_adds_receive_to_tracked_item(client, app):
    # pre-track ALM330 with a count
    client.post("/api/stock/add", json={"itm_code": "ALM330", "qty": 10, "title": "Almaza", "subgroup": "Beer"})
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "ALM330", "title": "Almaza", "subgroup": "Beer",
         "qty": 24, "unit_cost": 1.5, "raw_description": "ALMAZA 33"},
    ]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["received"] == 1
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="ALM330").one()
        recv = StockEvent.query.filter_by(stock_item_id=si.id, event_type="receive").all()
        assert len(recv) == 1
        assert recv[0].qty == 24
        assert recv[0].unit_cost_cents == 150
        assert recv[0].source == "invoice"
        assert recv[0].batch_id == body["batch_id"]
        # alias remembered
        assert StockItemAlias.query.filter_by(raw_description="ALMAZA 33").one().itm_code == "ALM330"


def test_confirm_creates_count_baseline_for_untracked_item(client, app):
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "PEP1L", "title": "Pepsi 1L", "subgroup": "Soda",
         "qty": 6, "unit_cost": 2.0, "raw_description": "PEPSI 1L"},
    ]})
    assert r.status_code == 200
    with app.app_context():
        si = StockItem.query.filter_by(itm_code="PEP1L").one()
        evs = StockEvent.query.filter_by(stock_item_id=si.id).all()
        assert len(evs) == 1
        assert evs[0].event_type == "count"   # delivery becomes the baseline
        assert evs[0].qty == 6
        assert evs[0].unit_cost_cents == 200


def test_confirm_rejects_empty_lines(client):
    r = client.post("/api/stock/receive/confirm", json={"lines": []})
    assert r.status_code == 400


def test_undo_reverses_batch(client, app):
    # untracked confirm creates item + count under a batch
    r = client.post("/api/stock/receive/confirm", json={"lines": [
        {"itm_code": "PEP1L", "title": "Pepsi", "subgroup": "Soda",
         "qty": 6, "unit_cost": 2.0, "raw_description": "PEPSI 1L"},
    ]})
    batch = r.get_json()["batch_id"]
    u = client.post("/api/stock/receive/undo", json={"batch_id": batch})
    assert u.status_code == 200
    with app.app_context():
        # event gone; item (created solely by this batch, now event-less) removed
        assert StockEvent.query.filter_by(batch_id=batch).count() == 0
        assert StockItem.query.filter_by(itm_code="PEP1L").count() == 0
```

- [ ] **Step 2: Run, verify FAIL**
`...python.exe -m pytest tests/test_routes_stock_receive.py -v` → 404s / attribute errors (routes absent).

- [ ] **Step 3: Implement** — edit `routes/stock.py`.

Add imports near the top (after the existing `from helpers_items import ...` line):
```python
import uuid
from helpers_invoice_ocr import extract_invoice_lines
from helpers_invoice_match import load_catalog, match_lines, upsert_alias

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
```

Add these routes at the END of `routes/stock.py`:
```python
@stock_bp.get("/stock/receive")
def stock_receive_page():
    return render_template("stock_receive.html")


@stock_bp.post("/api/stock/receive/scan")
def api_stock_receive_scan():
    f = request.files.get("image")
    if f is None or not f.filename:
        return jsonify({"ok": False, "error": "no image uploaded"}), 400
    image_bytes = f.read()
    if not image_bytes:
        return jsonify({"ok": False, "error": "empty image"}), 400
    if len(image_bytes) > _MAX_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "image too large (max 15MB)"}), 413
    media_type = f.mimetype or "image/jpeg"
    try:
        lines = extract_invoice_lines(image_bytes, media_type=media_type)
    except Exception as e:
        log.exception("invoice OCR failed")
        return jsonify({"ok": False, "error": f"could not read invoice: {e}"}), 400
    catalog = load_catalog()
    matched = match_lines(lines, catalog)
    tracked = {s.itm_code for s in StockItem.query.filter_by(active=True).all()}
    for m in matched:
        code = (m.get("match") or {}).get("code")
        m["tracked"] = code in tracked if code else False
    return jsonify({"ok": True, "lines": matched})


@stock_bp.post("/api/stock/receive/confirm")
def api_stock_receive_confirm():
    data = _body()
    lines = data.get("lines") if isinstance(data, dict) else None
    if not lines:
        return jsonify({"ok": False, "error": "no lines to confirm"}), 400
    batch_id = uuid.uuid4().hex
    received = 0
    for ln in lines:
        itm_code = (str(ln.get("itm_code") or "")).strip()
        if not itm_code:
            continue
        try:
            qty = float(ln.get("qty"))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        raw_cost = ln.get("unit_cost")
        try:
            cost_cents = int(round(float(raw_cost) * 100)) if raw_cost not in (None, "") else None
        except (TypeError, ValueError):
            cost_cents = None
        title = (str(ln.get("title") or "")).strip()
        subgroup = (str(ln.get("subgroup") or "")).strip()

        si = StockItem.query.filter_by(itm_code=itm_code).first()
        if si and si.active:
            event_type = "receive"
        elif si and not si.active:
            si.active = True
            event_type = "receive"
        else:
            si = StockItem(itm_code=itm_code, title=title, subgroup=subgroup,
                           alert_threshold=_default_threshold(), active=True)
            db.session.add(si)
            db.session.flush()
            event_type = "count"  # first delivery is the baseline for a new item
        db.session.add(StockEvent(stock_item_id=si.id, event_type=event_type, qty=qty,
                                  event_date=date.today(), source="invoice",
                                  unit_cost_cents=cost_cents, batch_id=batch_id))
        raw = (str(ln.get("raw_description") or "")).strip()
        if raw:
            upsert_alias(raw, itm_code)
        received += 1
    if received == 0:
        db.session.rollback()
        return jsonify({"ok": False, "error": "no valid lines"}), 400
    db.session.commit()
    return jsonify({"ok": True, "batch_id": batch_id, "received": received})


@stock_bp.post("/api/stock/receive/undo")
def api_stock_receive_undo():
    data = _body()
    batch_id = (str(data.get("batch_id") or "")).strip()
    if not batch_id:
        return jsonify({"ok": False, "error": "batch_id required"}), 400
    events = StockEvent.query.filter_by(batch_id=batch_id).all()
    affected = {e.stock_item_id for e in events}
    for e in events:
        db.session.delete(e)
    db.session.flush()
    removed_items = 0
    for sid in affected:
        if StockEvent.query.filter_by(stock_item_id=sid).count() == 0:
            si = db.session.get(StockItem, sid)
            if si is not None:
                db.session.delete(si)
                removed_items += 1
    db.session.commit()
    return jsonify({"ok": True, "events_removed": len(events), "items_removed": removed_items})
```

- [ ] **Step 4: Run, verify PASS (6 passed)** then full suite for regressions.
`...python.exe -m pytest tests/test_routes_stock_receive.py -v`
`...python.exe -m pytest tests/ -q`

- [ ] **Step 5: Commit**
```bash
git add routes/stock.py tests/test_routes_stock_receive.py
git commit -m "feat(stock): invoice receive routes (scan/confirm/undo)"
```

---

## Task 5: Receive page UI + button

UI task; verification is a render check + the receive route smoke. Read `templates/stock.html` and `templates/base.html` first to match conventions (block `content`, Bootstrap).

**Files:**
- Create: `templates/stock_receive.html`
- Modify: `templates/stock.html` (add a "Receive from invoice" button)

- [ ] **Step 1: Add the button in `templates/stock.html`**

In the header `<div class="d-flex justify-content-between ...">` that contains `<h4 ...>Stock</h4>` and `#alertBanner`, change it so the right side has both the banner and a button. Replace the `<div id="alertBanner" ...></div>` line with:
```html
    <div class="d-flex align-items-center gap-3">
      <div id="alertBanner" class="text-muted small"></div>
      <a href="/stock/receive" class="btn btn-sm btn-success"><i class="bi bi-upload"></i> Receive from invoice</a>
    </div>
```

- [ ] **Step 2: Create `templates/stock_receive.html`**

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-3" id="receiveApp">
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <h4 class="mb-0"><i class="bi bi-upload"></i> Receive from invoice</h4>
    <a href="/stock" class="btn btn-sm btn-outline-secondary">← Back to Stock</a>
  </div>

  <div class="card mb-3">
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div class="col-12 col-md-8">
          <label class="form-label small mb-1">Invoice photo (JPG/PNG)</label>
          <input id="fileInput" type="file" accept="image/*" class="form-control">
        </div>
        <div class="col-12 col-md-4">
          <button id="scanBtn" class="btn btn-primary w-100"><i class="bi bi-magic"></i> Read invoice</button>
        </div>
      </div>
      <div id="scanStatus" class="small text-muted mt-2"></div>
    </div>
  </div>

  <div id="reviewWrap"></div>
</div>

<script>
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
let LINES = [];

async function scan(){
  const f = document.getElementById("fileInput").files[0];
  if(!f){ alert("Choose a photo first."); return; }
  const status = document.getElementById("scanStatus");
  const btn = document.getElementById("scanBtn");
  btn.disabled = true; status.textContent = "Reading invoice… this can take a few seconds.";
  try{
    const fd = new FormData(); fd.append("image", f);
    const r = await fetch("/api/stock/receive/scan", {method:"POST", body:fd});
    const d = await r.json();
    if(!r.ok || !d.ok){ status.innerHTML = '<span class="text-danger">'+esc(d.error||"Failed to read invoice.")+'</span>'; return; }
    LINES = d.lines || [];
    status.textContent = `Found ${LINES.length} line(s). Review and confirm below.`;
    renderReview();
  }catch(e){ status.innerHTML = '<span class="text-danger">Network error.</span>'; }
  finally{ btn.disabled = false; }
}

function lineRow(ln, i){
  const m = ln.match || null;
  const matchLabel = m ? `${esc(m.title || m.code)} <span class="text-muted">(${esc(m.code)})</span>` : '<span class="text-danger">No match — search</span>';
  const badge = m ? (ln.tracked ? '<span class="badge bg-secondary">Tracked</span>' : '<span class="badge bg-info">New</span>') : '';
  return `<tr data-i="${i}">
    <td><div class="small text-muted">${esc(ln.raw_description)}</div></td>
    <td>${matchLabel} ${badge}
        <div><input class="form-control form-control-sm mt-1 matchSearch" placeholder="change match…" style="max-width:240px"></div>
        <div class="matchResults"></div></td>
    <td><input type="number" min="0" step="1" value="${ln.qty ?? ''}" class="form-control form-control-sm qtyIn" style="width:90px"></td>
    <td><input type="number" min="0" step="0.01" value="${ln.unit_cost ?? ''}" class="form-control form-control-sm costIn" style="width:100px"></td>
    <td><button class="btn btn-sm btn-outline-danger dropBtn">Drop</button></td>
  </tr>`;
}

function renderReview(){
  const wrap = document.getElementById("reviewWrap");
  if(!LINES.length){ wrap.innerHTML = '<div class="text-muted">No line items found.</div>'; return; }
  wrap.innerHTML = `
    <div class="table-responsive"><table class="table align-middle">
      <thead><tr><th>Invoice text</th><th>Matched item</th><th>Qty</th><th>Unit cost</th><th></th></tr></thead>
      <tbody>${LINES.map(lineRow).join("")}</tbody>
    </table></div>
    <button id="confirmBtn" class="btn btn-success"><i class="bi bi-check2-circle"></i> Confirm & add to stock</button>
    <div id="confirmStatus" class="mt-2 small"></div>`;

  wrap.querySelectorAll(".dropBtn").forEach(b => b.addEventListener("click", e => {
    const tr = e.currentTarget.closest("tr"); LINES.splice(+tr.dataset.i, 1); renderReview();
  }));
  wrap.querySelectorAll(".qtyIn").forEach(inp => inp.addEventListener("change", e => {
    LINES[+e.currentTarget.closest("tr").dataset.i].qty = parseFloat(e.currentTarget.value);
  }));
  wrap.querySelectorAll(".costIn").forEach(inp => inp.addEventListener("change", e => {
    const v = parseFloat(e.currentTarget.value); LINES[+e.currentTarget.closest("tr").dataset.i].unit_cost = isNaN(v)?null:v;
  }));
  wrap.querySelectorAll(".matchSearch").forEach(inp => inp.addEventListener("keyup", debounceSearch));
  document.getElementById("confirmBtn").addEventListener("click", confirmReceive);
}

let searchTimer = null;
function debounceSearch(e){
  clearTimeout(searchTimer);
  const inp = e.currentTarget;
  searchTimer = setTimeout(async () => {
    const q = inp.value.trim(); if(q.length < 2) return;
    const tr = inp.closest("tr");
    const d = await (await fetch(`/api/stock/search?q=${encodeURIComponent(q)}`)).json();
    const box = tr.querySelector(".matchResults");
    box.innerHTML = (d.items||[]).slice(0,6).map(it =>
      `<button class="btn btn-sm btn-outline-primary me-1 mt-1 pickBtn" data-code="${encodeURIComponent(it.code)}" data-title="${encodeURIComponent(it.title||'')}" data-subgroup="${encodeURIComponent(it.subgroup||'')}">${esc(it.title||it.code)}</button>`
    ).join("");
    box.querySelectorAll(".pickBtn").forEach(b => b.addEventListener("click", ev => {
      const i = +tr.dataset.i, ds = ev.currentTarget.dataset;
      LINES[i].match = {code: decodeURIComponent(ds.code), title: decodeURIComponent(ds.title), subgroup: decodeURIComponent(ds.subgroup), score: 1};
      renderReview();
    }));
  }, 350);
}

async function confirmReceive(){
  const payload = {lines: LINES.filter(l => l.match && l.qty > 0).map(l => ({
    itm_code: l.match.code, title: l.match.title, subgroup: l.match.subgroup,
    qty: l.qty, unit_cost: l.unit_cost, raw_description: l.raw_description,
  }))};
  const status = document.getElementById("confirmStatus");
  if(!payload.lines.length){ status.innerHTML = '<span class="text-danger">Nothing to confirm — match items and set quantities.</span>'; return; }
  const r = await fetch("/api/stock/receive/confirm", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  const d = await r.json();
  if(r.ok && d.ok){
    status.innerHTML = `<span class="text-success">Added ${d.received} item(s) to stock.</span>
      <button class="btn btn-sm btn-outline-danger ms-2" id="undoBtn">Undo</button>
      <a class="btn btn-sm btn-primary ms-1" href="/stock">View stock</a>`;
    document.getElementById("undoBtn").addEventListener("click", async () => {
      await fetch("/api/stock/receive/undo", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({batch_id: d.batch_id})});
      status.innerHTML = '<span class="text-muted">Import undone.</span>';
    });
    LINES = []; document.querySelector("#reviewWrap table tbody").innerHTML = "";
  } else {
    status.innerHTML = '<span class="text-danger">'+esc(d.error||"Failed.")+'</span>';
  }
}

document.getElementById("scanBtn").addEventListener("click", scan);
</script>
{% endblock %}
```

- [ ] **Step 3: Verify both templates render against the real app** (dummy env, like Phase 1 Task 5)

```bash
"C:/Users/majd/Documents/PyCharm Projects/checkout-cash-flow/.venv/Scripts/python.exe" - <<'PYEOF'
import os
for k,v in {"MSSQL_DRIVER":"ODBC Driver 17 for SQL Server","MSSQL_SERVER":"x,1433","MSSQL_DATABASE":"D","MSSQL_USERNAME":"u","MSSQL_PASSWORD":"p","SECRET_KEY":"s","APP_USERNAME":"a","APP_PASSWORD":"b","VISUAL_CROSSING_KEY":"k","OPENAI_API_KEY":"o","USD_EXCHANGE_RATE":"89000","CURRENCY":"LBP","MIN_TRACKING_DATE":"2026-04-11","LICENSE_SERVER_URL":"http://localhost:5001","SUPPORT_CONTACT":"+961"}.items(): os.environ.setdefault(k,v)
import main
with main.app.app_context(), main.app.test_request_context("/stock/receive"):
    from flask import render_template
    a = render_template("stock_receive.html"); b = render_template("stock.html")
assert 'id="receiveApp"' in a and "/api/stock/receive/scan" in a
assert "/stock/receive" in b and "Receive from invoice" in b
print("render OK", len(a), len(b))
PYEOF
```
Expected: `render OK <n> <n>` with no traceback.

- [ ] **Step 4: Commit**
```bash
git add templates/stock_receive.html templates/stock.html
git commit -m "feat(stock): invoice receive page + button"
```

---

## Task 6: Final verification

- [ ] **Step 1: Full app suite**
`...python.exe -m pytest tests/ -q` → all pass (Phase 1 + Phase 2 stock tests + pre-existing).

- [ ] **Step 2: Additive table creation**
```bash
"C:/Users/majd/Documents/PyCharm Projects/checkout-cash-flow/.venv/Scripts/python.exe" - <<'PYEOF'
from flask import Flask
import models
a = Flask(__name__); a.config["SQLALCHEMY_DATABASE_URI"]="sqlite:///:memory:"; a.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
models.db.init_app(a)
with a.app_context():
    models.db.create_all()
    from sqlalchemy import inspect
    insp = inspect(models.db.engine)
    tabs = set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("stock_events")}
print("tables:", sorted(tabs)); print("stock_events cols:", sorted(cols))
assert "stock_item_aliases" in tabs
assert {"unit_cost_cents","batch_id"} <= cols
print("ADDITIVE OK")
PYEOF
```

- [ ] **Step 3: Smoke the receive routes via main.app test client** (auth + blueprint registration; OCR/catalog mocked)
```bash
"C:/Users/majd/Documents/PyCharm Projects/checkout-cash-flow/.venv/Scripts/python.exe" - <<'PYEOF'
import os
for k,v in {"MSSQL_DRIVER":"ODBC Driver 17 for SQL Server","MSSQL_SERVER":"x,1433","MSSQL_DATABASE":"D","MSSQL_USERNAME":"u","MSSQL_PASSWORD":"p","SECRET_KEY":"s","APP_USERNAME":"a","APP_PASSWORD":"b","VISUAL_CROSSING_KEY":"k","OPENAI_API_KEY":"o","USD_EXCHANGE_RATE":"89000","CURRENCY":"LBP","MIN_TRACKING_DATE":"2026-04-11","LICENSE_SERVER_URL":"http://localhost:5001","SUPPORT_CONTACT":"+961"}.items(): os.environ.setdefault(k,v)
import main
rules = sorted(r.rule for r in main.app.url_map.iter_rules() if "receive" in r.rule)
print("receive routes:", rules)
assert "/stock/receive" in rules and "/api/stock/receive/scan" in rules and "/api/stock/receive/confirm" in rules
print("SMOKE OK")
PYEOF
```

- [ ] **Step 4: Commit (if any tweaks)**
```bash
git add -A && git commit -m "chore(stock): Phase 2 verification" || echo "nothing to commit"
```

---

## Self-Review notes
- **Spec coverage:** OCR via OpenAI (T3) ✓; phone-photo upload + size guard (T4) ✓; item+qty+cost capture as cents (T1 cols, T4 confirm) ✓; mandatory review (T5 UI, no DB write on scan) ✓; alias memory (T1 table, T2 helpers, T4 upsert) ✓; receive vs count-baseline semantics (T4) ✓; batch undo (T4) ✓; one cached POS query for matching (T2 load_catalog) ✓; no new required config key (T3 optional OCR_MODEL) ✓; additive migration (T6) ✓.
- **Types consistent:** `extract_invoice_lines`/`_parse_lines`/`load_catalog`/`match_lines`/`rank_match`/`alias_lookup`/`upsert_alias` signatures match call sites in `routes/stock.py`. Line dict keys (`raw_description`,`qty`,`unit_cost`,`match`,`candidates`,`tracked`) match the template JS and the confirm payload (`itm_code`,`title`,`subgroup`,`qty`,`unit_cost`,`raw_description`).
- **Money:** `unit_cost_cents = int(round(unit_cost*100))`, nullable.
- **No image persistence:** scan reads bytes in memory, discards after OCR.
