import calendar
from datetime import date
from dataclasses import dataclass
from typing import Dict, Tuple
from models import db, Envelope, EnvelopeTransaction, FixedBill


# ───────────────────────────────
# Money utilities
# ───────────────────────────────
def dollars_to_cents(value: str) -> int:
    """Convert string like '123.45' to integer cents (12345)."""
    clean = (value or "").replace(",", "").strip()
    return int(round(float(clean) * 100))


def cents_to_dollars(cents: int) -> str:
    """Convert integer cents to display string like '123.45'."""
    return f"{cents / 100:.2f}"


# ───────────────────────────────
# Date utility
# ───────────────────────────────
def days_in_month(year: int, month: int) -> int:
    """Return number of days in a given month."""
    return calendar.monthrange(year, month)[1]


# ───────────────────────────────
# Envelope management
# ───────────────────────────────
def ensure_default_envelopes():
    """Create default envelopes if missing."""
    defaults = [
        ("INVENTORY", "Inventory"),
        ("FIXED", "Fixed Reserve"),
        ("OPS", "Operations (3%)"),
        ("BUFFER", "Buffer"),
    ]
    for code, name in defaults:
        exists = db.session.scalar(
            db.select(db.func.count()).select_from(Envelope).where(Envelope.code == code)
        )
        if exists == 0:
            db.session.add(Envelope(code=code, name=name, balance_cents=0))
    db.session.commit()


def post_envelope_tx(code: str, amount: int, tx_type: str, desc: str, closing_id=None):
    """Record a transaction into an envelope and update its balance."""
    env = db.session.scalar(db.select(Envelope).where(Envelope.code == code))
    if not env:
        raise RuntimeError(f"Envelope {code} missing. Run ensure_default_envelopes().")
    env.balance_cents += amount
    db.session.add(
        EnvelopeTransaction(
            envelope_id=env.id,
            daily_closing_id=closing_id,
            type=tx_type,
            amount_cents=amount,
            description=desc,
        )
    )


# ───────────────────────────────
# Allocation logic
# ───────────────────────────────
@dataclass
class Allocation:
    fixed_cents: int
    ops_cents: int
    inventory_cents: int
    buffer_cents: int


def current_month_target_cents(on_date: date) -> int:
    """Sum of all active fixed bills for this month."""
    total = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(FixedBill.monthly_amount_cents), 0))
        .where(FixedBill.is_active == True)
    )
    return int(total or 0)


def compute_allocation(
    sales_cents: int,
    on_date: date,
    inventory_rate: float,
    ops_rate: float,
) -> Tuple[Allocation, Dict[str, int]]:
    """Split a sale amount into envelope allocations, optionally using a custom start date for this month."""
    month_target = current_month_target_cents(on_date)

    # ───────────────────────────────
    # Check for a custom start date override
    # ───────────────────────────────
    from models import FixedBill  # local import to avoid circular import

    custom_start_date = db.session.scalar(
        db.select(FixedBill.custom_start_date)
        .where(FixedBill.custom_start_date.isnot(None))
        .order_by(FixedBill.custom_start_date.desc())
        .limit(1)
    )

    if custom_start_date and custom_start_date.month == on_date.month and custom_start_date.year == on_date.year:
        # Calculate number of active days since custom start
        from datetime import timedelta
        last_day = date(on_date.year, on_date.month, 1).replace(
            day=calendar.monthrange(on_date.year, on_date.month)[1]
        )
        days_active = (last_day - custom_start_date).days + 1
        dim = max(days_active, 1)
    else:
        # Default: full month
        dim = days_in_month(on_date.year, on_date.month)

    fixed_daily_goal = month_target // dim if dim else 0

    # ───────────────────────────────
    # Allocation calculation
    # ───────────────────────────────
    remaining = sales_cents

    fixed_alloc = min(fixed_daily_goal, remaining)
    remaining -= fixed_alloc

    ops_alloc = min(int(round(ops_rate * sales_cents)), remaining)
    remaining -= ops_alloc

    inv_alloc = min(int(round(inventory_rate * sales_cents)), remaining)
    remaining -= inv_alloc

    buffer_alloc = max(remaining, 0)

    debug = {
        "month_target": month_target,
        "days_in_month": dim,
        "fixed_daily_goal": fixed_daily_goal,
        "custom_start_date": str(custom_start_date) if custom_start_date else None,
    }

    return Allocation(fixed_alloc, ops_alloc, inv_alloc, buffer_alloc), debug
