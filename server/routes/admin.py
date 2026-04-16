"""
Admin dashboard routes.
Protected by session-based login. Single admin account from .env.
"""
import secrets
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

import config
from models import db, Customer

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin.customers"))
        flash("Invalid credentials.", "danger")
    return render_template("admin/login.html")


@admin_bp.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/admin/customers")
@admin_required
def customers():
    sort = request.args.get("sort", "created")
    q = request.args.get("q", "").strip()

    query = Customer.query
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))

    if sort == "renewal":
        query = query.order_by(Customer.maintenance_renewal.asc().nullslast())
    elif sort == "heartbeat":
        query = query.order_by(Customer.last_heartbeat.desc().nullslast())
    elif sort == "status":
        query = query.order_by(Customer.status.asc())
    else:
        query = query.order_by(Customer.created_at.desc())

    all_customers = query.all()
    return render_template("admin/customers.html", customers=all_customers, q=q)


@admin_bp.route("/admin/customers/new", methods=["GET", "POST"])
@admin_required
def customer_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return render_template("admin/customer_new.html")

        customer = Customer(
            name=name,
            email=request.form.get("email", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            activation_key=secrets.token_hex(32),
            status="pending",
            purchase_date=_parse_date(request.form.get("purchase_date")),
            amount_paid=_parse_decimal(request.form.get("amount_paid")),
            payment_notes=request.form.get("payment_notes", "").strip() or None,
        )
        db.session.add(customer)
        db.session.commit()
        flash(f"Customer '{name}' created. Activation key ready to copy.", "success")
        return redirect(url_for("admin.customer_detail", id=customer.id))

    return render_template("admin/customer_new.html")


@admin_bp.route("/admin/customers/<int:id>")
@admin_required
def customer_detail(id):
    customer = Customer.query.get_or_404(id)
    heartbeats = customer.heartbeats.order_by(
        db.text("timestamp DESC")
    ).limit(50).all()
    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        heartbeats=heartbeats,
        today=date.today(),
    )


@admin_bp.post("/admin/customers/<int:id>/suspend")
@admin_required
def customer_suspend(id):
    customer = Customer.query.get_or_404(id)
    if customer.status == "active":
        customer.status = "suspended"
        db.session.commit()
        flash(f"'{customer.name}' suspended.", "warning")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/revoke")
@admin_required
def customer_revoke(id):
    customer = Customer.query.get_or_404(id)
    if customer.status in ("active", "suspended"):
        customer.status = "revoked"
        db.session.commit()
        flash(f"'{customer.name}' revoked.", "danger")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/reactivate")
@admin_required
def customer_reactivate(id):
    customer = Customer.query.get_or_404(id)
    if customer.status == "suspended":
        customer.status = "active"
        db.session.commit()
        flash(f"'{customer.name}' reactivated.", "success")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/deactivate")
@admin_required
def customer_deactivate(id):
    customer = Customer.query.get_or_404(id)
    customer.hw_fingerprint = None
    customer.status = "pending"
    db.session.commit()
    flash(f"'{customer.name}' deactivated. Key can be re-activated on a new machine.", "info")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/extend")
@admin_required
def customer_extend(id):
    customer = Customer.query.get_or_404(id)
    if customer.maintenance_renewal:
        customer.maintenance_renewal = customer.maintenance_renewal + timedelta(days=365)
    else:
        customer.maintenance_renewal = date.today() + timedelta(days=365)
    db.session.commit()
    flash(f"Maintenance extended to {customer.maintenance_renewal}.", "success")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.route("/admin/renewals")
@admin_required
def renewals():
    customers_list = Customer.query.filter(
        Customer.status.in_(["active", "suspended", "pending"])
    ).order_by(Customer.maintenance_renewal.asc().nullslast()).all()

    today_date = date.today()
    thirty_days = today_date + timedelta(days=30)

    stats = {
        "total_active": Customer.query.filter_by(status="active").count(),
        "overdue": Customer.query.filter(
            Customer.maintenance_renewal < today_date,
            Customer.status.in_(["active", "suspended"]),
        ).count(),
        "due_this_month": Customer.query.filter(
            Customer.maintenance_renewal >= today_date,
            Customer.maintenance_renewal <= thirty_days,
            Customer.status.in_(["active", "suspended"]),
        ).count(),
    }

    return render_template(
        "admin/renewals.html",
        customers=customers_list,
        today=today_date,
        thirty_days=thirty_days,
        stats=stats,
    )


def _parse_date(val):
    if not val or not val.strip():
        return None
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_decimal(val):
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None
