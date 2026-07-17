from models import db, StockItem, Supplier, SupplierItem
from helpers_supplier_reorder import tracked_catalog, unmatched_items, set_match


def _make_supplier(name="Box4Less"):
    s = Supplier(name=name)
    db.session.add(s)
    db.session.flush()
    return s


class TestTrackedCatalog:
    def test_returns_only_active_stock_items_correctly_shaped(self, app):
        with app.app_context():
            db.session.add(StockItem(itm_code="ALM330", title="Almaza 330", subgroup="Beer"))
            db.session.add(StockItem(itm_code="INACTIVE1", title="Old Item", subgroup="Misc",
                                      active=False))
            db.session.commit()

            catalog = tracked_catalog()
            assert catalog == [{"code": "ALM330", "title": "Almaza 330", "subgroup": "Beer"}]

    def test_empty_when_no_stock_items(self, app):
        with app.app_context():
            assert tracked_catalog() == []


class TestUnmatchedItems:
    def test_unmatched_item_shows_up(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150))
            db.session.commit()

            rows = unmatched_items()
            assert len(rows) == 1
            assert rows[0]["name"] == "Almaza Can 33cl"

    def test_already_matched_item_excluded(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Already Matched",
                                         category="Beer", unit_price_usd_cents=150,
                                         itm_code="ALM330"))
            db.session.commit()

            assert unmatched_items() == []

    def test_inactive_supplier_item_excluded(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Inactive Item",
                                         category="Beer", unit_price_usd_cents=150,
                                         active=False))
            db.session.commit()

            assert unmatched_items() == []

    def test_returned_dict_shape_and_supplier_relationship(self, app):
        with app.app_context():
            s = _make_supplier(name="Nice Food")
            db.session.add(SupplierItem(supplier_id=s.id, name="Cheese Block",
                                         category="Dairy", unit_price_usd_cents=499))
            db.session.commit()

            rows = unmatched_items()
            assert len(rows) == 1
            row = rows[0]
            assert set(row.keys()) == {"id", "name", "supplier", "category",
                                        "unit_price_usd_cents", "candidates"}
            assert row["supplier"] == "Nice Food"
            assert row["category"] == "Dairy"
            assert row["unit_price_usd_cents"] == 499

    def test_candidates_nonempty_when_stock_item_matches(self, app):
        with app.app_context():
            db.session.add(StockItem(itm_code="ALM330", title="Almaza Can 33cl", subgroup="Beer"))
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150))
            db.session.commit()

            rows = unmatched_items()
            assert len(rows) == 1
            candidates = rows[0]["candidates"]
            assert len(candidates) > 0
            assert any(c["code"] == "ALM330" for c in candidates)

    def test_ordered_by_category_then_name(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Zebra Water",
                                         category="Beverages", unit_price_usd_cents=100))
            db.session.add(SupplierItem(supplier_id=s.id, name="Apple Juice",
                                         category="Beverages", unit_price_usd_cents=100))
            db.session.add(SupplierItem(supplier_id=s.id, name="Anything",
                                         category="Alcohol", unit_price_usd_cents=100))
            db.session.commit()

            rows = unmatched_items()
            names = [r["name"] for r in rows]
            assert names == ["Anything", "Apple Juice", "Zebra Water"]


class TestSetMatch:
    def test_confirming_a_match_sets_and_persists(self, app):
        with app.app_context():
            s = _make_supplier()
            item = SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                 category="Beer", unit_price_usd_cents=150)
            db.session.add(item)
            db.session.commit()
            item_id = item.id

            ok = set_match(item_id, "ALM330")
            assert ok is True

            got = db.session.get(SupplierItem, item_id)
            assert got.itm_code == "ALM330"

    def test_clearing_a_match_unsets_it(self, app):
        with app.app_context():
            s = _make_supplier()
            item = SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                 category="Beer", unit_price_usd_cents=150,
                                 itm_code="ALM330")
            db.session.add(item)
            db.session.commit()
            item_id = item.id

            ok = set_match(item_id, None)
            assert ok is True

            got = db.session.get(SupplierItem, item_id)
            assert got.itm_code is None

    def test_nonexistent_id_returns_false_without_raising(self, app):
        with app.app_context():
            ok = set_match(999999, "ALM330")
            assert ok is False
