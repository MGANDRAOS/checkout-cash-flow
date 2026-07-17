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


def get_setting(key: str, default: str = None) -> str:
    setting = db.session.get(AppSetting, key)
    return setting.value if setting else default


def set_setting(key: str, value: str) -> None:
    setting = db.session.get(AppSetting, key)
    if setting:
        setting.value = value
    else:
        db.session.add(AppSetting(key=key, value=value))
    db.session.commit()


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


class StockItem(db.Model):
    """An item whose on-hand stock is tracked manually (local-only).

    POS is never written for stock. `title`/`subgroup` are cached POS snapshots
    captured when the item is added, so the list renders without a POS hit.
    """
    __tablename__ = "stock_items"

    id = db.Column(db.Integer, primary_key=True)
    itm_code = db.Column(db.String(128), nullable=False, unique=True, index=True)
    title = db.Column(db.String(255), nullable=False, default="")
    subgroup = db.Column(db.String(255), nullable=False, default="")
    alert_threshold = db.Column(db.Integer, nullable=False, default=5)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    events = db.relationship("StockEvent", backref="item",
                             cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<StockItem {self.itm_code} thr={self.alert_threshold}>"


class StockEvent(db.Model):
    """A ledger entry for a tracked item.

    event_type 'count'   -> qty is the ABSOLUTE on-hand as of event_date (manual).
    event_type 'receive' -> qty is a +DELTA received on event_date (Phase 2: invoices).
    Live stock = latest count qty + receives after it - net units sold since it.
    """
    __tablename__ = "stock_events"

    id = db.Column(db.Integer, primary_key=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"),
                              nullable=False, index=True)
    event_type = db.Column(db.String(16), nullable=False)   # 'count' | 'receive'
    qty = db.Column(db.Float, nullable=False)
    event_date = db.Column(db.Date, nullable=False, index=True)
    # Exact moment a 'count' was taken, in LOCAL time (comparable to POS RCPT_DATE).
    # The deduction window starts here, so a count taken any time of day only
    # deducts sales AFTER it. NULL on receives and on legacy counts (-> 08:00 fallback).
    counted_at = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(16), nullable=False, default="manual")  # 'manual' | 'invoice'
    invoice_id = db.Column(db.Integer, nullable=True)  # Phase 2 seam
    unit_cost_cents = db.Column(db.Integer, nullable=True)   # per-unit cost from invoice (Phase 2)
    batch_id = db.Column(db.String(36), nullable=True, index=True)  # groups one invoice import
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<StockEvent item={self.stock_item_id} {self.event_type} qty={self.qty} {self.event_date}>"


class StockItemAlias(db.Model):
    """Remembers that an invoice's printed item text maps to a POS item code.

    Lets repeat invoices auto-match instantly. Global (not per-supplier) by design.
    """
    __tablename__ = "stock_item_aliases"

    id = db.Column(db.Integer, primary_key=True)
    raw_description = db.Column(db.String(255), nullable=False, unique=True, index=True)
    itm_code = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<StockItemAlias {self.raw_description!r} -> {self.itm_code}>"


class Supplier(db.Model):
    """A goods supplier whose price catalog is imported/maintained locally."""
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    items = db.relationship("SupplierItem", backref="supplier",
                            cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<Supplier {self.name}>"


class SupplierItem(db.Model):
    """One catalog line from a supplier's price list.

    Prices are USD cents (the source spreadsheets' native currency; LBP is
    derived at render time via config.USD_EXCHANGE_RATE, not stored). itm_code
    links to StockItem.itm_code once matched via the /supplier-reorder/match
    screen; NULL means unmatched (catalog-only, not tied to tracked stock).
    """
    __tablename__ = "supplier_items"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(128), nullable=False, default="")
    format_label = db.Column(db.String(64), nullable=False, default="")
    case_price_usd_cents = db.Column(db.Integer, nullable=True)
    unit_price_usd_cents = db.Column(db.Integer, nullable=False)
    source_ref = db.Column(db.String(64), nullable=True)
    source_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    itm_code = db.Column(db.String(128), nullable=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SupplierItem {self.name!r} supplier={self.supplier_id} ${self.unit_price_usd_cents/100:.2f}>"
