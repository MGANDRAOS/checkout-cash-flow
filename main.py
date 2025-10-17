import os
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Local imports
from models import db, Envelope, DailyClosing, FixedBill, FixedCollection
from helpers import (
    dollars_to_cents,
    cents_to_dollars,
    ensure_default_envelopes,
    post_envelope_tx,
    compute_allocation,
    current_month_target_cents,
    get_setting,
    set_setting,
    days_in_month
)

# ───────────────────────────────
# Load environment variables
# ───────────────────────────────
load_dotenv()

# ───────────────────────────────
# Flask configuration
# ───────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///checkout.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy with the Flask app
db.init_app(app)

# Business constants
CURRENCY = os.getenv("CURRENCY", "USD")
DEFAULT_INVENTORY_RATE = float(os.getenv("INVENTORY_RATE", "0.50"))
DEFAULT_OPS_RATE = float(os.getenv("OPS_RATE", "0.03"))


# ───────────────────────────────
# Routes
# ───────────────────────────────


@app.context_processor
def inject_request():
    return dict(request=request)


@app.route("/", methods=["GET", "POST"])
def dashboard():
    """Main dashboard: balances, bills, recent closings."""
    ensure_default_envelopes()
    envelopes = db.session.execute(db.select(Envelope).order_by(Envelope.id)).scalars().all()
    bills = db.session.execute(db.select(FixedBill).order_by(FixedBill.created_at.desc())).scalars().all()

    today = date.today()
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
    )


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
    post_envelope_tx("FIXED", alloc.fixed_cents, "allocation", f"Daily Close {close_date}", closing.id)
    post_envelope_tx("OPS", alloc.ops_cents, "allocation", f"Daily Close {close_date}", closing.id)
    post_envelope_tx("INVENTORY", alloc.inventory_cents, "allocation", f"Daily Close {close_date}", closing.id)
    post_envelope_tx("BUFFER", alloc.buffer_cents, "allocation", f"Daily Close {close_date}", closing.id)

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


@app.route("/fixed-bills", methods=["GET", "POST"])
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
    """Void a daily closing and reverse its envelope allocations."""
    closing = db.session.get(DailyClosing, closing_id)
    if not closing:
        flash("Closing not found.", "warning")
        return redirect(url_for("dashboard"))

    # Reverse envelope allocations
    try:
        post_envelope_tx("FIXED", -closing.fixed_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("OPS", -closing.ops_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("INVENTORY", -closing.inventory_allocation_cents, "void", f"Void {closing.date}")
        post_envelope_tx("BUFFER", -closing.buffer_allocation_cents, "void", f"Void {closing.date}")

        db.session.delete(closing)
        db.session.commit()
        flash(f"Closing for {closing.date} voided.", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error voiding closing: {e}", "danger")

    return redirect(url_for("dashboard"))


@app.post("/edit-closing/<int:closing_id>")
def edit_closing(closing_id):
    """Edit a daily closing (update sale/notes and reallocate)."""
    closing = db.session.get(DailyClosing, closing_id)
    if not closing:
        flash("Closing not found.", "warning")
        return redirect(url_for("dashboard"))

    try:
        # Read new values
        new_sale_cents = dollars_to_cents(request.form["sale"])
        new_notes = request.form.get("notes", "").strip() or None
        inventory_rate = float(request.form.get("inventory_rate", DEFAULT_INVENTORY_RATE))
        ops_rate = float(request.form.get("ops_rate", DEFAULT_OPS_RATE))

        # Reverse old allocations
        post_envelope_tx("FIXED", -closing.fixed_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("OPS", -closing.ops_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("INVENTORY", -closing.inventory_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")
        post_envelope_tx("BUFFER", -closing.buffer_allocation_cents, "edit_reversal", f"Edit reversal {closing.date}")

        # Compute new allocation
        alloc, _ = compute_allocation(new_sale_cents, closing.date)

        # Apply updates
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

    return redirect(url_for("dashboard"))


@app.route("/closings")
def closings():
    from main import DailyClosing
    all_closings = DailyClosing.query.order_by(DailyClosing.date.desc()).all()
    return render_template("closings.html", closings=all_closings, today=date.today())


@app.route("/bills", methods=["GET", "POST"])
def bills():
    from main import db, FixedBill

    if request.method == "POST":
        name = request.form["name"]
        amount = float(request.form["amount"])
        active = "active" in request.form

        new_bill = FixedBill(
            name=name,
            monthly_amount_cents=int(round(amount * 100)),
            is_active=active
        )
        db.session.add(new_bill)
        db.session.commit()
        flash("New fixed bill added!", "success")
        return redirect(url_for("bills"))

    all_bills = FixedBill.query.order_by(FixedBill.name).all()
    return render_template("bills.html", bills=all_bills)


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



    
# ───────────────────────────────
# App entry
# ───────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_default_envelopes()
    app.run(debug=os.getenv("FLASK_ENV") == "development")
