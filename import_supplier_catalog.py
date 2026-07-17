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

# NOTE: main/db/models are imported lazily inside import_supplier() and the
# __main__ block below, not at module scope. main.py calls load_dotenv() on
# import, which (in local dev, where .env has LICENSE_ENFORCE=false) leaks
# that env var process-wide -- fine for a one-shot script, but it broke
# tests/test_license_middleware.py when this module got imported during a
# pytest session (test_import_supplier_catalog.py imports this module to
# unit-test the pure parsing functions below, which need no Flask/DB context
# at all). Keeping the Flask/DB import out of module scope keeps those tests
# import-free of main.py.


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
    from models import Supplier, SupplierItem
    from main import db

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
    from main import app, db

    with app.app_context():
        db.create_all()
        for i in range(0, len(args), 2):
            supplier_name, path = args[i], args[i + 1]
            n = import_supplier(supplier_name, path)
            print(f"{supplier_name}: {n} items imported from {path}")
