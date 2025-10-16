from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy instance will be created in main.py and imported here
db = SQLAlchemy()


class Envelope(db.Model):
    """Cash envelope (Inventory, Fixed, Ops, Buffer)."""
    __tablename__ = "envelopes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=False)
    balance_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EnvelopeTransaction(db.Model):
    """Tracks every inflow/outflow from each envelope."""
    __tablename__ = "envelope_transactions"

    id = db.Column(db.Integer, primary_key=True)
    envelope_id = db.Column(db.Integer, db.ForeignKey("envelopes.id"), nullable=False)
    daily_closing_id = db.Column(db.Integer, db.ForeignKey("daily_closings.id"))  # nullable for manual adjustment
    type = db.Column(db.String(32), nullable=False)  # allocation | adjustment | spend | transfer
    amount_cents = db.Column(db.Integer, nullable=False)  # positive=inflow, negative=outflow
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    envelope = db.relationship("Envelope", backref=db.backref("transactions", lazy=True))


class DailyClosing(db.Model):
    """Daily summary of sales and automatic allocations."""
    __tablename__ = "daily_closings"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    sales_cents = db.Column(db.Integer, nullable=False)
    fixed_allocation_cents = db.Column(db.Integer, default=0)
    ops_allocation_cents = db.Column(db.Integer, default=0)
    inventory_allocation_cents = db.Column(db.Integer, default=0)
    buffer_allocation_cents = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FixedBill(db.Model):
    """Recurring monthly fixed bills (used to compute daily fixed goal)."""
    __tablename__ = "fixed_bills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    monthly_amount_cents = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    custom_start_date = db.Column(db.Date)  # optional: override start-of-month
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSetting(db.Model):
    """Key-value settings for app configuration."""
    __tablename__ = "app_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<AppSetting {self.key}={self.value}>"
