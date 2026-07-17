from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from models import db, Supplier, SupplierItem


def test_create_supplier_defaults(app):
    with app.app_context():
        s = Supplier(name="Acme Beverages")
        db.session.add(s)
        db.session.commit()

        got = Supplier.query.filter_by(name="Acme Beverages").one()
        assert got.id is not None
        assert got.active is True
        assert isinstance(got.created_at, datetime)


def test_supplier_name_is_unique(app):
    with app.app_context():
        db.session.add(Supplier(name="Dup Supplier"))
        db.session.commit()
        db.session.add(Supplier(name="Dup Supplier"))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_create_supplier_item_defaults_and_required_fields(app):
    with app.app_context():
        s = Supplier(name="Acme Beverages")
        db.session.add(s)
        db.session.flush()

        item = SupplierItem(supplier_id=s.id, name="Almaza 330ml Case",
                            unit_price_usd_cents=125)
        db.session.add(item)
        db.session.commit()

        got = SupplierItem.query.filter_by(supplier_id=s.id).one()
        assert got.id is not None
        assert got.active is True
        assert got.category == ""
        assert got.format_label == ""
        assert got.name == "Almaza 330ml Case"
        assert got.unit_price_usd_cents == 125
        assert isinstance(got.created_at, datetime)


def test_supplier_items_relationship_and_backref(app):
    with app.app_context():
        s = Supplier(name="Acme Beverages")
        db.session.add(s)
        db.session.flush()

        item = SupplierItem(supplier_id=s.id, name="Almaza 330ml Case",
                            unit_price_usd_cents=125)
        db.session.add(item)
        db.session.commit()

        assert item in s.items
        assert item.supplier is s


def test_deleting_supplier_cascades_to_items(app):
    with app.app_context():
        s = Supplier(name="Acme Beverages")
        db.session.add(s)
        db.session.flush()

        item = SupplierItem(supplier_id=s.id, name="Almaza 330ml Case",
                            unit_price_usd_cents=125)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

        db.session.delete(s)
        db.session.commit()

        assert SupplierItem.query.filter_by(id=item_id).first() is None


def test_supplier_item_itm_code_defaults_to_none(app):
    with app.app_context():
        s = Supplier(name="Acme Beverages")
        db.session.add(s)
        db.session.flush()

        item = SupplierItem(supplier_id=s.id, name="Almaza 330ml Case",
                            unit_price_usd_cents=125)
        db.session.add(item)
        db.session.commit()

        got = SupplierItem.query.filter_by(supplier_id=s.id).one()
        assert got.itm_code is None
