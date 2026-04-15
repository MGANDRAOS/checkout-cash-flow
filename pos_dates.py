"""
Sargable date range utilities for POS receipt queries.

HISTORIC_RECEIPT.RCPT_DATE holds raw timestamps. Wrapping RCPT_DATE in a CASE
expression inside a WHERE clause (the old BUSINESS_DATE_SQL pattern) prevents
SQL Server from using the index on RCPT_DATE — causing full table scans.

These functions convert a business date into an explicit datetime range so queries
can use WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ? — index-friendly.

Two boundaries are preserved (existing codebase convention):
  - 08:00 boundary: helpers_sales.py and helpers_realtime.py
  - 07:00 boundary: helpers_intelligence.py (matches its DATEADD(HOUR,-7,...) shift)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def biz_date_range_8h(d: date) -> tuple[datetime, datetime]:
    """
    Business date range with 08:00 boundary (sales/realtime helpers).

    Business day [d] spans:  d @ 08:00:00  to  (d+1) @ 08:00:00 (exclusive)
    Returns (inclusive_start, exclusive_end).

    SQL usage:
        start, end = biz_date_range_8h(d)
        WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?   -- params: (start, end)
    """
    start = datetime(d.year, d.month, d.day, 8, 0, 0)
    return start, start + timedelta(days=1)


def biz_date_range_7h(d: date) -> tuple[datetime, datetime]:
    """
    Business date range with 07:00 boundary (intelligence helpers).

    Business day [d] spans:  d @ 07:00:00  to  (d+1) @ 07:00:00 (exclusive)
    Returns (inclusive_start, exclusive_end).

    SQL usage:
        start, end = biz_date_range_7h(d)
        WHERE r.RCPT_DATE >= ? AND r.RCPT_DATE < ?   -- params: (start, end)
    """
    start = datetime(d.year, d.month, d.day, 7, 0, 0)
    return start, start + timedelta(days=1)


def cutoff_dt_8h(days: int) -> datetime:
    """
    Rolling window cutoff using 08:00 boundary.
    Returns the earliest RCPT_DATE to include when looking back <days> business days.
    Adds 1 extra buffer day to account for the partial current business day.

    SQL usage:
        cutoff = cutoff_dt_8h(30)
        WHERE r.RCPT_DATE >= ?    -- param: cutoff
    """
    cutoff_date = datetime.now().date() - timedelta(days=days + 1)
    return datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day, 8, 0, 0)


def cutoff_dt_7h(days: int) -> datetime:
    """
    Rolling window cutoff using 07:00 boundary.
    Returns the earliest RCPT_DATE to include when looking back <days> business days.
    Adds 1 extra buffer day to account for the partial current business day.

    SQL usage:
        cutoff = cutoff_dt_7h(30)
        WHERE r.RCPT_DATE >= ?    -- param: cutoff
    """
    cutoff_date = datetime.now().date() - timedelta(days=days + 1)
    return datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day, 7, 0, 0)
