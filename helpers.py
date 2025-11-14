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
    """
    Ensure only the required envelopes exist for v2 logic.
    We DO NOT delete old envelopes to preserve history; we just guarantee BILLS & SPEND exist.
    """
    required = [
        ("BILLS", "Bills & Obligations"),
        ("SPEND", "Spend & Restock"),
    ]
    for code, name in required:
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
    """
    v2: Two-envelope allocation.
    - Compute a dynamic BILLS% to guarantee monthly bills + savings target by month end.
    - Map BILLS -> fixed_cents (reuse existing column), set others = 0 for compatibility.
    """
    # Toggle: dynamic vs fixed split (defaults dynamic)
    auto_dynamic = get_setting("auto_dynamic_allocation", "true").lower() in ("1","true","yes")
    if auto_dynamic:
        bills_pct = dynamic_bills_pct(on_date)
    else:
        # Fallback to fixed ratio if you decide to turn dynamic off in Settings
        bills_pct = get_float_setting("bills_pct_fixed", 0.50)

    bills_alloc = int(round(sales_cents * bills_pct))

    # Optional spend floor to avoid starving restock
    spend_floor_cents = int(round(get_float_setting("spend_floor_cents", 0)))
    spend_alloc = max(sales_cents - bills_alloc, spend_floor_cents)
    if spend_alloc > sales_cents:  # guard if floor > sales
        spend_alloc = sales_cents
        bills_alloc = 0

    # Reuse existing structure: fixed = BILLS; others set to 0
    alloc = Allocation(
        fixed_cents=bills_alloc,
        ops_cents=0,
        inventory_cents=0,
        buffer_cents=spend_alloc
    )

    debug = {
        "mode": "dynamic" if auto_dynamic else "fixed",
        "bills_pct": bills_pct,
        "sales": sales_cents,
        "bills_alloc": bills_alloc,
        "spend_alloc": spend_alloc,
    }
    return alloc, debug



def dynamic_bills_pct(on_date: date) -> float:
    """
    Compute today's BILLS% based on:
    - Remaining (sum(active fixed bills) + target_savings_monthly) - already allocated this month
    - Days remaining this month
    - Average daily sales (this month so far). Falls back to 0.5 if no data.
    Clamped between bills_pct_min and bills_pct_max; also respects spend_floor_cents.
    """
    # Targets
    active_bills_cents = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(FixedBill.monthly_amount_cents), 0))
        .where(FixedBill.is_active == True)
    ) or 0
    target_savings = int(round(get_float_setting("target_savings_monthly", 500.0) * 100))
    month_target = active_bills_cents + target_savings

    # Progress this month
    month_start = on_date.replace(day=1)
    allocated_fixed = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(DailyClosing.fixed_allocation_cents), 0))
        .where(DailyClosing.date >= month_start)
    ) or 0
    remaining = max(month_target - allocated_fixed, 0)

    # Time left
    total_days = days_in_month(on_date.year, on_date.month)
    days_left = max(total_days - (on_date.day - 1), 1)

    # Sales baseline (avg of this month's closings)
    avg_sales_cents = db.session.scalar(
        db.select(db.func.avg(DailyClosing.sales_cents))
        .where(DailyClosing.date >= month_start)
    ) or 0

    # If no history this month, assume neutral 50%
    raw_pct = (remaining / days_left) / avg_sales_cents if avg_sales_cents > 0 else 0.5

    # Clamp & floors
    pct_min = get_float_setting("bills_pct_min", 0.25)
    pct_max = get_float_setting("bills_pct_max", 0.80)
    pct = min(max(raw_pct, pct_min), pct_max)
    return pct



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



def get_float_setting(key: str, default: float) -> float:
    val = get_setting(key, None)
    try:
        return float(val) if val is not None else default
    except Exception:
        return default
    
    
    
def ensure_default_settings():
    defaults = {
        "auto_dynamic_allocation": "true",
        "target_savings_monthly": "500",
        "bills_pct_min": "0.25",
        "bills_pct_max": "0.80",
        "spend_floor_cents": "0",
        # Optional fixed mode knob:
        "bills_pct_fixed": "0.50",
    }
    for k, v in defaults.items():
        if get_setting(k) is None:
            set_setting(k, v)
