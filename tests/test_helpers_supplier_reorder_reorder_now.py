from datetime import date, datetime, timedelta
from unittest.mock import patch

from models import db, StockItem, StockEvent, Supplier, SupplierItem
from helpers_supplier_reorder import reorder_now


def _make_supplier(name="Box4Less"):
    s = Supplier(name=name)
    db.session.add(s)
    db.session.flush()
    return s


def _needs_reorder_item(itm_code="ALM330", title="Almaza 330", threshold=10, qty=5):
    """A StockItem whose only count leaves it under threshold -> needs_reorder=True
    once sold=0 (units_sold_since mocked to {}). live=qty, need=threshold-qty=5,
    so reorder_qty is deterministically 5 (see helpers_stock.stock_analytics)."""
    si = StockItem(itm_code=itm_code, title=title, subgroup="Beer", alert_threshold=threshold)
    db.session.add(si)
    db.session.flush()
    db.session.add(StockEvent(
        stock_item_id=si.id, event_type="count", qty=qty,
        event_date=date.today() - timedelta(days=1),
        counted_at=datetime.now() - timedelta(days=1),
    ))
    db.session.commit()
    return si


def _well_stocked_item(itm_code="PEPSI1L", title="Pepsi 1L", threshold=5, qty=500):
    si = StockItem(itm_code=itm_code, title=title, subgroup="Bev", alert_threshold=threshold)
    db.session.add(si)
    db.session.flush()
    db.session.add(StockEvent(
        stock_item_id=si.id, event_type="count", qty=qty,
        event_date=date.today() - timedelta(days=1),
        counted_at=datetime.now() - timedelta(days=1),
    ))
    db.session.commit()
    return si


class TestReorderNowUnpriced:
    def test_needs_reorder_item_with_no_match_has_empty_options(self, app):
        with app.app_context():
            _needs_reorder_item()
            with patch("helpers_stock.units_sold_since", return_value={}):
                result = reorder_now()

            assert len(result["items"]) == 1
            row = result["items"][0]
            assert row["itm_code"] == "ALM330"
            assert row["reorder_qty"] == 5
            assert row["options"] == []
            assert row["chosen_supplier_item_id"] is None
            assert row["line_total_cents"] is None
            assert result["unpriced_count"] == 1
            assert result["totals_by_supplier_cents"] == {}
            assert result["live_unavailable"] is False


class TestReorderNowPriced:
    def test_matched_supplier_item_is_chosen_and_totaled(self, app):
        with app.app_context():
            _needs_reorder_item()
            sup = _make_supplier("Box4Less")
            db.session.add(SupplierItem(supplier_id=sup.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150,
                                         itm_code="ALM330"))
            db.session.commit()

            with patch("helpers_stock.units_sold_since", return_value={}):
                result = reorder_now()

            assert len(result["items"]) == 1
            row = result["items"][0]
            assert len(row["options"]) == 1
            assert row["options"][0]["unit_price_usd_cents"] == 150
            assert row["chosen_supplier_item_id"] == row["options"][0]["supplier_item_id"]
            assert row["line_total_cents"] == 150 * row["reorder_qty"]
            assert result["totals_by_supplier_cents"] == {"Box4Less": 150 * row["reorder_qty"]}
            assert result["unpriced_count"] == 0

    def test_cheapest_supplier_item_chosen_when_multiple_match(self, app):
        with app.app_context():
            _needs_reorder_item()
            cheap = _make_supplier("CheapCo")
            pricey = _make_supplier("PriceyCo")
            db.session.add(SupplierItem(supplier_id=pricey.id, name="Almaza Can 33cl (A)",
                                         category="Beer", unit_price_usd_cents=200,
                                         itm_code="ALM330"))
            cheap_item = SupplierItem(supplier_id=cheap.id, name="Almaza Can 33cl (B)",
                                       category="Beer", unit_price_usd_cents=120,
                                       itm_code="ALM330")
            db.session.add(cheap_item)
            db.session.commit()
            cheap_item_id = cheap_item.id

            with patch("helpers_stock.units_sold_since", return_value={}):
                result = reorder_now()

            row = result["items"][0]
            assert len(row["options"]) == 2
            prices = [o["unit_price_usd_cents"] for o in row["options"]]
            assert prices == sorted(prices)
            assert row["chosen_supplier_item_id"] == cheap_item_id

    def test_inactive_supplier_item_excluded_from_options(self, app):
        with app.app_context():
            _needs_reorder_item()
            sup = _make_supplier("Box4Less")
            db.session.add(SupplierItem(supplier_id=sup.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150,
                                         itm_code="ALM330", active=False))
            db.session.commit()

            with patch("helpers_stock.units_sold_since", return_value={}):
                result = reorder_now()

            row = result["items"][0]
            assert row["options"] == []
            assert row["chosen_supplier_item_id"] is None
            assert result["unpriced_count"] == 1


class TestReorderNowExclusions:
    def test_well_stocked_item_not_included(self, app):
        with app.app_context():
            _well_stocked_item()
            with patch("helpers_stock.units_sold_since", return_value={}):
                result = reorder_now()

            assert result["items"] == []
            assert result["unpriced_count"] == 0


class TestReorderNowPosUnavailable:
    def test_units_sold_since_exception_sets_live_unavailable(self, app):
        with app.app_context():
            _needs_reorder_item()
            with patch("helpers_stock.units_sold_since",
                       side_effect=RuntimeError("pos down")):
                result = reorder_now()

            assert result["live_unavailable"] is True
            # sold defaults to 0 for every item when the POS call fails, so the
            # low-stock item still surfaces (using the ledger's own numbers).
            assert len(result["items"]) == 1
