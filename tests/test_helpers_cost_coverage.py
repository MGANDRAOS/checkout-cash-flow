from helpers_intelligence import _cost_coverage_summary


def _rows():
    return [
        {"item_code": "A", "item": "Fantasia XL", "subgroup": "Snacks",
         "qty": 316.0, "revenue": 31600000.0, "avg_price": 100000.0, "last_sold": "2026-06-15"},
        {"item_code": "B", "item": "Reva Tissues", "subgroup": "Home",
         "qty": 126.0, "revenue": 12600000.0, "avg_price": 100000.0, "last_sold": "2026-06-14"},
    ]


def test_coverage_pct_and_at_risk():
    out = _cost_coverage_summary(active=3014, uncosted_active=1064,
                                 dormant_uncosted=931, rows=_rows())
    # (3014 - 1064) / 3014 * 100 = 64.7
    assert out["coverage"]["coverage_pct"] == 64.7
    assert out["coverage"]["active"] == 3014
    assert out["coverage"]["uncosted_active"] == 1064
    assert out["dormant_uncosted"] == 931
    # at_risk derived from rows
    assert out["at_risk"]["items"] == 2
    assert out["at_risk"]["revenue"] == 44200000.0


def test_rows_sorted_by_revenue_desc():
    unsorted = list(reversed(_rows()))
    out = _cost_coverage_summary(active=10, uncosted_active=2,
                                 dormant_uncosted=0, rows=unsorted)
    assert [r["item_code"] for r in out["rows"]] == ["A", "B"]


def test_empty_rows():
    out = _cost_coverage_summary(active=100, uncosted_active=0,
                                 dormant_uncosted=0, rows=[])
    assert out["coverage"]["coverage_pct"] == 100.0
    assert out["at_risk"] == {"items": 0, "revenue": 0.0}
    assert out["rows"] == []


def test_zero_active_no_divide_by_zero():
    out = _cost_coverage_summary(active=0, uncosted_active=0,
                                 dormant_uncosted=0, rows=[])
    assert out["coverage"]["coverage_pct"] == 0.0
