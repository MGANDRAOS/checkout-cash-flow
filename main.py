import os
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Local imports
from models import db, Envelope, DailyClosing, FixedBill
from helpers import (
    dollars_to_cents,
    cents_to_dollars,
    ensure_default_envelopes,
    post_envelope_tx,
    compute_allocation,
    current_month_target_cents,
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

@app.route("/")
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

    return render_template(
        "dashboard.html",
        envelopes=envelopes,
        bills=bills,
        closings=closings,
        currency=CURRENCY,
        funded_pct=funded_pct,
        month_target_cents=month_target,
    )


@app.post("/daily-close")
def daily_close():
    """Perform the end-of-day cash allocation."""
    ensure_default_envelopes()
    try:
        close_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        sale_cents = dollars_to_cents(request.form["sale"])
        inventory_rate = float(request.form.get("inventory_rate", DEFAULT_INVENTORY_RATE))
        ops_rate = float(request.form.get("ops_rate", DEFAULT_OPS_RATE))
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
        return redirect(url_for("dashboard"))

    # Compute allocation
    alloc, debug = compute_allocation(sale_cents, close_date, inventory_rate, ops_rate)

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

    flash(
        f"Closed {close_date}: "
        f"Fixed ${cents_to_dollars(alloc.fixed_cents)}, "
        f"Ops ${cents_to_dollars(alloc.ops_cents)}, "
        f"Inventory ${cents_to_dollars(alloc.inventory_cents)}, "
        f"Buffer ${cents_to_dollars(alloc.buffer_cents)}.",
        "success",
    )
    return redirect(url_for("dashboard"))


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




# ───────────────────────────────
# App entry
# ───────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_default_envelopes()
    app.run(debug=os.getenv("FLASK_ENV") == "development")
