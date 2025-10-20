import calendar 
from calendar import monthrange
from datetime import date
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from models import db, Envelope, EnvelopeTransaction, FixedBill, AppSetting, DailyClosing


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
        ("FIXED", "Fixed Expenses"),
        ("OPS", "Operations"),
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
    """Split a sale amount into envelope allocations using current settings.
    Fixed expenses are reserved first, using custom start dates if defined.
    """

    # Get configured percentages from settings
    inventory_rate = float(get_setting("inventory_pct", "0.5"))
    ops_rate = float(get_setting("ops_pct", "0.03"))

    # --- 1️⃣  Determine Fixed Bills Period ---
    fixed_bills = db.session.execute(
        db.select(FixedBill).where(FixedBill.is_active == True)
    ).scalars().all()

    if fixed_bills:
        # Find earliest custom_start_date (or fallback to month start)
        earliest_start = min(
            b.custom_start_date or date(on_date.year, on_date.month, 1)
            for b in fixed_bills
        )
    else:
        earliest_start = date(on_date.year, on_date.month, 1)

    # Total days in this active period (from start to end of month)
    month_end = date(on_date.year, on_date.month, days_in_month(on_date.year, on_date.month))
    days_in_period = (month_end - earliest_start).days + 1
    days_in_period = max(days_in_period, 1)

    # --- 2️⃣  Compute total fixed target for current month ---
    month_target = sum(b.monthly_amount_cents for b in fixed_bills)
    fixed_daily_goal = month_target // days_in_period

      # --- 3️⃣ Allocate ---

    # Reserve fixed first
    fixed_alloc = min(fixed_daily_goal, sales_cents)
    base = max(sales_cents - fixed_alloc, 0)

    # Apply both inventory and ops percentages on the same post-fixed base
    inv_alloc = int(round(base * inventory_rate))
    ops_alloc = int(round(base * ops_rate))

    # Whatever remains becomes buffer
    buffer_alloc = max(base - inv_alloc - ops_alloc, 0)


    # --- 4️⃣  Debug info for diagnostics ---
    debug = {
        "month_target": month_target,
        "days_in_period": days_in_period,
        "fixed_daily_goal": fixed_daily_goal,
        "inventory_rate": inventory_rate,
        "ops_rate": ops_rate,
        "period_start": earliest_start.isoformat(),
    }
    
    print("Settings → inventory_pct:", get_setting("inventory_pct", "0.5"))
    print("Settings → ops_pct:", get_setting("ops_pct", "0.03"))

    return Allocation(fixed_alloc, ops_alloc, inv_alloc, buffer_alloc), debug




def days_in_month(year: int, month: int) -> int:
    """Returns number of days in a given month."""
    return monthrange(year, month)[1]



def get_sales_overview_data():
    """Compute last 30-day sales KPIs and chart points for dashboard/report reuse."""
    from datetime import date, timedelta
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    closings = db.session.execute(
        db.select(DailyClosing).where(DailyClosing.date >= start_date)
    ).scalars().all()

    if not closings:
        return {}, []

    total_sales = sum(c.sales_cents for c in closings)
    avg_sales = total_sales / len(closings)
    best_day = max(closings, key=lambda c: c.sales_cents)
    worst_day = min(closings, key=lambda c: c.sales_cents)

    kpis = {
        "total_sales": total_sales / 100,
        "avg_sales": avg_sales / 100,
        "best_day": (best_day.date.strftime("%b %d"), best_day.sales_cents / 100),
        "worst_day": (worst_day.date.strftime("%b %d"), worst_day.sales_cents / 100),
    }

    data_points = [{
        "date": c.date.strftime("%b %d"),
        "sales": c.sales_cents / 100,
        "fixed": c.fixed_allocation_cents / 100,
        "ops": c.ops_allocation_cents / 100,
        "inventory": c.inventory_allocation_cents / 100,
        "buffer": c.buffer_allocation_cents / 100,
    } for c in closings]

    return kpis, data_points
