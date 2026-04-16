"""
Application entry point.

Loads .env, validates config (via import of config.py), wires up SQLAlchemy,
registers blueprints, and defines only the auth + Sales-vs-Spending routes.
All other finance/accounting surface has been removed.
"""
import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# load_dotenv BEFORE config import so config sees the populated env
load_dotenv()

import config  # noqa: E402  (import-after-load_dotenv is intentional)

from models import db, DailyPaidItem, AppSetting, get_setting, set_setting  # noqa: E402

from routes.intelligence import intelligence_bp  # noqa: E402
from routes.items import items_bp
from routes.sales import sales_bp
from routes.ai import ai_bp
from routes.weather import weather_bp
from routes.analytics_assistant import bp as analytics_assistant_bp
from routes.realtime import realtime_bp
from routes.item_trends import item_trends_bp
from routes.items_explorer import items_explorer_bp
from routes.dead_items import dead_items_bp
from routes.reorder_radar import reorder_radar_bp

from helpers_intelligence import (
    get_pos_sales_total_by_range,
    get_pos_sales_daily_by_range,
)

from license_client import get_hw_fingerprint, activate as license_activate
from license_heartbeat import start_heartbeat_thread, notify_activated
from license_middleware import register_license_middleware


# ───────────────────────────────
# Flask app
# ───────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Start license heartbeat daemon
start_heartbeat_thread()

# Register license middleware (runs before require_login)
register_license_middleware(app)


@app.context_processor
def inject_request():
    return dict(request=request)


# ───────────────────────────────
# Sales vs Spending (surviving finance route, rebranded)
# ───────────────────────────────
@app.route("/finance/summary")
def finance_summary():
    """
    Sales vs Spending report.

    - Sales are read live from POS (via helpers_intelligence).
    - Spending is locally-entered DailyPaidItem rows.
    - Remaining = Sales - Spending (per source business day).
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    default_from = today - timedelta(days=today.weekday())
    default_to = today

    from_str = request.args.get("from_date", default_from.isoformat()).strip()
    to_str = request.args.get("to_date", default_to.isoformat()).strip()

    try:
        from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
        to_date = datetime.strptime(to_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date range. Reset to current week.", "warning")
        from_date, to_date = default_from, default_to
        from_str, to_str = from_date.isoformat(), to_date.isoformat()

    if from_date > to_date:
        flash("From date cannot be after To date. Reset to current week.", "warning")
        from_date, to_date = default_from, default_to
        from_str, to_str = from_date.isoformat(), to_date.isoformat()

    if from_date < config.MIN_TRACKING_DATE:
        from_date = config.MIN_TRACKING_DATE
        from_str = from_date.isoformat()
        flash(
            f"Start date adjusted to tracking start ({config.MIN_TRACKING_DATE.isoformat()}).",
            "warning",
        )

    if to_date < config.MIN_TRACKING_DATE:
        to_date = config.MIN_TRACKING_DATE
        to_str = to_date.isoformat()

    total_sales_lbp = float(get_pos_sales_total_by_range(from_date, to_date) or 0.0)

    paid_items = db.session.execute(
        db.select(DailyPaidItem)
        .where(DailyPaidItem.source_date >= from_date)
        .where(DailyPaidItem.source_date <= to_date)
        .order_by(DailyPaidItem.paid_date.desc(), DailyPaidItem.created_at.desc())
    ).scalars().all()

    total_spending_lbp = sum((item.amount_cents or 0) / 100 for item in paid_items)
    total_profit_lbp = total_sales_lbp - total_spending_lbp

    total_sales_usd = total_sales_lbp / config.USD_EXCHANGE_RATE
    total_spending_usd = total_spending_lbp / config.USD_EXCHANGE_RATE
    total_profit_usd = total_profit_lbp / config.USD_EXCHANGE_RATE

    sales_daily_rows = get_pos_sales_daily_by_range(from_date, to_date)

    sales_by_day = {
        row["biz_date"]: float(row["sales_lbp"] or 0.0)
        for row in sales_daily_rows
    }

    spending_by_day: dict[str, float] = {}
    for item in paid_items:
        day_key = item.source_date.isoformat()
        spending_by_day[day_key] = spending_by_day.get(day_key, 0.0) + (
            (item.amount_cents or 0) / 100
        )

    all_days = sorted(
        set(list(sales_by_day.keys()) + list(spending_by_day.keys())),
        reverse=True,
    )

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
            "sales_usd": sales_lbp / config.USD_EXCHANGE_RATE,
            "used_usd": used_lbp / config.USD_EXCHANGE_RATE,
            "remaining_usd": remaining_lbp / config.USD_EXCHANGE_RATE,
        })

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
        usd_exchange_rate=config.USD_EXCHANGE_RATE,
        paid_item_types=config.PAID_ITEM_TYPES,
        default_paid_date_str=default_paid_date_str,
        default_source_date_str=default_source_date_str,
        currency=config.CURRENCY,
    )


@app.post("/finance/summary/add-paid-item")
def finance_summary_add_paid_item():
    """Add a manual paid item for the Sales vs Spending page."""
    try:
        paid_date = datetime.strptime(request.form["paid_date"], "%Y-%m-%d").date()
        source_date = datetime.strptime(request.form["source_date"], "%Y-%m-%d").date()
        title = request.form["title"].strip()
        amount_lbp_raw = request.form.get("amount_lbp", "").strip()
        amount_usd_raw = request.form.get("amount_usd", "").strip()
        amount_lbp = 0.0

        if amount_usd_raw:
            amount_usd = float(amount_usd_raw)
            if amount_usd <= 0:
                raise ValueError("USD amount must be greater than zero.")
            amount_lbp = amount_usd * config.USD_EXCHANGE_RATE
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
        if payment_type not in config.PAID_ITEM_TYPES:
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

    from_str = request.form.get("from_date_redirect", "").strip()
    to_str = request.form.get("to_date_redirect", "").strip()
    if from_str and to_str:
        return redirect(url_for("finance_summary", from_date=from_str, to_date=to_str))
    return redirect(url_for("finance_summary"))


# ───────────────────────────────
# Settings page (AI features toggle)
# ───────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            ai_on = "true" if request.form.get("ai_summaries_enabled") == "1" else "false"
            set_setting("ai_summaries_enabled", ai_on)
            flash("Settings updated successfully!", "success")
        except Exception as e:
            flash(f"Error saving settings: {e}", "danger")
        return redirect(url_for("settings"))

    ai_enabled = get_setting("ai_summaries_enabled", "true").lower() in ("1", "true", "yes")
    return render_template("settings.html", ai_summaries_enabled=ai_enabled)


# ───────────────────────────────
# License activation
# ───────────────────────────────
@app.route("/activate", methods=["GET", "POST"])
def activate_page():
    if request.method == "POST":
        key = request.form.get("activation_key", "").strip()
        if not key:
            flash("Please enter an activation key.", "danger")
            return render_template("activate.html")

        try:
            hw = get_hw_fingerprint()
            blob, response = license_activate(config.LICENSE_SERVER_URL, key, hw)
            notify_activated(key, blob)

            # Append ACTIVATION_KEY to .env so heartbeat can use it on restart
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            with open(env_path, "a") as f:
                f.write(f"\nACTIVATION_KEY={key}\n")

            flash("License activated successfully!", "success")
            return redirect("/login")
        except RuntimeError as e:
            flash(f"Activation failed: {e}", "danger")
            return render_template("activate.html")

    return render_template("activate.html")


@app.route("/license-expired")
def license_expired_page():
    return render_template("license_expired.html", support_contact=config.SUPPORT_CONTACT)


# ───────────────────────────────
# Auth
# ───────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == config.APP_USERNAME and password == config.APP_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ───────────────────────────────
# Blueprints
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
app.register_blueprint(dead_items_bp)
app.register_blueprint(reorder_radar_bp)


@app.before_request
def require_login():
    allowed_routes = ["login", "static", "activate_page", "license_expired_page"]
    if request.endpoint not in allowed_routes:
        if not session.get("logged_in"):
            return redirect(url_for("login"))


# ───────────────────────────────
# Entry
# ───────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=os.getenv("FLASK_ENV") == "development")
