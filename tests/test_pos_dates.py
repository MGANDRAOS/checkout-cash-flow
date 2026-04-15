from datetime import date, datetime
import pytest
from pos_dates import biz_date_range_8h, biz_date_range_7h, cutoff_dt_8h, cutoff_dt_7h


def test_8h_start():
    start, _ = biz_date_range_8h(date(2026, 4, 14))
    assert start == datetime(2026, 4, 14, 8, 0, 0)

def test_8h_end():
    _, end = biz_date_range_8h(date(2026, 4, 14))
    assert end == datetime(2026, 4, 15, 8, 0, 0)

def test_7h_start():
    start, _ = biz_date_range_7h(date(2026, 4, 14))
    assert start == datetime(2026, 4, 14, 7, 0, 0)

def test_7h_end():
    _, end = biz_date_range_7h(date(2026, 4, 14))
    assert end == datetime(2026, 4, 15, 7, 0, 0)

def test_cutoff_8h_is_datetime():
    result = cutoff_dt_8h(30)
    assert isinstance(result, datetime)
    assert result.hour == 8

def test_cutoff_7h_is_datetime():
    result = cutoff_dt_7h(30)
    assert isinstance(result, datetime)
    assert result.hour == 7

def test_cutoff_8h_is_days_ago():
    from datetime import timedelta
    result = cutoff_dt_8h(30)
    expected_date = datetime.now().date() - timedelta(days=31)  # +1 buffer
    assert result.date() == expected_date

def test_cutoff_7h_is_days_ago():
    from datetime import timedelta
    result = cutoff_dt_7h(30)
    expected_date = datetime.now().date() - timedelta(days=31)
    assert result.date() == expected_date
