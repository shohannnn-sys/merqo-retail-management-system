"""Catalog and inventory tests: costing, ledger invariants and history protection."""

import pytest

from retvia.core.errors import (
    BusinessRuleError,
    DuplicateError,
    InsufficientStockError,
    ValidationError,
)
from retvia.core.money import round_div
from retvia.core.quantity import MILLI_PER_UNIT
from retvia.services.catalog import ProductInput


def make_product(products, unit_id, **kw):
    data = ProductInput(
        name=kw.pop("name", "চিনি"),
        sku=kw.pop("sku", "SUG-1"),
        unit_id=unit_id,
        purchase_price=kw.pop("purchase_price", 8000),
        selling_price=kw.pop("selling_price", 10000),
        opening_qty=kw.pop("opening_qty", 10_000),
        **kw,
    )
    return products.create(data)


class TestCategories:
    def test_create_and_duplicate(self, categories):
        cid = categories.create("মুদি পণ্য")
        assert cid > 0
        with pytest.raises(DuplicateError):
            categories.create("মুদি পণ্য")

    def test_delete_blocked_when_products_exist(self, categories, products, unit_id):
        cid = categories.create("তেল")
        make_product(products, unit_id, category_id=cid)
        with pytest.raises(BusinessRuleError):
            categories.delete(cid)

    def test_delete_empty(self, categories):
        cid = categories.create("খালি")
        categories.delete(cid)
        assert categories.list() == []


class TestUnits:
    def test_seeded_defaults(self, units):
        names = {u["name"] for u in units.list()}
        assert "পিস" in names and "কেজি" in names

    def test_precision_stored(self, units):
        uid = units.create("লিটার টেস্ট", symbol="L", precision=3)
        assert units.get(uid)["decimal_precision"] == 3

    def test_invalid_precision(self, units):
        with pytest.raises(ValidationError):
            units.create("bad", precision=9)

    def test_delete_blocked_when_used(self, units, unit_id, products):
        make_product(products, unit_id)
        with pytest.raises(BusinessRuleError):
            units.delete(unit_id)


class TestProducts:
    def test_create_sets_opening_stock_and_cost(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        p = products.get(pid)
        assert p["stock_qty"] == 10_000
        assert p["avg_cost"] == 8000
        assert p["stock_value"] == 80_000  # 10 units × 80.00

    def test_duplicate_sku_rejected(self, products, unit_id):
        make_product(products, unit_id, sku="DUP")
        with pytest.raises(DuplicateError):
            make_product(products, unit_id, sku="DUP", name="অন্য")

    def test_duplicate_barcode_rejected(self, products, unit_id):
        make_product(products, unit_id, sku="A", barcode="123456")
        with pytest.raises(DuplicateError):
            make_product(products, unit_id, sku="B", barcode="123456")

    def test_bangla_name_search(self, products, unit_id):
        make_product(products, unit_id, name="সয়াবিন তেল", sku="OIL-1")
        result = products.search(query="সয়াবিন")
        assert result["total"] == 1

    def test_search_by_barcode_and_sku(self, products, unit_id):
        make_product(products, unit_id, sku="RICE-9", barcode="890123")
        assert products.search(query="890123")["total"] == 1
        assert products.search(query="rice-9")["total"] == 1

    def test_pagination(self, products, unit_id):
        for i in range(25):
            make_product(products, unit_id, sku=f"P{i}", name=f"পণ্য {i}")
        page1 = products.search(limit=10, offset=0)
        page2 = products.search(limit=10, offset=10)
        assert page1["total"] == 25
        assert len(page1["rows"]) == 10
        assert {r["id"] for r in page1["rows"]}.isdisjoint({r["id"] for r in page2["rows"]})

    def test_archive(self, products, unit_id):
        pid = make_product(products, unit_id)
        products.set_status(pid, "archived")
        assert products.search(status="active")["total"] == 0
        assert products.search(status="archived")["total"] == 1

    def test_delete_untouched_product(self, products, unit_id):
        pid = make_product(products, unit_id)
        products.delete(pid)
        assert products.count() == 0

    def test_stock_filters(self, products, unit_id):
        make_product(products, unit_id, sku="OUT", opening_qty=0, min_stock_qty=5_000)
        make_product(products, unit_id, sku="LOW", opening_qty=2_000, min_stock_qty=5_000)
        make_product(products, unit_id, sku="OK", opening_qty=50_000, min_stock_qty=5_000)
        assert products.search(stock_filter="out")["total"] == 1
        assert products.search(stock_filter="low")["total"] == 1
        assert products.search(stock_filter="in")["total"] == 2


class TestBarcodes:
    def test_lookup(self, products, barcodes, unit_id):
        pid = make_product(products, unit_id, barcode="555000")
        found = barcodes.lookup("555000")
        assert found is not None and found["id"] == pid

    def test_unknown_code_returns_none(self, barcodes):
        assert barcodes.lookup("nope") is None

    def test_generate_is_unique(self, products, barcodes, unit_id):
        pid = make_product(products, unit_id)
        code = barcodes.generate(pid)
        assert barcodes.lookup(code)["id"] == pid

    def test_multi_barcode_per_product(self, products, barcodes, unit_id):
        pid = make_product(products, unit_id, barcode="111")
        barcodes.add(pid, "222")
        assert len(barcodes.for_product(pid)) == 2
        assert barcodes.lookup("222")["id"] == pid


class TestInventoryCosting:
    def test_moving_average_on_receipt(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        # Receive 10 more at 100.00 -> MAC should become 90.00
        inventory.apply_movement(
            product_id=pid,
            qty_delta=10_000,
            movement_type="purchase",
            movement_date="2026-01-02",
            unit_cost=10_000,
        )
        p = products.get(pid)
        assert p["stock_qty"] == 20_000
        assert p["avg_cost"] == 9000
        assert p["stock_value"] == 180_000

    def test_issue_does_not_change_mac(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        result = inventory.apply_movement(
            product_id=pid,
            qty_delta=-3_000,
            movement_type="sale",
            movement_date="2026-01-03",
        )
        p = products.get(pid)
        assert p["avg_cost"] == 8000
        assert p["stock_qty"] == 7_000
        assert result.value_delta == -24_000  # COGS 3 × 80.00
        assert p["stock_value"] == 56_000

    def test_negative_stock_blocked_by_default(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=1_000)
        with pytest.raises(InsufficientStockError):
            inventory.apply_movement(
                product_id=pid,
                qty_delta=-2_000,
                movement_type="sale",
                movement_date="2026-01-01",
            )

    def test_negative_stock_allowed_when_enabled(self, products, inventory, settings, unit_id):
        settings.set("allow_negative_stock", "1")
        pid = make_product(products, unit_id, opening_qty=1_000)
        inventory.apply_movement(
            product_id=pid,
            qty_delta=-2_000,
            movement_type="sale",
            movement_date="2026-01-01",
        )
        assert products.get(pid)["stock_qty"] == -1_000

    def test_empty_shelf_has_zero_value(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=3_000, purchase_price=3333)
        inventory.apply_movement(
            product_id=pid,
            qty_delta=-3_000,
            movement_type="sale",
            movement_date="2026-01-01",
        )
        p = products.get(pid)
        assert p["stock_qty"] == 0
        assert p["stock_value"] == 0

    def test_fractional_quantity_costing(self, products, inventory, kg_unit_id):
        pid = make_product(
            products,
            kg_unit_id,
            name="চাল",
            sku="RICE",
            opening_qty=2_500,
            purchase_price=6000,
        )
        result = inventory.apply_movement(
            product_id=pid,
            qty_delta=-1_250,
            movement_type="sale",
            movement_date="2026-01-01",
        )
        assert result.value_delta == -round_div(6000 * 1250, MILLI_PER_UNIT)
        assert products.get(pid)["stock_qty"] == 1_250

    def test_ledger_reconciles_after_many_movements(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=100_000, purchase_price=7_777)
        for i in range(1, 21):
            inventory.apply_movement(
                product_id=pid,
                qty_delta=3_000,
                movement_type="purchase",
                movement_date="2026-01-01",
                unit_cost=7_000 + i * 137,
            )
            inventory.apply_movement(
                product_id=pid,
                qty_delta=-4_500,
                movement_type="sale",
                movement_date="2026-01-01",
            )
        assert inventory.reconcile() == []
        p = products.get(pid)
        assert p["stock_qty"] == 100_000 + 20 * 3_000 - 20 * 4_500

    def test_non_stock_product_does_not_move_quantity(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, name="সার্ভিস", sku="SVC", track_stock=False)
        inventory.apply_movement(
            product_id=pid,
            qty_delta=-1_000,
            movement_type="sale",
            movement_date="2026-01-01",
        )
        assert products.get(pid)["stock_qty"] == 0


class TestAdjustments:
    def test_damage_reduces_stock_and_value(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        result = inventory.adjust(
            product_id=pid,
            adjustment_type="damage",
            quantity=2_000,
            reason="ভেঙে গেছে",
            adjustment_date="2026-01-05",
        )
        assert result["qty_delta"] == -2_000
        assert result["value_delta"] == -16_000
        assert products.get(pid)["stock_qty"] == 8_000
        assert inventory.reconcile() == []

    def test_write_off_value_reported(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        inventory.adjust(
            product_id=pid,
            adjustment_type="expiry",
            quantity=1_000,
            reason="মেয়াদ শেষ",
            adjustment_date="2026-01-05",
        )
        assert inventory.write_off_value("2026-01-01", "2026-01-31") == 8_000

    def test_physical_count_increase(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        result = inventory.adjust(
            product_id=pid,
            adjustment_type="count_increase",
            quantity=0,
            counted_qty=12_000,
            reason="গণনায় বেশি",
            adjustment_date="2026-01-05",
        )
        assert result["qty_delta"] == 2_000
        assert products.get(pid)["stock_qty"] == 12_000

    def test_count_direction_validated(self, products, inventory, unit_id):
        pid = make_product(products, unit_id, opening_qty=10_000)
        with pytest.raises(ValidationError):
            inventory.adjust(
                product_id=pid,
                adjustment_type="count_increase",
                quantity=0,
                counted_qty=5_000,
                reason="x",
                adjustment_date="2026-01-05",
            )

    def test_reason_required(self, products, inventory, unit_id):
        pid = make_product(products, unit_id)
        with pytest.raises(ValidationError):
            inventory.adjust(
                product_id=pid,
                adjustment_type="loss",
                quantity=1_000,
                reason="  ",
                adjustment_date="2026-01-05",
            )

    def test_valuation_totals(self, products, inventory, unit_id):
        make_product(products, unit_id, sku="A", opening_qty=10_000, purchase_price=5000)
        make_product(products, unit_id, sku="B", opening_qty=5_000, purchase_price=2000)
        v = inventory.valuation()
        assert v["total_value"] == 50_000 + 10_000
        assert v["product_count"] == 2
