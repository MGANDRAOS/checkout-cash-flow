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
