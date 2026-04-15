from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy instance will be created in main.py and imported here
db = SQLAlchemy()


class AppSetting(db.Model):
    """Key-value settings for app configuration."""
    __tablename__ = "app_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<AppSetting {self.key}={self.value}>"


class DailyPaidItem(db.Model):
    """
    Manual spending entry used for the Sales vs Spending page.

    Important business logic:
    - paid_date   = when you actually paid
    - source_date = which business day's cash was used
    - payment_type must come from a fixed controlled list
    """
    __tablename__ = "daily_paid_items"

    id = db.Column(db.Integer, primary_key=True)

    # IMPORTANT:
    # paid_date = actual calendar/business date when payment happened
    paid_date = db.Column(db.Date, nullable=False, index=True)

    # IMPORTANT:
    # source_date = which business day cash batch was used
    # Example:
    #   sales of Apr 7 are used on Apr 8 morning
    source_date = db.Column(db.Date, nullable=False, index=True)

    # Basic spending info
    title = db.Column(db.String(255), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)

    # IMPORTANT:
    # keep this controlled in the UI as a dropdown only
    payment_type = db.Column(db.String(32), nullable=False)

    notes = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DailyPaidItem paid={self.paid_date} source={self.source_date} title={self.title}>"
