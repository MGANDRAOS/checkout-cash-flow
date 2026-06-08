from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from models import db, StockItem, StockEvent


def test_create_stock_item_defaults(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", subgroup="Beer",
                       alert_threshold=6)
        db.session.add(si)
        db.session.commit()

        got = StockItem.query.filter_by(itm_code="ALM330").one()
        assert got.id is not None
        assert got.active is True
        assert got.alert_threshold == 6
        assert isinstance(got.created_at, datetime)


def test_create_stock_event_and_relationship(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", subgroup="Beer",
                       alert_threshold=6)
        db.session.add(si)
        db.session.flush()

        ev = StockEvent(stock_item_id=si.id, event_type="count", qty=22.0,
                        event_date=date(2026, 6, 8), source="manual")
        db.session.add(ev)
        db.session.commit()

        rows = StockEvent.query.filter_by(stock_item_id=si.id).all()
        assert len(rows) == 1
        assert rows[0].event_type == "count"
        assert rows[0].qty == 22.0
        assert rows[0].source == "manual"
        assert rows[0].invoice_id is None
        assert isinstance(rows[0].created_at, datetime)
        # backref wires event -> item
        assert rows[0].item is si


def test_itm_code_is_unique(app):
    with app.app_context():
        db.session.add(StockItem(itm_code="DUP", title="First", alert_threshold=5))
        db.session.commit()
        db.session.add(StockItem(itm_code="DUP", title="Second", alert_threshold=5))
        with pytest.raises(IntegrityError):
            db.session.commit()
