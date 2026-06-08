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
        assert out[0]["match"]["code"] == "WTR05"
        assert out[1]["match"]["code"] == "PEP1L"
        assert out[0]["qty"] == 5
