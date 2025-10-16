import calendar
from datetime import date
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from models import db, Envelope, EnvelopeTransaction, FixedBill, AppSetting


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
# App settings
# ───────────────────────────────
    
def get_setting(key: str, default: Optional[str] = None) -> str:
    setting = db.session.get(AppSetting, key)
    return setting.value if setting else default


def set_setting(key: str, value: str) -> None:
    setting = db.session.get(AppSetting, key)
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


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


def compute_allocation(sales_cents: int, on_date: date) -> Tuple[Allocation, Dict[str, int]]:
    """Split a sale amount into envelope allocations using current settings."""
    # Get configured percentages from settings
    inventory_rate = float(get_setting("inventory_pct", "0.5"))
    ops_rate = float(get_setting("ops_pct", "0.03"))

    month_target = current_month_target_cents(on_date)
    dim = days_in_month(on_date.year, on_date.month)
    fixed_daily_goal = month_target // dim if dim else 0

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
        "inventory_rate": inventory_rate,
        "ops_rate": ops_rate,
    }

    return Allocation(fixed_alloc, ops_alloc, inv_alloc, buffer_alloc), debug

