from datetime import date, datetime
from types import SimpleNamespace

from helpers_stock import (
    latest_count,
    receives_after,
    status_for,
    compute_live,
    build_units_sold_query,
    count_window_start,
)


def _ev(event_type, qty, event_date, created_at, counted_at=None):
    return SimpleNamespace(event_type=event_type, qty=qty,
                           event_date=event_date, created_at=created_at,
                           counted_at=counted_at)


def test_count_window_start_uses_counted_at_when_present():
    # A 15:00 count -> the window starts at the exact count moment, NOT 08:00,
    # so morning sales already in the counted number are not re-deducted.
    ts = datetime(2026, 6, 14, 15, 30)
    ev = _ev("count", 20, date(2026, 6, 14), datetime(2026, 6, 14, 15, 30), counted_at=ts)
    assert count_window_start(ev) == ts


def test_count_window_start_falls_back_to_0800_for_legacy_counts():
    # Legacy count with no counted_at -> business-day 08:00 boundary (old behaviour).
    ev = _ev("count", 20, date(2026, 6, 14), datetime(2026, 6, 14, 8), counted_at=None)
    assert count_window_start(ev) == datetime(2026, 6, 14, 8, 0, 0)


def test_latest_count_picks_newest_by_date_then_created_at():
    a = _ev("count", 10, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    b = _ev("count", 22, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    c = _ev("count", 30, date(2026, 6, 8), datetime(2026, 6, 8, 9))  # same day, later
    assert latest_count([a, b, c]) is c
    assert latest_count([]) is None


def test_status_boundaries():
    assert status_for(0, 5) == "out"
    assert status_for(-3, 5) == "out"
    assert status_for(5, 5) == "low"
    assert status_for(1, 5) == "low"
    assert status_for(6, 5) == "ok"


def test_compute_live_count_only_deducts_sales():
    # Almaza: counted 22 today, sold 4 -> 18
    ev = _ev("count", 22, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    info = compute_live([ev], sold_units=4, threshold=6)
    assert info["live"] == 18
    assert info["status"] == "ok"
    assert info["q0"] == 22
    assert info["d0"] == date(2026, 6, 8)
    assert info["has_baseline"] is True


def test_compute_live_net_of_returns_adds_back():
    ev = _ev("count", 10, date(2026, 6, 8), datetime(2026, 6, 8, 8))
    # net sold negative => a return => stock goes UP
    info = compute_live([ev], sold_units=-2, threshold=5)
    assert info["live"] == 12


def test_compute_live_includes_receives_after_count():
    count = _ev("count", 6, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    recv = _ev("receive", 24, date(2026, 6, 5), datetime(2026, 6, 5, 10))
    info = compute_live([count, recv], sold_units=10, threshold=5)
    # 6 + 24 - 10 = 20
    assert info["live"] == 20
    assert info["receives"] == 24


def test_compute_live_ignores_receives_before_latest_count():
    old_recv = _ev("receive", 100, date(2026, 5, 1), datetime(2026, 5, 1, 10))
    count = _ev("count", 8, date(2026, 6, 1), datetime(2026, 6, 1, 8))
    info = compute_live([old_recv, count], sold_units=3, threshold=5)
    # receive predates the count baseline -> ignored. 8 - 3 = 5 (low)
    assert info["live"] == 5
    assert info["status"] == "low"
    assert info["receives"] == 0


def test_compute_live_no_baseline():
    info = compute_live([], sold_units=0, threshold=5)
    assert info["has_baseline"] is False
    assert info["live"] is None
    assert info["status"] == "unknown"


def test_build_units_sold_query_param_shape():
    pairs = (("ALM330", datetime(2026, 6, 8, 8)), ("PEPSI1L", datetime(2026, 6, 7, 8)))
    sql, params = build_units_sold_query(pairs)
    # one (?,?) values row per pair
    assert sql.count("(?, ?)") == 2
    # params are flattened code, start, code, start (positional)
    assert params == ["ALM330", datetime(2026, 6, 8, 8), "PEPSI1L", datetime(2026, 6, 7, 8)]
    assert "HISTORIC_RECEIPT_CONTENTS" in sql
    assert "SUM(c.ITM_QUANTITY)" in sql
    assert "r.RCPT_DATE >= v.win_start" in sql


def test_build_units_sold_query_empty():
    sql, params = build_units_sold_query(())
    assert sql == ""
    assert params == []
