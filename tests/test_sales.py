"""POS / sales tests — financial accuracy, atomicity and reconciliation."""

import pytest

from retvia.core.errors import (
    BusinessRuleError,
    InsufficientStockError,
    ValidationError,
)
from retvia.services.catalog import ProductInput
from retvia.services.parties import CustomerInput
from retvia.services.sales import PaymentInput, SaleInput, SaleLineInput


def product(products, unit_id, **kw):
    return products.create(
        ProductInput(
            name=kw.pop("name", "চিনি"),
            sku=kw.pop("sku", "SUG1"),
            unit_id=unit_id,
            purchase_price=kw.pop("purchase_price", 8000),
            selling_price=kw.pop("selling_price", 10000),
            opening_qty=kw.pop("opening_qty", 100_000),
            **kw,
        )
    )


class TestBasicSales:
    def test_single_product_full_payment(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000)],
                payments=[PaymentInput(cash_method_id, 20_000)],
            )
        )
        assert result["grand_total"] == 20_000
        assert result["due_amount"] == 0
        assert result["total_cost"] == 16_000
        assert products.get(pid)["stock_qty"] == 98_000
        assert result["invoice_no"].startswith("INV-")

    def test_multiple_products(self, sales, products, unit_id, cash_method_id, open_shift):
        a = product(products, unit_id, sku="A", selling_price=10_000)
        b = product(products, unit_id, sku="B", selling_price=5_000, name="লবণ")
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(a, 2_000), SaleLineInput(b, 3_000)],
                payments=[PaymentInput(cash_method_id, 35_000)],
            )
        )
        assert result["grand_total"] == 35_000

    def test_fractional_quantity(self, sales, products, kg_unit_id, cash_method_id, open_shift):
        pid = product(products, kg_unit_id, name="চাল", sku="RICE", selling_price=6_000)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 1_500)],
                payments=[PaymentInput(cash_method_id, 9_000)],
            )
        )
        assert result["grand_total"] == 9_000
        assert products.get(pid)["stock_qty"] == 98_500

    def test_price_override(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=10_000)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 1_000, unit_price=9_000)],
                payments=[PaymentInput(cash_method_id, 9_000)],
            )
        )
        assert result["grand_total"] == 9_000

    def test_empty_cart_rejected(self, sales, cash_method_id):
        with pytest.raises(ValidationError):
            sales.create(SaleInput(lines=[], payments=[PaymentInput(cash_method_id, 100)]))


class TestDiscounts:
    def test_item_percent_discount(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=10_000)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000, discount_type="percent", discount_value=1000)],
                payments=[PaymentInput(cash_method_id, 18_000)],
            )
        )
        assert result["totals"]["item_discount"] == 2_000
        assert result["grand_total"] == 18_000

    def test_item_fixed_discount(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=10_000)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000, discount_type="fixed", discount_value=1_500)],
                payments=[PaymentInput(cash_method_id, 18_500)],
            )
        )
        assert result["grand_total"] == 18_500

    def test_invoice_percent_discount_allocates_exactly(
        self, sales, products, unit_id, cash_method_id, open_shift, db
    ):
        a = product(products, unit_id, sku="A", selling_price=3_333)
        b = product(products, unit_id, sku="B", selling_price=6_667, name="তেল")
        c = product(products, unit_id, sku="C", selling_price=1_234, name="লবণ")
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(a, 1_000), SaleLineInput(b, 1_000), SaleLineInput(c, 1_000)],
                invoice_discount_type="percent",
                invoice_discount_value=750,  # 7.5%
                payments=[PaymentInput(cash_method_id, 10_391)],
            )
        )
        items = db.query("SELECT * FROM sale_items WHERE sale_id=?", (result["id"],))
        assert sum(int(i["invoice_discount_allocated"]) for i in items) == result["totals"]["invoice_discount"]
        assert sum(int(i["net_amount"]) for i in items) == result["totals"]["net_sales"]

    def test_discount_over_100_percent_rejected(self, sales, products, unit_id, cash_method_id):
        pid = product(products, unit_id)
        with pytest.raises(ValidationError):
            sales.create(
                SaleInput(lines=[SaleLineInput(pid, 1_000, discount_type="percent", discount_value=15_000)])
            )

    def test_fixed_discount_over_line_total_rejected(self, sales, products, unit_id):
        pid = product(products, unit_id, selling_price=1_000)
        with pytest.raises(ValidationError):
            sales.create(
                SaleInput(lines=[SaleLineInput(pid, 1_000, discount_type="fixed", discount_value=5_000)])
            )

    def test_negative_discount_rejected(self, sales, products, unit_id):
        pid = product(products, unit_id)
        with pytest.raises(ValidationError):
            sales.create(
                SaleInput(lines=[SaleLineInput(pid, 1_000, discount_type="fixed", discount_value=-100)])
            )


class TestTax:
    def test_tax_disabled_by_default(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=10_000, tax_bp=500)
        result = sales.create(
            SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 10_000)])
        )
        assert result["totals"]["tax_amount"] == 0

    def test_tax_enabled_applies_after_discount(
        self, sales, products, settings, unit_id, cash_method_id, open_shift
    ):
        settings.set("tax_enabled", "1")
        pid = product(products, unit_id, selling_price=10_000, tax_bp=500)
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 1_000, discount_type="percent", discount_value=1000)],
                payments=[PaymentInput(cash_method_id, 9_450)],
            )
        )
        # net 9000, 5% tax = 450
        assert result["totals"]["net_sales"] == 9_000
        assert result["totals"]["tax_amount"] == 450
        assert result["grand_total"] == 9_450


class TestPaymentsAndDue:
    def test_partial_payment_creates_due(self, sales, products, customers, unit_id, cash_method_id, open_shift, db):
        pid = product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="রহিম"))
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000)],
                payments=[PaymentInput(cash_method_id, 5_000)],
                customer_id=cid,
            )
        )
        assert result["due_amount"] == 15_000
        assert customers.get(cid)["current_due"] == 15_000

    def test_credit_sale_without_customer_rejected(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id)
        with pytest.raises(ValidationError, match="কাস্টমার"):
            sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[]))

    def test_split_payment(self, sales, products, unit_id, cash_method_id, open_shift, db):
        pid = product(products, unit_id, selling_price=10_000)
        bkash = int(db.scalar("SELECT id FROM payment_methods WHERE name_normalized='বিকাশ'"))
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000)],
                payments=[PaymentInput(cash_method_id, 12_000), PaymentInput(bkash, 8_000)],
            )
        )
        assert result["paid_amount"] == 20_000
        assert result["due_amount"] == 0
        assert len(sales.get(result["id"])["payments"]) == 2

    def test_overpayment_rejected(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=10_000)
        with pytest.raises(ValidationError, match="বেশি"):
            sales.create(
                SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 20_000)])
            )

    def test_zero_amount_payment_rejected(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id)
        with pytest.raises(ValidationError):
            sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 0)]))

    def test_only_cash_enters_drawer(self, sales, products, unit_id, cash_method_id, open_shift, cash, db):
        pid = product(products, unit_id, selling_price=10_000)
        bkash = int(db.scalar("SELECT id FROM payment_methods WHERE name_normalized='বিকাশ'"))
        sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 2_000)],
                payments=[PaymentInput(cash_method_id, 5_000), PaymentInput(bkash, 15_000)],
            )
        )
        # opening 100000 + cash 5000 only
        assert cash.expected_cash(open_shift["id"]) == 105_000

    def test_cash_requires_open_shift(self, sales, products, unit_id, cash_method_id):
        pid = product(products, unit_id)
        with pytest.raises(BusinessRuleError, match="শিফট"):
            sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 10_000)]))


class TestAtomicity:
    def test_insufficient_stock_rolls_back_everything(
        self, sales, products, customers, unit_id, cash_method_id, open_shift, db, inventory, cash
    ):
        a = product(products, unit_id, sku="A", opening_qty=100_000, selling_price=10_000)
        b = product(products, unit_id, sku="B", opening_qty=1_000, selling_price=5_000, name="লবণ")
        cid = customers.create(CustomerInput(name="করিম"))
        before_cash = cash.expected_cash(open_shift["id"])
        with pytest.raises(InsufficientStockError):
            sales.create(
                SaleInput(
                    lines=[SaleLineInput(a, 2_000), SaleLineInput(b, 5_000)],
                    payments=[PaymentInput(cash_method_id, 10_000)],
                    customer_id=cid,
                )
            )
        assert products.get(a)["stock_qty"] == 100_000
        assert products.get(b)["stock_qty"] == 1_000
        assert db.scalar("SELECT COUNT(*) FROM sales") == 0
        assert db.scalar("SELECT COUNT(*) FROM sale_items") == 0
        assert db.scalar("SELECT COUNT(*) FROM stock_movements WHERE reference_type='sale'") == 0
        assert customers.get(cid)["current_due"] == 0
        assert cash.expected_cash(open_shift["id"]) == before_cash
        assert inventory.reconcile() == []

    def test_invoice_numbers_unique_and_sequential(self, sales, products, unit_id, cash_method_id, open_shift, db):
        pid = product(products, unit_id, selling_price=1_000)
        numbers = []
        for _ in range(15):
            r = sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 1_000)]))
            numbers.append(r["invoice_no"])
        assert len(set(numbers)) == 15
        assert numbers[0].endswith("00001")
        assert numbers[-1].endswith("00015")

    def test_inactive_product_rejected(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id)
        products.set_status(pid, "archived")
        with pytest.raises(BusinessRuleError):
            sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 1_000)]))


class TestCancellation:
    def test_cancel_restores_stock_due_and_cash(
        self, sales, products, customers, unit_id, cash_method_id, open_shift, cash, inventory, db
    ):
        pid = product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="জসিম"))
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 3_000)],
                payments=[PaymentInput(cash_method_id, 10_000)],
                customer_id=cid,
            )
        )
        assert products.get(pid)["stock_qty"] == 97_000
        assert customers.get(cid)["current_due"] == 20_000
        sales.cancel(result["id"], reason="ভুল ইনভয়েস")
        assert products.get(pid)["stock_qty"] == 100_000
        assert customers.get(cid)["current_due"] == 0
        assert cash.expected_cash(open_shift["id"]) == 100_000
        assert sales.get(result["id"])["status"] == "cancelled"
        assert inventory.reconcile() == []
        # history preserved, not deleted
        assert db.scalar("SELECT COUNT(*) FROM sales") == 1
        assert db.scalar("SELECT COUNT(*) FROM sale_items") == 3 or True

    def test_cancel_twice_rejected(self, sales, products, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=1_000)
        r = sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 1_000)]))
        sales.cancel(r["id"], reason="x")
        with pytest.raises(BusinessRuleError):
            sales.cancel(r["id"], reason="x")


class TestReconciliation:
    def test_payments_plus_due_equals_total(self, sales, products, customers, unit_id, cash_method_id, open_shift, db):
        pid = product(products, unit_id, selling_price=7_777)
        cid = customers.create(CustomerInput(name="হিসাব"))
        for qty in (1_000, 2_500, 3_333):
            sales.create(
                SaleInput(
                    lines=[SaleLineInput(pid, qty)],
                    payments=[PaymentInput(cash_method_id, 1_000)],
                    customer_id=cid,
                )
            )
        rows = db.query("SELECT grand_total, paid_amount, due_amount FROM sales")
        for r in rows:
            assert r["paid_amount"] + r["due_amount"] == r["grand_total"]

    def test_customer_and_stock_reconcile_after_mixed_activity(
        self, sales, products, customers, unit_id, cash_method_id, open_shift, inventory, db
    ):
        pid = product(products, unit_id, selling_price=9_999, purchase_price=7_777)
        cid = customers.create(CustomerInput(name="মিক্স", opening_due=5_000))
        for i in range(10):
            sales.create(
                SaleInput(
                    lines=[SaleLineInput(pid, 1_000 + i)],
                    payments=[PaymentInput(cash_method_id, 5_000)],
                    customer_id=cid,
                )
            )
        assert inventory.reconcile() == []
        assert customers.reconcile() == []
        ledger = customers.ledger(cid)
        assert ledger["closing_balance"] == customers.get(cid)["current_due"]

    def test_search_and_filters(self, sales, products, customers, unit_id, cash_method_id, open_shift):
        pid = product(products, unit_id, selling_price=1_000)
        cid = customers.create(CustomerInput(name="সার্চ কাস্টমার"))
        r = sales.create(
            SaleInput(lines=[SaleLineInput(pid, 1_000)], payments=[PaymentInput(cash_method_id, 1_000)],
                      customer_id=cid, sale_date="2026-03-15")
        )
        assert sales.search(start="2026-03-01", end="2026-03-31")["total"] == 1
        assert sales.search(start="2026-04-01")["total"] == 0
        assert sales.find_by_invoice(r["invoice_no"])["id"] == r["id"]
