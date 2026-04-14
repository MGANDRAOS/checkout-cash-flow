import os
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
# Local imports
from models import (
    db,
    Envelope,
    EnvelopeTransaction,
    DailyClosing,
    FixedBill,
    FixedCollection,
    Expense,
    Supplier,
    Payable,
    PayablePayment,
    DailyPaidItem
)

from helpers import (
    dollars_to_cents,
    cents_to_dollars,
    ensure_default_envelopes,
    post_envelope_tx,
    compute_allocation,
    current_month_target_cents,
    get_setting,
    set_setting,
    get_sales_overview_data,
    days_in_month,
    ensure_default_settings
)
from routes.intelligence import intelligence_bp
from routes.items import items_bp
from routes.sales import sales_bp
from routes.ai import ai_bp
from routes.weather import weather_bp
from routes.analytics_assistant import bp as analytics_assistant_bp
from routes.realtime import realtime_bp
from routes.item_trends import item_trends_bp
from routes.items_explorer import items_explorer_bp
from routes.invoices import invoices_bp
from routes.dead_items import dead_items_bp
from routes.reorder_radar import reorder_radar_bp  # NEW
from helpers_intelligence import get_pos_sales_total_by_range
from helpers_intelligence import get_pos_sales_daily_by_range



# ───────────────────────────────
# Load environment variables
# ───────────────────────────────
load_dotenv()

# ───────────────────────────────
# Flask configuration
# ───────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
# ----------------------------------------------------
# Simple App Authentication (username + password)
# ----------------------------------------------------

APP_USERNAME = os.getenv("APP_USERNAME")
APP_PASSWORD = os.getenv("APP_PASSWORD")

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///checkout.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy with the Flask app
db.init_app(app)

# Business constants
CURRENCY = os.getenv("CURRENCY", "USD")
DEFAULT_INVENTORY_RATE = float(os.getenv("INVENTORY_RATE", "0.50"))
DEFAULT_OPS_RATE = float(os.getenv("OPS_RATE", "0.03"))
USD_EXCHANGE_RATE = 89000
# IMPORTANT:
# Controlled payment types for manual paid items.
# Keep this list aligned with the dropdown in the template.
PAID_ITEM_TYPES = [
    "Generator",
    "EDL",
    "Wifi",
    "Restock",
    "Salary",
    "Other",
]
MIN_TRACKING_DATE = date(2026, 4, 11)

# ───────────────────────────────
# Routes
# ───────────────────────────────


@app.context_processor
def inject_request():
    return dict(request=request)


def dashboard():
    """Main dashboard: balances, bills, recent closings."""
    ensure_default_envelopes()
    envelopes = db.session.execute(db.select(Envelope).order_by(Envelope.id)).scalars().all()
    bills = db.session.execute(db.select(FixedBill).order_by(FixedBill.created_at.desc())).scalars().all()

    today = date.today()
    yesterday = today - timedelta(days=1)
    month_target = current_month_target_cents(today)
    fixed_balance = db.session.scalar(db.select(Envelope.balance_cents).where(Envelope.code == "FIXED")) or 0
    funded_pct = (fixed_balance / month_target * 100) if month_target > 0 else 0

    closings = db.session.execute(
        db.select(DailyClosing).order_by(DailyClosing.date.desc()).limit(30)
    ).scalars().all()
    
    last_close = db.session.execute(
    db.select(DailyClosing).order_by(DailyClosing.date.desc())
    ).scalars().first()
    
    last_data = None
    
    if last_close:
        last_data = {
            "fixed": last_close.fixed_allocation_cents / 100,
            "ops": last_close.ops_allocation_cents / 100,
            "inventory": last_close.inventory_allocation_cents / 100,
            "buffer": last_close.buffer_allocation_cents / 100,
        }
        
    # Fetch last closing (yesterday's sale suggestion)
    last_closing = db.session.execute(
        db.select(DailyClosing).order_by(DailyClosing.date.desc())
    ).scalars().first()
    
    suggested_date = (last_closing.date + timedelta(days=1)) if last_closing else date.today()
    suggested_sale = last_closing.sales_cents / 100 if last_closing else ""

    # Smart alert: missing yesterday's closing
    yesterday = today - timedelta(days=1)
    missing_yesterday = db.session.scalar(
        db.select(db.func.count()).select_from(DailyClosing).where(DailyClosing.date == yesterday)
    ) == 0

    # Smart alert: outstanding Fixed not yet collected (month-to-date)
    month_start = today.replace(day=1)
    closings_mtd = db.session.execute(
        db.select(DailyClosing).where(DailyClosing.date >= month_start)
    ).scalars().all()
    total_allocated_fixed = sum(c.fixed_allocation_cents for c in closings_mtd)
    total_collected_fixed = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(FixedCollection.amount_cents), 0))
        .where(FixedCollection.collected_on >= month_start)
    ).scalar() or 0
    outstanding_fixed_cents = max(total_allocated_fixed - (total_collected_fixed or 0), 0)

    # Mini chart: last 7 days sales vs. buffer
    last7 = db.session.execute(
        db.select(DailyClosing).order_by(DailyClosing.date.desc()).limit(7)
    ).scalars().all()
    last7 = list(reversed(last7))
    chart_labels = [c.date.strftime('%b %d') for c in last7]
    chart_sales = [round(c.sales_cents / 100, 2) for c in last7]
    chart_buffer = [round(c.buffer_allocation_cents / 100, 2) for c in last7]

    # Highlight: largest sale this week and running average (last 7 days)
    week_start = today - timedelta(days=6)
    last7_window = db.session.execute(
        db.select(DailyClosing)
        .where(DailyClosing.date >= week_start)
        .order_by(DailyClosing.date)
    ).scalars().all()
    if last7_window:
        top_closing = max(last7_window, key=lambda c: c.sales_cents)
        largest_sale_cents = top_closing.sales_cents
        largest_sale_date = top_closing.date
        avg_sales_cents = int(sum(c.sales_cents for c in last7_window) / len(last7_window))
    else:
        largest_sale_cents = 0
        largest_sale_date = None
        avg_sales_cents = 0
        
    kpis, data_points = get_sales_overview_data()


    return render_template(
        "dashboard.html",
        envelopes=envelopes,
        bills=bills,
        closings=closings,
        currency=CURRENCY,
        funded_pct=funded_pct,
        month_target_cents=month_target,
        suggested_sale=suggested_sale,
        suggested_date=suggested_date,
        last_data=last_data,
        last_closing=last_closing,
        today=date.today(),
        # Smart alerts
        missing_yesterday=missing_yesterday,
        yesterday=yesterday,
        outstanding_fixed_cents=outstanding_fixed_cents,
        outstanding_fixed_dollars=cents_to_dollars(outstanding_fixed_cents),
        # Mini chart data
        chart_labels=chart_labels,
        chart_sales=chart_sales,
        chart_buffer=chart_buffer,
        # Highlights
        largest_sale_dollars=cents_to_dollars(largest_sale_cents),
        largest_sale_date=largest_sale_date,
        avg_sales_dollars=cents_to_dollars(avg_sales_cents),
        # New 30-day analytics
        kpis=kpis,
        data_points=data_points,
    )


@app.route("/finance")
def finance_home():
    """
    Finance entry point.
    Redirect directly to the simple Sales vs Spending Summary page.
    """
    return redirect(url_for("finance_summary"))


@app.route("/finance/payables", methods=["GET", "POST"])
def finance_payables():
    """
    Payables main page.
    GET  -> show all payables + suppliers
    POST -> create a new payable
    """
    if request.method == "POST":
        try:
            supplier_name = request.form["supplier_name"].strip()
            description = request.form["description"].strip()
            bill_date = datetime.strptime(request.form["bill_date"], "%Y-%m-%d").date()
            due_date_raw = request.form.get("due_date", "").strip()
            due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None

            total_amount_cents = dollars_to_cents(request.form["total_amount"])
            reference = request.form.get("reference", "").strip() or None
            notes = request.form.get("notes", "").strip() or None

            if not supplier_name:
                raise ValueError("Supplier name is required.")
            if not description:
                raise ValueError("Description is required.")
            if total_amount_cents <= 0:
                raise ValueError("Amount must be greater than zero.")

            # Important: reuse supplier if it already exists, otherwise create it
            supplier = db.session.execute(
                db.select(Supplier).where(db.func.lower(Supplier.name) == supplier_name.lower())
            ).scalar_one_or_none()

            if not supplier:
                supplier = Supplier(name=supplier_name)
                db.session.add(supplier)
                db.session.flush()

            payable = Payable(
                supplier_id=supplier.id,
                bill_date=bill_date,
                due_date=due_date,
                reference=reference,
                description=description,
                total_amount_cents=total_amount_cents,
                paid_amount_cents=0,
                remaining_amount_cents=total_amount_cents,
                notes=notes,
            )
            payable.refresh_status()

            db.session.add(payable)
            db.session.commit()
            flash("Payable created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Could not create payable: {e}", "danger")

        return redirect(url_for("finance_payables"))

    # GET
    payables = db.session.execute(
        db.select(Payable).order_by(Payable.bill_date.desc(), Payable.created_at.desc())
    ).scalars().all()

    suppliers = db.session.execute(
        db.select(Supplier).where(Supplier.is_active == True).order_by(Supplier.name)
    ).scalars().all()

    return render_template(
        "finance/payables.html",
        payables=payables,
        suppliers=suppliers,
        currency=CURRENCY,
        today=date.today(),
    )


@app.post("/finance/payables/<int:payable_id>/payment")
def finance_payable_payment(payable_id):
    """
    Record a payment against a payable.
    This updates payment history, payable totals/status,
    and optionally creates a cash movement from an envelope.
    """
    ensure_default_envelopes()

    payable = db.session.get(Payable, payable_id)
    if not payable:
        flash("Payable not found.", "warning")
        return redirect(url_for("finance_payables"))

    try:
        payment_date = datetime.strptime(request.form["payment_date"], "%Y-%m-%d").date()
        amount_cents = dollars_to_cents(request.form["amount"])
        payment_method = request.form.get("payment_method", "").strip() or None
        envelope_code = request.form.get("envelope_code", "").strip() or None
        notes = request.form.get("notes", "").strip() or None

        if amount_cents <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if amount_cents > (payable.remaining_amount_cents or 0):
            raise ValueError("Payment amount cannot exceed remaining balance.")

        envelope = None
        if envelope_code:
            envelope = db.session.execute(
                db.select(Envelope).where(Envelope.code == envelope_code)
            ).scalar_one_or_none()

            if not envelope:
                raise ValueError("Selected envelope was not found.")

        payment = PayablePayment(
            payable_id=payable.id,
            payment_date=payment_date,
            amount_cents=amount_cents,
            payment_method=payment_method,
            envelope_id=envelope.id if envelope else None,
            notes=notes,
        )
        db.session.add(payment)

        # Important: update payable totals and status
        payable.paid_amount_cents = (payable.paid_amount_cents or 0) + amount_cents
        payable.refresh_status()

        # Optional: move cash if an envelope was selected
        if envelope_code:
            post_envelope_tx(
                envelope_code,
                -amount_cents,
                "payable_payment",
                f"Payable payment: {payable.description}",
            )

        db.session.commit()
        flash("Payment recorded successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Could not record payment: {e}", "danger")

    return redirect(url_for("finance_payables"))


@app.route("/finance/ledger")
def finance_ledger():
    """
    Unified finance ledger.
    Combines expenses, payable payments, and envelope transactions
    into one chronological operational view.
    """
    # ------------------------------------------------------------
    # Collect expenses
    # ------------------------------------------------------------
    expense_rows = db.session.execute(
        db.select(Expense).order_by(Expense.date.desc(), Expense.created_at.desc())
    ).scalars().all()

    ledger_items = []

    for expense in expense_rows:
        envelope_name = expense.envelope.name if expense.envelope else None

        ledger_items.append({
            "entry_date": expense.date,
            "created_at": expense.created_at,
            "source_type": "expense",
            "direction": "out",
            "title": expense.description,
            "subtitle": expense.category or "Expense",
            "party": expense.vendor,
            "payment_method": expense.payment_method,
            "account_name": envelope_name,
            "amount_cents": expense.amount_cents,
            "status": None,
            "reference_text": f"Expense #{expense.id}",
        })

    # ------------------------------------------------------------
    # Collect payable payments
    # ------------------------------------------------------------
    payable_payment_rows = db.session.execute(
        db.select(PayablePayment).order_by(PayablePayment.payment_date.desc(), PayablePayment.created_at.desc())
    ).scalars().all()

    for payment in payable_payment_rows:
        payable = payment.payable
        supplier_name = payable.supplier.name if payable and payable.supplier else None
        envelope_name = payment.envelope.name if payment.envelope else None

        ledger_items.append({
            "entry_date": payment.payment_date,
            "created_at": payment.created_at,
            "source_type": "payable_payment",
            "direction": "out",
            "title": payable.description if payable else "Payable Payment",
            "subtitle": "Payable Payment",
            "party": supplier_name,
            "payment_method": payment.payment_method,
            "account_name": envelope_name,
            "amount_cents": payment.amount_cents,
            "status": payable.status if payable else None,
            "reference_text": f"Payment #{payment.id}",
        })

    # ------------------------------------------------------------
    # Collect envelope transactions
    # Important:
    # skip pure daily-close allocation noise for now where needed later
    # but keep them visible now because this is the true cash movement log
    # ------------------------------------------------------------
    envelope_tx_rows = db.session.execute(
        db.select(EnvelopeTransaction).order_by(EnvelopeTransaction.created_at.desc())
    ).scalars().all()

    for tx in envelope_tx_rows:
        envelope_name = tx.envelope.name if tx.envelope else None
        amount_cents = abs(tx.amount_cents or 0)

        ledger_items.append({
            "entry_date": tx.created_at.date() if tx.created_at else None,
            "created_at": tx.created_at,
            "source_type": "envelope_transaction",
            "direction": "in" if (tx.amount_cents or 0) > 0 else "out",
            "title": tx.description or tx.type or "Envelope Transaction",
            "subtitle": tx.type or "Envelope Transaction",
            "party": None,
            "payment_method": None,
            "account_name": envelope_name,
            "amount_cents": amount_cents,
            "status": None,
            "reference_text": f"Envelope Tx #{tx.id}",
        })

    # ------------------------------------------------------------
    # Sort newest first by entry date then exact creation time
    # ------------------------------------------------------------
    ledger_items.sort(
        key=lambda item: (
            item["entry_date"] or date.min,
            item["created_at"] or datetime.min
        ),
        reverse=True
    )

    return render_template(
        "finance/ledger.html",
        ledger_items=ledger_items,
        today=date.today(),
        currency=CURRENCY,
    )


@app.route("/finance/reconciliation", methods=["GET", "POST"])
def finance_reconciliation():
    """
    Simple reconciliation page.
    Compare expected envelope balances with actual counted balances.
    """
    ensure_default_envelopes()

    # ------------------------------------------------------------
    # Load the two main finance envelopes
    # ------------------------------------------------------------
    bills_envelope = db.session.execute(
        db.select(Envelope).where(Envelope.code == "BILLS")
    ).scalar_one_or_none()

    spend_envelope = db.session.execute(
        db.select(Envelope).where(Envelope.code == "SPEND")
    ).scalar_one_or_none()

    bills_expected_cents = bills_envelope.balance_cents if bills_envelope else 0
    spend_expected_cents = spend_envelope.balance_cents if spend_envelope else 0

    # Default values for GET
    bills_actual = ""
    spend_actual = ""
    bills_diff_cents = None
    spend_diff_cents = None
    total_expected_cents = bills_expected_cents + spend_expected_cents
    total_actual_cents = None
    total_diff_cents = None

    if request.method == "POST":
        try:
            bills_actual_cents = dollars_to_cents(request.form.get("bills_actual", "0"))
            spend_actual_cents = dollars_to_cents(request.form.get("spend_actual", "0"))

            bills_actual = request.form.get("bills_actual", "").strip()
            spend_actual = request.form.get("spend_actual", "").strip()

            bills_diff_cents = bills_actual_cents - bills_expected_cents
            spend_diff_cents = spend_actual_cents - spend_expected_cents

            total_actual_cents = bills_actual_cents + spend_actual_cents
            total_diff_cents = total_actual_cents - total_expected_cents

        except Exception as e:
            flash(f"Could not calculate reconciliation: {e}", "danger")

    return render_template(
        "finance/reconciliation.html",
        today=date.today(),
        bills_expected_cents=bills_expected_cents,
        spend_expected_cents=spend_expected_cents,
        total_expected_cents=total_expected_cents,
        bills_actual=bills_actual,
        spend_actual=spend_actual,
        bills_diff_cents=bills_diff_cents,
        spend_diff_cents=spend_diff_cents,
        total_actual_cents=total_actual_cents,
        total_diff_cents=total_diff_cents,
        currency=CURRENCY,
    )

@app.route("/finance/summary")
def finance_summary():
    """
    Sales vs Spending summary page.

    Real business logic:
    - Sales belong to a business day
    - Paid items are linked to a source_date (which cash batch was used)
    - Remaining Cash = Sales - Used From This Day
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    # ------------------------------------------------------------
    # Default range = current week (Monday -> today)
    # ------------------------------------------------------------
    default_from = today - timedelta(days=today.weekday())
    default_to = today

    from_str = request.args.get("from_date", default_from.isoformat()).strip()
    to_str = request.args.get("to_date", default_to.isoformat()).strip()

    try:
        from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
        to_date = datetime.strptime(to_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date range. Reset to current week.", "warning")
        from_date = default_from
        to_date = default_to
        from_str = from_date.isoformat()
        to_str = to_date.isoformat()

    if from_date > to_date:
        flash("From date cannot be after To date. Reset to current week.", "warning")
        from_date = default_from
        to_date = default_to
        from_str = from_date.isoformat()
        to_str = to_date.isoformat()
        
            # ------------------------------------------------------------
    # Enforce minimum tracking date
    # ------------------------------------------------------------
    if from_date < MIN_TRACKING_DATE:
        from_date = MIN_TRACKING_DATE
        from_str = from_date.isoformat()
        flash("Start date adjusted to tracking start (April 11, 2026).", "warning")

    if to_date < MIN_TRACKING_DATE:
        to_date = MIN_TRACKING_DATE
        to_str = to_date.isoformat()

    # ------------------------------------------------------------
    # POS sales totals in LBP for the selected business-date range
    # ------------------------------------------------------------
    total_sales_lbp = float(get_pos_sales_total_by_range(from_date, to_date) or 0.0)

    # ------------------------------------------------------------
    # Paid items:
    # We load by source_date because spending is tied to the cash batch used
    # ------------------------------------------------------------
    paid_items = db.session.execute(
        db.select(DailyPaidItem)
        .where(DailyPaidItem.source_date >= from_date)
        .where(DailyPaidItem.source_date <= to_date)
        .order_by(DailyPaidItem.paid_date.desc(), DailyPaidItem.created_at.desc())
    ).scalars().all()

    total_spending_lbp = sum((item.amount_cents or 0) / 100 for item in paid_items)
    total_profit_lbp = total_sales_lbp - total_spending_lbp

    # ------------------------------------------------------------
    # Currency conversion
    # ------------------------------------------------------------
    total_sales_usd = total_sales_lbp / USD_EXCHANGE_RATE
    total_spending_usd = total_spending_lbp / USD_EXCHANGE_RATE
    total_profit_usd = total_profit_lbp / USD_EXCHANGE_RATE

    # ------------------------------------------------------------
    # Daily sales from POS
    # ------------------------------------------------------------
    sales_daily_rows = get_pos_sales_daily_by_range(from_date, to_date)

    sales_by_day = {
        row["biz_date"]: float(row["sales_lbp"] or 0.0)
        for row in sales_daily_rows
    }

    # ------------------------------------------------------------
    # Spending grouped by SOURCE DATE (cash batch used)
    # ------------------------------------------------------------
    spending_by_day = {}
    for item in paid_items:
        day_key = item.source_date.isoformat()
        spending_by_day[day_key] = spending_by_day.get(day_key, 0.0) + ((item.amount_cents or 0) / 100)

    # Build one combined set of dates for the selected range
    all_days = sorted(set(list(sales_by_day.keys()) + list(spending_by_day.keys())), reverse=True)

    daily_rows = []
    for day_key in all_days:
        biz_date_obj = datetime.strptime(day_key, "%Y-%m-%d").date()
        sales_lbp = sales_by_day.get(day_key, 0.0)
        used_lbp = spending_by_day.get(day_key, 0.0)
        remaining_lbp = sales_lbp - used_lbp

        daily_rows.append({
            "biz_date": day_key,
            "day_name": biz_date_obj.strftime("%A"),
            "display_date": biz_date_obj.strftime("%A, %Y-%m-%d"),
            "sales_lbp": sales_lbp,
            "used_lbp": used_lbp,
            "remaining_lbp": remaining_lbp,
            "sales_usd": sales_lbp / USD_EXCHANGE_RATE,
            "used_usd": used_lbp / USD_EXCHANGE_RATE,
            "remaining_usd": remaining_lbp / USD_EXCHANGE_RATE,
        })

    # ------------------------------------------------------------
    # Default values for the add form
    # - paid_date defaults to today
    # - source_date defaults to yesterday
    # ------------------------------------------------------------
    default_paid_date_str = today.isoformat()
    default_source_date_str = (today - timedelta(days=1)).isoformat()

    return render_template(
        "finance/summary.html",
        today=today,
        yesterday=yesterday,
        from_date=from_date,
        to_date=to_date,
        from_str=from_str,
        to_str=to_str,
        paid_items=paid_items,
        daily_rows=daily_rows,
        total_sales_lbp=total_sales_lbp,
        total_spending_lbp=total_spending_lbp,
        total_profit_lbp=total_profit_lbp,
        total_sales_usd=total_sales_usd,
        total_spending_usd=total_spending_usd,
        total_profit_usd=total_profit_usd,
        usd_exchange_rate=USD_EXCHANGE_RATE,
        paid_item_types=PAID_ITEM_TYPES,
        default_paid_date_str=default_paid_date_str,
        default_source_date_str=default_source_date_str,
        currency=CURRENCY,
    )

@app.post("/finance/summary/add-paid-item")
def finance_summary_add_paid_item():
    """
    Add a manual paid item for the Sales vs Spending page.

    Important business logic:
    - paid_date   = when payment happened
    - source_date = which business day's cash was used
    - payment_type must be selected from a fixed list
    """
    try:
        paid_date = datetime.strptime(request.form["paid_date"], "%Y-%m-%d").date()
        source_date = datetime.strptime(request.form["source_date"], "%Y-%m-%d").date()

        title = request.form["title"].strip()
        amount_lbp_raw = request.form.get("amount_lbp", "").strip()
        amount_usd_raw = request.form.get("amount_usd", "").strip()

        amount_lbp = 0.0

        # ------------------------------------------------------------
        # Handle input logic:
        # - Prefer USD if provided
        # - Otherwise use LBP
        # ------------------------------------------------------------
        if amount_usd_raw:
            amount_usd = float(amount_usd_raw)
            if amount_usd <= 0:
                raise ValueError("USD amount must be greater than zero.")
            amount_lbp = amount_usd * USD_EXCHANGE_RATE

        elif amount_lbp_raw:
            amount_lbp = float(amount_lbp_raw)
            if amount_lbp <= 0:
                raise ValueError("LBP amount must be greater than zero.")

        else:
            raise ValueError("Please enter either LBP or USD amount.")
        payment_type = request.form.get("payment_type", "").strip()
        notes = request.form.get("notes", "").strip() or None

        if not title:
            raise ValueError("Title is required.")

        if payment_type not in PAID_ITEM_TYPES:
            raise ValueError("Invalid payment type selected.")

        paid_item = DailyPaidItem(
            paid_date=paid_date,
            source_date=source_date,
            title=title,
            amount_cents=int(round(amount_lbp * 100)),
            payment_type=payment_type,
            notes=notes,
        )
        db.session.add(paid_item)
        db.session.commit()
        flash("Paid item added successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Could not add paid item: {e}", "danger")

    # IMPORTANT:
    # Keep user on the same selected range after save.
    from_str = request.form.get("from_date_redirect", "").strip()
    to_str = request.form.get("to_date_redirect", "").strip()

    if from_str and to_str:
        return redirect(url_for("finance_summary", from_date=from_str, to_date=to_str))

    return redirect(url_for("finance_summary"))

@app.post("/daily-close")
def daily_close():
    """Perform the end-of-day cash allocation."""
    ensure_default_envelopes()
    try:
        close_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        sale_cents = dollars_to_cents(request.form["sales"])
        notes = request.form.get("notes", "").strip() or None
    except Exception as e:
        flash(f"Invalid input: {e}", "danger")
        return redirect(url_for("dashboard"))

    # Prevent duplicate closings
    exists = db.session.scalar(
        db.select(db.func.count()).select_from(DailyClosing).where(DailyClosing.date == close_date)
    )
    if exists:
        flash("A closing for this date already exists.", "warning")
        return redirect(url_for("closings"))

    # Compute allocation
    alloc, debug = compute_allocation(sale_cents, close_date)

    closing = DailyClosing(
        date=close_date,
        sales_cents=sale_cents,
        fixed_allocation_cents=alloc.fixed_cents,
        ops_allocation_cents=alloc.ops_cents,
        inventory_allocation_cents=alloc.inventory_cents,
        buffer_allocation_cents=alloc.buffer_cents,
        notes=notes,
    )
    db.session.add(closing)
    db.session.flush()

    # Post envelope transactions
    # === v2: Post to BILLS (fixed) and SPEND (buffer) only ===============
    post_envelope_tx("BILLS", alloc.fixed_cents, "allocation", f"Daily Close {close_date}", closing.id)
    post_envelope_tx("SPEND", alloc.buffer_cents, "allocation", f"Daily Close {close_date}", closing.id)
    # Legacy: zero out other envelopes via neutral entries (optional — skip to reduce noise)
    # =====================================================================


    db.session.commit()
    
    if close_date > date.today():
        flash("You cannot submit a slip for a future date.", "danger")
        return redirect(url_for("closings"))
    if close_date < date(2025, 10, 13):
        flash("You cannot submit slips before the business officially started.", "danger")
        return redirect(url_for("closings"))

    flash(
        f"Successfully submitted closing for {close_date.strftime('%B %d, %Y')}: "
        f"Fixed ${cents_to_dollars(alloc.fixed_cents)}, "
        f"Ops ${cents_to_dollars(alloc.ops_cents)}, "
        f"Inventory ${cents_to_dollars(alloc.inventory_cents)}, "
        f"Buffer ${cents_to_dollars(alloc.buffer_cents)}.",
        "success",
    )
    return redirect(url_for("closings"))


@app.route("/bills", methods=["GET", "POST"])
def bills():
    """Add or list monthly fixed bills with funding progress."""
    from main import db, FixedBill, DailyClosing, FixedCollection, Envelope
    from datetime import date

    # POST → Add new bill
    if request.method == "POST":
        name = request.form["name"].strip()
        amount = float(request.form["amount"])
        active = "active" in request.form

        new_bill = FixedBill(
            name=name,
            monthly_amount_cents=int(round(amount * 100)),
            is_active=active
        )
        db.session.add(new_bill)
        db.session.commit()
        flash(f"New fixed bill '{name}' added!", "success")
        return redirect(url_for("bills"))

    # GET → List all bills with progress
    today = date.today()
    month_start = today.replace(day=1)

    # 1. Get all bills
    all_bills = FixedBill.query.order_by(FixedBill.name).all()

    # 2. Calculate monthly fixed funds (allocated + collected)
    closings = db.session.execute(
        db.select(DailyClosing).where(DailyClosing.date >= month_start)
    ).scalars().all()
    total_allocated_fixed = sum(c.fixed_allocation_cents for c in closings)

    total_collected_fixed = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(FixedCollection.amount_cents), 0))
        .where(FixedCollection.collected_on >= month_start)
    ).scalar() or 0

    # 3. Compute funding progress for each bill (proportional allocation)
    active_bills = [b for b in all_bills if b.is_active]
    total_target_cents = sum(b.monthly_amount_cents for b in active_bills) or 1

    for bill in all_bills:
        target = bill.monthly_amount_cents or 1

        # Allocate funds proportionally by target weight
        bill_share_ratio = target / total_target_cents
        allocated_share = total_collected_fixed * bill_share_ratio

        # Cap at target (don't exceed 100%)
        funded = min(allocated_share, target)
        pct = round((funded / target) * 100, 1)
        remaining = max(target - funded, 0)

        bill.funded = funded / 100
        bill.remaining = remaining / 100
        bill.pct = pct
        
    fixed_balance = db.session.scalar(
        db.select(Envelope.balance_cents).where(Envelope.code == "FIXED")
    ) or 0
    active_bills = [b for b in all_bills if b.is_active]
    total_target = sum(b.monthly_amount_cents for b in active_bills) or 1
    funded_pct = round((fixed_balance / total_target) * 100, 1)

    today = date.today()
    last30 = db.session.execute(
        db.select(DailyClosing.date, DailyClosing.fixed_allocation_cents)
        .where(DailyClosing.date >= today - timedelta(days=30))
        .order_by(DailyClosing.date)
    ).all()
    running, points = 0, []
    for d, f in last30:
        running += f or 0
        points.append({"date": d.strftime("%b %d"), "balance": running / 100})

    if not all_bills:
        kpis = {"funded_pct": 0, "balance": 0, "total_target": 0}
        points = []
    
    kpis = {
        "funded_pct": funded_pct,
        "balance": fixed_balance / 100,
        "total_target": total_target / 100,
    }
    
    return render_template(
        "bills.html",
        bills=all_bills,
        currency="USD",
        today=today,
        points=points,
        kpis=kpis
    )


@app.post("/fixed-bills")
def fixed_bills():
    """Add or list monthly fixed bills."""
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            amount = float(request.form.get("monthly_amount", "0"))
            is_active = bool(request.form.get("is_active"))
            if not name:
                raise ValueError("Bill name required.")
            db.session.add(FixedBill(name=name, monthly_amount_cents=int(amount * 100), is_active=is_active))
            db.session.commit()
            flash("Fixed bill added.", "success")
        except Exception as e:
            flash(f"Could not add bill: {e}", "danger")
        return redirect(url_for("dashboard"))

    bills = db.session.execute(db.select(FixedBill)).scalars().all()
    return jsonify([
        {
            "id": b.id,
            "name": b.name,
            "monthly_amount_cents": b.monthly_amount_cents,
            "monthly_amount": f"{b.monthly_amount_cents / 100:.2f}",
            "is_active": b.is_active,
        } for b in bills
    ])
    
    
@app.post("/set-custom-start")
def set_custom_start():
    try:
        date_str = request.form.get("custom_start_date")
        custom_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        # Apply globally (for all active bills this month)
        active_bills = db.session.execute(
            db.select(FixedBill).where(FixedBill.is_active == True)
        ).scalars().all()
        for bill in active_bills:
            bill.custom_start_date = custom_date
        db.session.commit()
        flash(f"Custom start date set to {custom_date}.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("dashboard"))


@app.post("/delete-fixed-bill/<int:bill_id>")
def delete_fixed_bill(bill_id):
    """Delete a fixed bill."""
    try:
        bill = db.session.get(FixedBill, bill_id)
        if not bill:
            flash("Fixed bill not found.", "warning")
            return redirect(url_for("dashboard"))
        db.session.delete(bill)
        db.session.commit()
        flash(f"Deleted fixed bill: {bill.name}", "success")
    except Exception as e:
        flash(f"Error deleting bill: {e}", "danger")
    return redirect(url_for("dashboard"))


@app.post("/toggle-fixed-bill/<int:bill_id>")
def toggle_fixed_bill(bill_id):
    """Toggle the active/inactive state of a fixed bill."""
    try:
        bill = db.session.get(FixedBill, bill_id)
        if not bill:
            flash("Fixed bill not found.", "warning")
            return redirect(url_for("dashboard"))
        bill.is_active = not bill.is_active
        db.session.commit()
        status = "activated" if bill.is_active else "deactivated"
        flash(f"{bill.name} {status}.", "info")
    except Exception as e:
        flash(f"Error toggling bill: {e}", "danger")
    return redirect(url_for("dashboard"))


@app.post("/void-closing/<int:closing_id>")
def void_closing(closing_id):
    """Void a daily closing, reverse allocations, and remove related data."""
    closing = db.session.get(DailyClosing, closing_id)
    if not closing:
        flash("Closing not found.", "warning")
        return redirect(url_for("closings"))

    try:
        # --- Step 1: Reverse Envelope Allocations ---
        post_envelope_tx("FIXED", -closing.fixed_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("OPS", -closing.ops_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("INVENTORY", -closing.inventory_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("BUFFER", -closing.buffer_allocation_cents, "void", f"Void {closing.date}")

        # --- Step 2: Delete Related FixedCollection (if any) ---
        fixed_collections = db.session.execute(
            db.select(FixedCollection).where(FixedCollection.collected_on == closing.date)
        ).scalars().all()

        if fixed_collections:
            for fc in fixed_collections:
                db.session.delete(fc)
            flash(f"Also removed {len(fixed_collections)} related Fixed Collection(s).", "info")

        # --- Step 3: Delete Envelope Transactions linked to this closing ---
        from models import EnvelopeTransaction
        related_tx = db.session.execute(
            db.select(EnvelopeTransaction).where(EnvelopeTransaction.daily_closing_id == closing.id)
        ).scalars().all()
        if related_tx:
            for tx in related_tx:
                db.session.delete(tx)
            flash(f"Removed {len(related_tx)} linked envelope transaction(s).", "info")

        # --- Step 4: Delete the Closing record itself ---
        db.session.delete(closing)
        db.session.commit()

        flash(f"Closing for {closing.date} fully voided and cleaned up.", "danger")

    except Exception as e:
        db.session.rollback()
        flash(f"Error while voiding closing: {e}", "danger")

    return redirect(url_for("closings"))


@app.post("/edit-closing/<int:closing_id>")
def edit_closing(closing_id):
    """Edit a daily closing (update sale/notes and reallocate safely)."""
    closing = db.session.get(DailyClosing, closing_id)
    if not closing:
        flash("Closing not found.", "warning")
        return redirect(url_for("closings"))

    try:
        # Parse new form data
        new_sale_cents = dollars_to_cents(request.form["sale"])
        new_notes = request.form.get("notes", "").strip() or None
        inventory_rate = float(request.form.get("inventory_rate", DEFAULT_INVENTORY_RATE))
        ops_rate = float(request.form.get("ops_rate", DEFAULT_OPS_RATE))

        # Check for existing fixed collection
        fixed_collections = db.session.execute(
            db.select(FixedCollection).where(FixedCollection.collected_on == closing.date)
        ).scalars().all()

        if fixed_collections:
            flash(
                f"Cannot edit closing for {closing.date} — fixed collection already recorded. "
                "Please void the collection first if you need to modify this closing.",
                "warning",
            )
            return redirect(url_for("closings"))

        # Reverse old allocations from envelopes
        post_envelope_tx("FIXED", -closing.fixed_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("OPS", -closing.ops_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("INVENTORY", -closing.inventory_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("BUFFER", -closing.buffer_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")

        # Compute new allocation
        alloc, _ = compute_allocation(new_sale_cents, closing.date)

        # Update closing record
        closing.sales_cents = new_sale_cents
        closing.notes = new_notes
        closing.fixed_allocation_cents = alloc.fixed_cents
        closing.ops_allocation_cents = alloc.ops_cents
        closing.inventory_allocation_cents = alloc.inventory_cents
        closing.buffer_allocation_cents = alloc.buffer_cents

        # Post new allocations
        post_envelope_tx("FIXED", alloc.fixed_cents, "edit_allocation", f"Edit update {closing.date}")
        post_envelope_tx("OPS", alloc.ops_cents, "edit_allocation", f"Edit update {closing.date}")
        post_envelope_tx("INVENTORY", alloc.inventory_cents, "edit_allocation", f"Edit update {closing.date}")
        post_envelope_tx("BUFFER", alloc.buffer_cents, "edit_allocation", f"Edit update {closing.date}")

        db.session.commit()
        flash(f"Closing for {closing.date} updated successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error editing closing: {e}", "danger")

    return redirect(url_for("closings"))


@app.route("/closings")
def closings():
    from main import DailyClosing
    all_closings = DailyClosing.query.order_by(DailyClosing.date.desc()).all()
    return render_template("closings.html", closings=all_closings, today=date.today())


@app.route("/envelopes")
def envelope_view():
    from main import Envelope

    envelopes = Envelope.query.order_by(Envelope.name).all()
    return render_template("envelopes.html", envelopes=envelopes)


@app.route("/reports")
def reports():
    return render_template("reports.html")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            inv_pct = float(request.form["inventory_pct"])
            ops_pct = float(request.form["ops_pct"])
            if inv_pct + ops_pct >= 1.0:
                flash("Inventory + Ops % must be less than 100%", "danger")
            else:
                set_setting("inventory_pct", str(inv_pct))
                set_setting("ops_pct", str(ops_pct))
                flash("Settings updated successfully!", "success")
        except Exception as e:
            flash(f"Error saving settings: {e}", "danger")
        return redirect(url_for("settings"))

    # GET method
    inv_pct = float(get_setting("inventory_pct", "0.5"))
    ops_pct = float(get_setting("ops_pct", "0.03"))

    return render_template(
        "settings.html",
        inventory_pct=inv_pct,
        ops_pct=ops_pct
    )
    


@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    """
    Quick ledger of payouts.
    POST creates an Expense, deducts from the chosen envelope, optional bill link.
    """
    ensure_default_envelopes()

    if request.method == "POST":
        try:
            exp_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
            desc = request.form["description"].strip()
            amount_cents = dollars_to_cents(request.form["amount"])
            envelope_code = request.form["envelope_code"]  # 'BILLS' or 'SPEND'
            category = request.form.get("category") or None
            vendor = request.form.get("vendor") or None
            payment_method = request.form.get("payment_method") or None
            bill_id = request.form.get("bill_id")
            bill_id = int(bill_id) if bill_id else None

            env = db.session.scalar(db.select(Envelope).where(Envelope.code == envelope_code))
            if not env:
                raise ValueError("Envelope not found.")

            exp = Expense(
                date=exp_date,
                description=desc,
                amount_cents=amount_cents,
                category=category,
                vendor=vendor,
                payment_method=payment_method,
                envelope_id=env.id,
                bill_id=bill_id
            )
            db.session.add(exp)

            # Deduct from envelope
            post_envelope_tx(envelope_code, -amount_cents, "spend", f"Expense: {desc}")

            # If linked to an installment bill, bump counter
            if bill_id:
                b = db.session.get(FixedBill, bill_id)
                if b and (b.frequency == "installment" or b.installments_total):
                    b.installments_paid = (b.installments_paid or 0) + 1

            db.session.commit()
            flash("Expense recorded.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Could not add expense: {e}", "danger")
        return redirect(url_for("expenses"))

    # GET
    all_exp = db.session.execute(
        db.select(Expense).order_by(Expense.date.desc(), Expense.created_at.desc())
    ).scalars().all()
    bills = db.session.execute(db.select(FixedBill).order_by(FixedBill.name)).scalars().all()
    envelopes = db.session.execute(db.select(Envelope).where(Envelope.code.in_(["BILLS","SPEND"]))).scalars().all()
    return render_template("expenses.html", expenses=all_exp, bills=bills, envelopes=envelopes, currency=CURRENCY)


@app.post("/bills/pay/<int:bill_id>")
def pay_bill(bill_id):
    """
    One-click bill payment: deduct from BILLS, create Expense, update installments if any.
    Amount = bill.monthly_amount_cents (current period).
    """
    b = db.session.get(FixedBill, bill_id)
    if not b or not b.is_active:
        flash("Bill not found or inactive.", "warning")
        return redirect(url_for("bills"))

    try:
        # Create expense
        today = date.today()
        desc = f"Pay {b.name}"
        amount_cents = b.monthly_amount_cents

        env = db.session.scalar(db.select(Envelope).where(Envelope.code == "BILLS"))
        if not env:
            raise RuntimeError("BILLS envelope missing.")

        exp = Expense(
            date=today,
            description=desc,
            amount_cents=amount_cents,
            category="Obligations",
            vendor=None,
            payment_method="Cash",
            envelope_id=env.id,
            bill_id=b.id
        )
        db.session.add(exp)

        # Deduct BILLS balance & bump installments if applicable
        post_envelope_tx("BILLS", -amount_cents, "spend", desc)
        if b.frequency == "installment" or b.installments_total:
            b.installments_paid = (b.installments_paid or 0) + 1

        db.session.commit()
        flash(f"Paid {b.name}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error paying bill: {e}", "danger")

    return redirect(url_for("bills"))


    
@app.route("/fixed-collections")
def fixed_collections():
    today = date.today()

    # 1. Get all closings this month and sum the fixed allocations
    month_start = today.replace(day=1)
    closings = db.session.execute(
        db.select(DailyClosing)
        .where(DailyClosing.date >= month_start)
        .order_by(DailyClosing.date.desc()) # This is the crucial line
    ).scalars().all()

    total_allocated = sum(c.fixed_allocation_cents for c in closings)

    # 2. Get all FixedCollection entries for this month
    collections = db.session.execute(
        db.select(FixedCollection).where(FixedCollection.collected_on >= month_start)
    ).scalars().all()

    total_collected = sum(c.amount_cents for c in collections)

    # 3. Daily fixed goal
    month_target = current_month_target_cents(today)
    dim = days_in_month(today.year, today.month)
    daily_goal = month_target // dim if dim else 0
    
    
    outstanding = total_allocated - total_collected

    progress_pct = (total_collected / total_allocated * 100) if total_allocated > 0 else 0


    return render_template(
        "fixed_collections.html",
        total_allocated=total_allocated,
        total_collected=total_collected,
        daily_goal=daily_goal,
        progress_pct=progress_pct,
        closings=closings,
        outstanding=outstanding,
        collections=collections,
        currency=CURRENCY,
        today=today
    )

    
@app.post("/mark-fixed-collected")
def mark_fixed_collected():
    try:
        collect_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        amount_cents = int(request.form["amount"])
        
        exists = db.session.scalar(
            db.select(db.func.count())
            .select_from(FixedCollection)
            .where(FixedCollection.collected_on == collect_date)
        )
        if exists:
            flash(f"Already collected for {collect_date}.", "warning")
        else:
            fc = FixedCollection(
                collected_on=collect_date,
                amount_cents=amount_cents
            )
            db.session.add(fc)
            db.session.commit()
            flash(f"Collected for {collect_date} successfully recorded.", "success")
    except Exception as e:
        flash(f"Error recording collection: {e}", "danger")

    return redirect(url_for("fixed_collections"))


@app.route("/reports/fixed-coverage")
def fixed_coverage_report():
    from datetime import date, timedelta
    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    days_in_month = (next_month - month_start).days
    days_elapsed = (today - month_start).days + 1
    days_remaining = days_in_month - days_elapsed

    # Data sources
    fixed_balance = db.session.scalar(
        db.select(Envelope.balance_cents).where(Envelope.code == "FIXED")
    ) or 0
    bills = db.session.execute(
        db.select(FixedBill).where(FixedBill.is_active == True)
    ).scalars().all()

    total_target = sum(b.monthly_amount_cents for b in bills) or 1
    funded_pct = round((fixed_balance / total_target) * 100, 1)

    # Average daily fixed inflow (last 30 days)
    last30 = db.session.execute(
        db.select(DailyClosing.fixed_allocation_cents)
        .where(DailyClosing.date >= today - timedelta(days=30))
    ).scalars().all()
    avg_daily_inflow_cents = sum(last30) / max(len(last30), 1)
    avg_daily_inflow = avg_daily_inflow_cents / 100

    # Forecasting
    remaining_cents = max(total_target - fixed_balance, 0)
    if avg_daily_inflow_cents > 0:
        projected_days = int(remaining_cents / avg_daily_inflow_cents)
        projected_date = (today + timedelta(days=projected_days)).strftime("%b %d")
    else:
        projected_date = "—"

    expected_end_balance = fixed_balance + (avg_daily_inflow_cents * days_remaining)
    gap_cents = expected_end_balance - total_target

    kpis = {
        "total_target": total_target / 100,
        "balance": fixed_balance / 100,
        "funded_pct": funded_pct,
        "avg_daily_inflow": avg_daily_inflow,
        "projected_date": projected_date,
        "days_remaining": days_remaining,
        "gap": gap_cents / 100,
    }

    # For line chart: daily cumulative fixed inflow (last 30 days)
    last30_closings = db.session.execute(
        db.select(DailyClosing.date, DailyClosing.fixed_allocation_cents)
        .where(DailyClosing.date >= today - timedelta(days=30))
        .order_by(DailyClosing.date)
    ).all()
    running, points = 0, []
    for d, f in last30_closings:
        running += f or 0
        points.append({"date": d.strftime("%b %d"), "balance": running / 100})

    return render_template("report_fixed_coverage.html", kpis=kpis, points=points, today=today )


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Very simple login page.
    Checks username/password from .env
    and stores login status in Flask session.
    """

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if username == APP_USERNAME and password == APP_PASSWORD:
            session["logged_in"] = True
            return redirect("/")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    """
    Clears login session.
    """
    session.clear()
    return redirect("/login")

    
# ───────────────────────────────
# App entry
# ───────────────────────────────
app.register_blueprint(intelligence_bp)
app.register_blueprint(items_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(analytics_assistant_bp)
app.register_blueprint(realtime_bp)
app.register_blueprint(item_trends_bp)
app.register_blueprint(items_explorer_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(dead_items_bp)
app.register_blueprint(reorder_radar_bp)  # NEW


@app.before_request
def require_login():
    """
    This runs before every request.
    If the user is not logged in,
    redirect them to the login page.
    """

    allowed_routes = ["login", "static"]

    if request.endpoint not in allowed_routes:
        if not session.get("logged_in"):
            return redirect(url_for("login"))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_default_envelopes()
        ensure_default_settings() 
    app.run(debug=os.getenv("FLASK_ENV") == "development")