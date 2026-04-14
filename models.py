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
    payment_mode = db.Column(db.String(20))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FixedBill(db.Model):
    """Recurring monthly fixed bills (used to compute daily fixed goal)."""
    __tablename__ = "fixed_bills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    monthly_amount_cents = db.Column(db.Integer, nullable=False)
    frequency = db.Column(db.String(16), default="monthly")   # 'monthly'|'weekly'|'installment'|'one_time'
    due_rule = db.Column(db.String(64))                       # e.g., 'day=25', 'weekday=FRI', 'immediate'
    installments_total = db.Column(db.Integer)                # e.g., Mario 7
    installments_paid = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(255))
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
    
    
class FixedCollection(db.Model):
    """Manual log of actual Fixed envelope cash collected."""
    __tablename__ = "fixed_collections"

    id = db.Column(db.Integer, primary_key=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    collected_on = db.Column(db.Date, nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# === [ADD new model below FixedCollection] ================================
class Expense(db.Model):
    """Every payout: either BILLS (obligations) or SPEND (restock/ops)."""
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)                           # expense date
    description = db.Column(db.String(255), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(64))                                  # Restock, Cleaning, Maintenance,...
    vendor = db.Column(db.String(128))
    payment_method = db.Column(db.String(32))                            # Cash/Transfer/Other

    # Link to envelope + optional fixed bill
    envelope_id = db.Column(db.Integer, db.ForeignKey("envelopes.id"), nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey("fixed_bills.id"))    # nullable

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    envelope = db.relationship("Envelope", lazy=True)
    bill = db.relationship("FixedBill", lazy=True)
# =========================================================================


# === [ADD new mini accounting models below Expense] =======================
class Supplier(db.Model):
    """
    Supplier / vendor master record.
    Used by payables so we do not keep repeating supplier names everywhere.
    """
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    phone = db.Column(db.String(32))
    notes = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Supplier {self.name}>"


class Payable(db.Model):
    """
    Supplier bill / amount owed.
    This does NOT move cash by itself.
    Cash only moves later when an actual payment is recorded.
    """
    __tablename__ = "payables"

    id = db.Column(db.Integer, primary_key=True)

    # Core supplier/bill info
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False)
    bill_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    reference = db.Column(db.String(64))                # invoice number / bill reference
    description = db.Column(db.String(255), nullable=False)

    # Money fields
    total_amount_cents = db.Column(db.Integer, nullable=False)
    paid_amount_cents = db.Column(db.Integer, nullable=False, default=0)
    remaining_amount_cents = db.Column(db.Integer, nullable=False)

    # Status: pending | partial | paid | overdue
    status = db.Column(db.String(20), nullable=False, default="pending")

    # Optional notes
    notes = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    supplier = db.relationship("Supplier", backref=db.backref("payables", lazy=True))

    def __repr__(self):
        return f"<Payable {self.id} - {self.description}>"

    def refresh_status(self):
        """
        Recalculate remaining amount and status after any payment change.
        Keep this logic inside the model so later routes stay cleaner.
        """
        paid = self.paid_amount_cents or 0
        total = self.total_amount_cents or 0

        self.remaining_amount_cents = max(total - paid, 0)

        if self.remaining_amount_cents <= 0:
            self.status = "paid"
        elif paid > 0:
            self.status = "partial"
        else:
            # Only mark overdue if due_date exists and is already passed
            if self.due_date and self.due_date < datetime.utcnow().date():
                self.status = "overdue"
            else:
                self.status = "pending"


class PayablePayment(db.Model):
    """
    Each real payment made against a payable.
    This is the payment history table.
    In the next step, page logic will also use this to create cash movement.
    """
    __tablename__ = "payable_payments"

    id = db.Column(db.Integer, primary_key=True)
    payable_id = db.Column(db.Integer, db.ForeignKey("payables.id"), nullable=False)

    payment_date = db.Column(db.Date, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)

    # Optional operational fields
    payment_method = db.Column(db.String(32))           # Cash / Transfer / Other
    envelope_id = db.Column(db.Integer, db.ForeignKey("envelopes.id"))  # optional for later linkage
    notes = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payable = db.relationship("Payable", backref=db.backref("payments", lazy=True, cascade="all, delete-orphan"))
    envelope = db.relationship("Envelope", lazy=True)

    def __repr__(self):
        return f"<PayablePayment {self.id} - {self.amount_cents}>"
# =========================================================================



# === [UPDATE simple cash-summary model] ===================================
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
# =========================================================================