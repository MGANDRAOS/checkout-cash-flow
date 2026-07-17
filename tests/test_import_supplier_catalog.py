from datetime import date

import openpyxl

from import_supplier_catalog import _to_cents, _parse_date, parse_workbook


def test_to_cents_none():
    assert _to_cents(None) is None


def test_to_cents_simple():
    assert _to_cents(21.85) == 2185


def test_to_cents_rounds_correctly():
    # actual per-unit price format from the real spreadsheets
    assert _to_cents(0.910416666666667) == 91


def test_parse_date_none():
    assert _parse_date(None) is None


def test_parse_date_string():
    assert _parse_date("06/06/2026") == date(2026, 6, 6)


def test_parse_date_passthrough_date_object():
    d = date(2026, 6, 6)
    assert _parse_date(d) == d


def _build_workbook(tmp_path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    path = tmp_path / "catalog.xlsx"
    wb.save(str(path))
    return str(path)


def test_parse_workbook_basic_layout(tmp_path):
    rows = [
        ("Rate: 89500", None, None, None, None, None, None, None),
        ("Box4Less Master Price List", None, None, None, None, None, None, None),
        (None, None, None, None, None, None, None, None),
        ("Item", "Format / Pcs per Pack", "Case Price ($)", "Unit Price ($)",
         "Unit Price (LBP)", "Source", "Date", "Notes"),
        ("BEER", None, None, None, None, None, None, None),
        ("Almaza Can 33cl", "24 cans", 21.85, 0.910416666666667, 81_477,
         "INV-123", "06/06/2026", "chilled"),
    ]
    path = _build_workbook(tmp_path, rows)

    out = list(parse_workbook(path))

    assert len(out) == 1
    item = out[0]
    assert item["name"] == "Almaza Can 33cl"
    assert item["category"] == "BEER"
    assert item["format_label"] == "24 cans"
    assert item["case_price_usd_cents"] == 2185
    assert item["unit_price_usd_cents"] == 91
    assert item["source_ref"] == "INV-123"
    assert item["source_date"] == date(2026, 6, 6)
    assert item["notes"] == "chilled"


def test_parse_workbook_multiple_categories_and_items(tmp_path):
    rows = [
        ("Rate: 89500", None, None, None, None, None, None, None),
        ("Nice Food Master Price List", None, None, None, None, None, None, None),
        (None, None, None, None, None, None, None, None),
        ("Item", "Format", "Case Price", "Unit Price", "Unit Price LBP", "Source", "Date", "Notes"),
        ("BEER", None, None, None, None, None, None, None),
        ("Almaza Can 33cl", "24 cans", 20.00, 0.92, 82_340, "INV-1", "01/01/2026", None),
        ("SNACKS", None, None, None, None, None, None, None),
        ("Chips 50g", "1 pc", None, 1.5, 134_250, "INV-2", "02/01/2026", "spicy"),
    ]
    path = _build_workbook(tmp_path, rows)

    out = list(parse_workbook(path))

    assert len(out) == 2
    assert out[0]["name"] == "Almaza Can 33cl"
    assert out[0]["category"] == "BEER"
    assert out[1]["name"] == "Chips 50g"
    assert out[1]["category"] == "SNACKS"
    assert out[1]["case_price_usd_cents"] is None
    assert out[1]["unit_price_usd_cents"] == 150


def test_parse_workbook_item_row_with_blank_format_and_case_price_is_not_a_category(tmp_path):
    # A row with unit_price present but fmt/case_price both None must still be
    # treated as an item, not misclassified as a category row -- the
    # category-vs-item distinction hinges on unit_price being None.
    rows = [
        ("Rate: 89500", None, None, None, None, None, None, None),
        ("Title", None, None, None, None, None, None, None),
        (None, None, None, None, None, None, None, None),
        ("Item", "Format", "Case Price", "Unit Price", "Unit Price LBP", "Source", "Date", "Notes"),
        ("Mystery Item", None, None, 2.5, None, None, None, None),
    ]
    path = _build_workbook(tmp_path, rows)

    out = list(parse_workbook(path))

    assert len(out) == 1
    assert out[0]["name"] == "Mystery Item"
    assert out[0]["unit_price_usd_cents"] == 250
