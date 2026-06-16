from helpers_intelligence import _summarize_items_sold


def test_empty_rows_returns_zero_totals():
    out = _summarize_items_sold([])
    assert out["rows"] == []
    assert out["totals"] == {
        "items": 0, "qty": 0.0, "revenue": 0.0,
        "cost": 0.0, "profit": 0.0, "costed_revenue": 0.0,
        "margin": 0.0, "uncosted_items": 0,
    }


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
    assert out["totals"]["items"] == 2
    assert out["totals"]["qty"] == 50.0
    assert out["totals"]["revenue"] == 400.0
    # no unit_cost on these rows -> all uncosted
    assert out["totals"]["uncosted_items"] == 2
    assert out["totals"]["cost"] == 0.0
    assert round(sum(r["share"] for r in out["rows"]), 1) == 100.0


def test_zero_revenue_has_no_divide_by_zero():
    raw = [{"subgroup": "X", "item_code": "Z", "item": "Free",
            "qty": 0.0, "revenue": 0.0, "avg_price": 0.0, "txns": 1}]
    out = _summarize_items_sold(raw)
    assert out["rows"][0]["share"] == 0.0
    assert out["totals"]["revenue"] == 0.0
    assert out["totals"]["margin"] == 0.0


def test_cost_profit_margin_computed_per_row_and_totals():
    raw = [
        {"subgroup": "Beer", "item_code": "A", "item": "Almaza",
         "qty": 10.0, "revenue": 1000.0, "avg_price": 100.0, "txns": 5, "unit_cost": 60.0},
        {"subgroup": "Soft", "item_code": "B", "item": "Cola",
         "qty": 20.0, "revenue": 400.0, "avg_price": 20.0, "txns": 8, "unit_cost": 25.0},
    ]
    out = _summarize_items_sold(raw)
    by = {r["item_code"]: r for r in out["rows"]}
    # A: cost 60*10=600, profit 1000-600=400, margin 40%
    assert by["A"]["total_cost"] == 600.0
    assert by["A"]["profit"] == 400.0
    assert by["A"]["margin"] == 40.0
    # B sold below cost: cost 25*20=500, profit 400-500=-100, margin -25%
    assert by["B"]["total_cost"] == 500.0
    assert by["B"]["profit"] == -100.0
    assert by["B"]["margin"] == -25.0
    t = out["totals"]
    assert t["cost"] == 1100.0
    assert t["profit"] == 300.0
    assert t["costed_revenue"] == 1400.0
    assert t["margin"] == round(300.0 / 1400.0 * 100, 1)  # 21.4
    assert t["uncosted_items"] == 0


def test_unknown_cost_excluded_from_profit():
    raw = [
        {"subgroup": "X", "item_code": "A", "item": "Costed",
         "qty": 10.0, "revenue": 1000.0, "avg_price": 100.0, "txns": 1, "unit_cost": 60.0},
        {"subgroup": "X", "item_code": "B", "item": "NoCost",
         "qty": 5.0, "revenue": 500.0, "avg_price": 100.0, "txns": 1, "unit_cost": None},
    ]
    out = _summarize_items_sold(raw)
    by = {r["item_code"]: r for r in out["rows"]}
    assert by["B"]["unit_cost"] is None
    assert by["B"]["total_cost"] is None
    assert by["B"]["profit"] is None
    assert by["B"]["margin"] is None
    t = out["totals"]
    # only A counted: cost 600, profit 400, costed_revenue 1000 -> margin 40
    assert t["cost"] == 600.0
    assert t["profit"] == 400.0
    assert t["costed_revenue"] == 1000.0
    assert t["margin"] == 40.0
    assert t["uncosted_items"] == 1
