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
