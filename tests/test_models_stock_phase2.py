from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from models import db, StockItem, StockEvent, StockItemAlias


def test_stock_event_cost_and_batch_nullable(app):
    with app.app_context():
        si = StockItem(itm_code="ALM330", title="Almaza 330", alert_threshold=5)
        db.session.add(si)
        db.session.flush()
        db.session.add(StockEvent(stock_item_id=si.id, event_type="count", qty=10,
                                  event_date=date.today(), source="manual"))
        db.session.add(StockEvent(stock_item_id=si.id, event_type="receive", qty=24,
                                  event_date=date.today(), source="invoice",
                                  unit_cost_cents=150, batch_id="batch-xyz"))
        db.session.commit()
        evs = StockEvent.query.filter_by(stock_item_id=si.id).order_by(StockEvent.id).all()
        assert evs[0].unit_cost_cents is None and evs[0].batch_id is None
        assert evs[1].unit_cost_cents == 150 and evs[1].batch_id == "batch-xyz"


def test_alias_unique(app):
    with app.app_context():
        db.session.add(StockItemAlias(raw_description="ALMAZA 33CL", itm_code="ALM330"))
        db.session.commit()
        db.session.add(StockItemAlias(raw_description="ALMAZA 33CL", itm_code="OTHER"))
        with pytest.raises(IntegrityError):
            db.session.commit()
