"""SQLAlchemy models for the license server."""
from datetime import datetime, timezone
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    activation_key = db.Column(db.String(64), unique=True, nullable=False)
    hw_fingerprint = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="pending")
    license_expiry = db.Column(db.DateTime(timezone=True))
    last_heartbeat = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Billing
    purchase_date = db.Column(db.Date)
    maintenance_renewal = db.Column(db.Date)
    amount_paid = db.Column(db.Numeric(10, 2))
    payment_notes = db.Column(db.Text)

    heartbeats = db.relationship("HeartbeatLog", backref="customer", lazy="dynamic")

    VALID_STATUSES = ("pending", "active", "suspended", "revoked")

    def __repr__(self):
        return f"<Customer {self.name} [{self.status}]>"


class HeartbeatLog(db.Model):
    __tablename__ = "heartbeat_log"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    hw_fingerprint = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    app_version = db.Column(db.String(20))

    def __repr__(self):
        return f"<HeartbeatLog customer={self.customer_id} at={self.timestamp}>"
