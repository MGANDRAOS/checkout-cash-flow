from models import db, StockItem, Supplier, SupplierItem
from helpers_supplier_reorder import (
    tracked_catalog, unmatched_items, set_match, browse_catalog, list_categories,
)


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


class TestBrowseCatalog:
    def test_no_filters_returns_paginated_results_with_correct_total(self, app):
        with app.app_context():
            s = _make_supplier()
            for i in range(3):
                db.session.add(SupplierItem(supplier_id=s.id, name=f"Item {i}",
                                             category="Beer", unit_price_usd_cents=100))
            db.session.commit()

            result = browse_catalog()
            assert result["total"] == 3
            assert len(result["items"]) == 3
            assert result["page"] == 1
            assert result["page_size"] == 30

    def test_q_filter_is_case_insensitive_substring_match(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150))
            db.session.add(SupplierItem(supplier_id=s.id, name="Cheese Block",
                                         category="Dairy", unit_price_usd_cents=499))
            db.session.commit()

            result = browse_catalog(q="ALMAZA")
            assert len(result["items"]) == 1
            assert result["items"][0]["name"] == "Almaza Can 33cl"

            result = browse_catalog(q="can")
            assert len(result["items"]) == 1
            assert result["items"][0]["name"] == "Almaza Can 33cl"

    def test_category_filter_is_exact_match_only(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150))
            db.session.add(SupplierItem(supplier_id=s.id, name="Cheese Block",
                                         category="Dairy", unit_price_usd_cents=499))
            db.session.commit()

            result = browse_catalog(category="Beer")
            assert len(result["items"]) == 1
            assert result["items"][0]["name"] == "Almaza Can 33cl"

    def test_q_and_category_combine(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Can 33cl",
                                         category="Beer", unit_price_usd_cents=150))
            db.session.add(SupplierItem(supplier_id=s.id, name="Almaza Juice",
                                         category="Beverages", unit_price_usd_cents=120))
            db.session.commit()

            result = browse_catalog(q="Almaza", category="Beer")
            assert len(result["items"]) == 1
            assert result["items"][0]["name"] == "Almaza Can 33cl"

    def test_pagination_slices_correctly_and_total_reflects_full_count(self, app):
        with app.app_context():
            s = _make_supplier()
            for i in range(35):
                db.session.add(SupplierItem(supplier_id=s.id, name=f"Item {i:02d}",
                                             category="Beer", unit_price_usd_cents=100))
            db.session.commit()

            page1 = browse_catalog(page=1, page_size=30)
            assert len(page1["items"]) == 30
            assert page1["total"] == 35

            page2 = browse_catalog(page=2, page_size=30)
            assert len(page2["items"]) == 5
            assert page2["total"] == 35

            page1_names = {r["name"] for r in page1["items"]}
            page2_names = {r["name"] for r in page2["items"]}
            assert page1_names.isdisjoint(page2_names)

    def test_inactive_items_excluded(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="Inactive Item",
                                         category="Beer", unit_price_usd_cents=150,
                                         active=False))
            db.session.commit()

            result = browse_catalog()
            assert result["items"] == []
            assert result["total"] == 0

    def test_row_shape(self, app):
        with app.app_context():
            s = _make_supplier(name="Nice Food")
            db.session.add(SupplierItem(supplier_id=s.id, name="Cheese Block",
                                         category="Dairy", format_label="1kg block",
                                         unit_price_usd_cents=499, case_price_usd_cents=None,
                                         itm_code="CHZ1"))
            db.session.commit()

            result = browse_catalog()
            assert len(result["items"]) == 1
            row = result["items"][0]
            assert set(row.keys()) == {
                "id", "name", "category", "format_label", "supplier", "supplier_id",
                "unit_price_usd_cents", "case_price_usd_cents", "itm_code",
            }
            assert row["supplier"] == "Nice Food"
            assert row["format_label"] == "1kg block"
            assert row["itm_code"] == "CHZ1"


class TestListCategories:
    def test_returns_distinct_sorted_nonempty_categories(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="A", category="Beer",
                                         unit_price_usd_cents=100))
            db.session.add(SupplierItem(supplier_id=s.id, name="B", category="Beer",
                                         unit_price_usd_cents=100))
            db.session.add(SupplierItem(supplier_id=s.id, name="C", category="Dairy",
                                         unit_price_usd_cents=100))
            db.session.add(SupplierItem(supplier_id=s.id, name="D", category="",
                                         unit_price_usd_cents=100))
            db.session.commit()

            cats = list_categories()
            assert cats == ["Beer", "Dairy"]

    def test_excludes_inactive_items_category(self, app):
        with app.app_context():
            s = _make_supplier()
            db.session.add(SupplierItem(supplier_id=s.id, name="A", category="OnlyInactive",
                                         unit_price_usd_cents=100, active=False))
            db.session.commit()

            assert list_categories() == []

    def test_empty_when_no_items(self, app):
        with app.app_context():
            assert list_categories() == []
