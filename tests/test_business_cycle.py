"""Purchase, payment, return and expense tests plus cross-ledger reconciliation."""

import pytest

from retvia.core.errors import BusinessRuleError, ValidationError
from retvia.services.catalog import ProductInput
from retvia.services.parties import CustomerInput, SupplierInput
from retvia.services.purchases import PurchaseInput, PurchaseLineInput
from retvia.services.returns import PurchaseReturnLine, SalesReturnLine
from retvia.services.sales import PaymentInput, SaleInput, SaleLineInput


def make_product(products, unit_id, **kw):
    return products.create(
        ProductInput(
            name=kw.pop("name", "চিনি"),
            sku=kw.pop("sku", "P1"),
            unit_id=unit_id,
            purchase_price=kw.pop("purchase_price", 8000),
            selling_price=kw.pop("selling_price", 10000),
            opening_qty=kw.pop("opening_qty", 100_000),
            **kw,
        )
    )


class TestPurchases:
    def test_purchase_increases_stock_and_recomputes_mac(
        self, purchases, products, suppliers, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, opening_qty=10_000, purchase_price=8000)
        sid = suppliers.create(SupplierInput(name="মেসার্স ভাই ভাই"))
        result = purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 10_000, 10_000)],
                payments=[PaymentInput(cash_method_id, 50_000)],
            )
        )
        p = products.get(pid)
        assert p["stock_qty"] == 20_000
        assert p["avg_cost"] == 9000
        assert result["grand_total"] == 100_000
        assert result["due_amount"] == 50_000
        assert suppliers.get(sid)["current_payable"] == 50_000

    def test_purchase_discount_lowers_effective_cost(
        self, purchases, products, suppliers, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, opening_qty=0, purchase_price=0)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        result = purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 10_000, 10_000, discount_amount=10_000)],
                payments=[PaymentInput(cash_method_id, 90_000)],
            )
        )
        assert result["grand_total"] == 90_000
        assert products.get(pid)["avg_cost"] == 9000

    def test_purchase_cash_leaves_drawer(
        self, purchases, products, suppliers, unit_id, cash_method_id, open_shift, cash
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 1_000, 5_000)],
                payments=[PaymentInput(cash_method_id, 5_000)],
            )
        )
        assert cash.expected_cash(open_shift["id"]) == 95_000

    def test_overpayment_rejected(self, purchases, products, suppliers, unit_id, cash_method_id, open_shift):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        with pytest.raises(ValidationError):
            purchases.create(
                PurchaseInput(
                    supplier_id=sid,
                    lines=[PurchaseLineInput(pid, 1_000, 5_000)],
                    payments=[PaymentInput(cash_method_id, 50_000)],
                )
            )

    def test_purchase_cancel_restores_stock_and_payable(
        self, purchases, products, suppliers, unit_id, cash_method_id, open_shift, inventory
    ):
        pid = make_product(products, unit_id, opening_qty=10_000)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        r = purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 5_000, 9_000)],
                payments=[PaymentInput(cash_method_id, 10_000)],
            )
        )
        purchases.cancel(r["id"], reason="ভুল এন্ট্রি")
        assert products.get(pid)["stock_qty"] == 10_000
        assert suppliers.get(sid)["current_payable"] == 0
        assert inventory.reconcile() == []


class TestSupplierPayments:
    def test_partial_then_full_payment(
        self, purchases, supplier_payments, products, suppliers, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার", opening_payable=10_000))
        purchases.create(PurchaseInput(supplier_id=sid, lines=[PurchaseLineInput(pid, 10_000, 10_000)]))
        assert suppliers.get(sid)["current_payable"] == 110_000
        supplier_payments.pay(supplier_id=sid, amount=40_000, method_id=cash_method_id)
        assert suppliers.get(sid)["current_payable"] == 70_000
        supplier_payments.pay(supplier_id=sid, amount=70_000, method_id=cash_method_id)
        assert suppliers.get(sid)["current_payable"] == 0
        assert suppliers.reconcile() == []

    def test_allocation_to_purchase(
        self, purchases, supplier_payments, products, suppliers, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        r = purchases.create(PurchaseInput(supplier_id=sid, lines=[PurchaseLineInput(pid, 10_000, 10_000)]))
        assert supplier_payments.purchase_outstanding(r["id"]) == 100_000
        supplier_payments.pay(supplier_id=sid, amount=30_000, method_id=cash_method_id, purchase_id=r["id"])
        assert supplier_payments.purchase_outstanding(r["id"]) == 70_000
        assert suppliers.get(sid)["current_payable"] == 70_000
        assert suppliers.reconcile() == []

    def test_supplier_ledger_balance_matches(
        self, purchases, supplier_payments, products, suppliers, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="লেজার সাপ্লায়ার", opening_payable=5_000))
        purchases.create(PurchaseInput(supplier_id=sid, lines=[PurchaseLineInput(pid, 5_000, 10_000)]))
        supplier_payments.pay(supplier_id=sid, amount=20_000, method_id=cash_method_id)
        ledger = suppliers.ledger(sid)
        assert ledger["closing_balance"] == suppliers.get(sid)["current_payable"]


class TestCustomerCollections:
    def test_partial_and_full_collection(
        self, sales, products, customers, customer_payments, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="রহিম", opening_due=20_000))
        sales.create(SaleInput(lines=[SaleLineInput(pid, 3_000)], customer_id=cid))
        assert customers.get(cid)["current_due"] == 50_000
        customer_payments.collect(customer_id=cid, amount=20_000, method_id=cash_method_id)
        assert customers.get(cid)["current_due"] == 30_000
        customer_payments.collect(customer_id=cid, amount=30_000, method_id=cash_method_id)
        assert customers.get(cid)["current_due"] == 0
        assert customers.reconcile() == []

    def test_advance_payment_creates_negative_due(
        self, customers, customer_payments, unit_id, cash_method_id, open_shift
    ):
        cid = customers.create(CustomerInput(name="অ্যাডভান্স"))
        result = customer_payments.collect(customer_id=cid, amount=50_000, method_id=cash_method_id)
        assert result["current_due"] == -50_000
        assert result["advance"] == 50_000
        assert customers.reconcile() == []

    def test_invoice_allocation(
        self, sales, products, customers, customer_payments, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="বাকি কাস্টমার"))
        r = sales.create(SaleInput(lines=[SaleLineInput(pid, 2_000)], customer_id=cid))
        assert customer_payments.invoice_outstanding(r["id"]) == 20_000
        customer_payments.collect(customer_id=cid, amount=8_000, method_id=cash_method_id, sale_id=r["id"])
        assert customer_payments.invoice_outstanding(r["id"]) == 12_000
        assert customers.get(cid)["current_due"] == 12_000
        assert customers.reconcile() == []
        assert len(customer_payments.due_invoices(cid)) == 1

    def test_collection_enters_cash_drawer(
        self, customers, customer_payments, cash, open_shift, cash_method_id
    ):
        cid = customers.create(CustomerInput(name="ক্যাশ কাস্টমার", opening_due=10_000))
        customer_payments.collect(customer_id=cid, amount=10_000, method_id=cash_method_id)
        assert cash.expected_cash(open_shift["id"]) == 110_000

    def test_wrong_invoice_customer_rejected(
        self, sales, products, customers, customer_payments, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        c1 = customers.create(CustomerInput(name="এক"))
        c2 = customers.create(CustomerInput(name="দুই"))
        r = sales.create(SaleInput(lines=[SaleLineInput(pid, 1_000)], customer_id=c1))
        with pytest.raises(ValidationError):
            customer_payments.collect(customer_id=c2, amount=1_000, method_id=cash_method_id, sale_id=r["id"])

    def test_ledger_running_balance(
        self, sales, products, customers, customer_payments, unit_id, cash_method_id, open_shift
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="লেজার", opening_due=15_000))
        sales.create(SaleInput(lines=[SaleLineInput(pid, 2_000)], customer_id=cid))
        customer_payments.collect(customer_id=cid, amount=10_000, method_id=cash_method_id)
        ledger = customers.ledger(cid)
        assert ledger["closing_balance"] == customers.get(cid)["current_due"]
        assert ledger["entries"][0]["particulars"] == "ওপেনিং ব্যালেন্স"
        assert ledger["entries"][-1]["balance"] == ledger["closing_balance"]


class TestSalesReturns:
    def _sale(self, sales, products, customers, unit_id, cash_method_id, qty=5_000, paid=None):
        pid = make_product(products, unit_id, selling_price=10_000, purchase_price=8000)
        cid = customers.create(CustomerInput(name="রিটার্ন কাস্টমার"))
        result = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, qty)],
                customer_id=cid,
                payments=[PaymentInput(cash_method_id, paid if paid is not None else qty * 10)],
            )
        )
        return pid, cid, result

    def test_restock_return_restores_stock_and_reverses_cogs(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, inventory, db
    ):
        pid, cid, r = self._sale(sales, products, customers, unit_id, cash_method_id)
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        before_stock = products.get(pid)["stock_qty"]
        result = sales_returns.create(
            sale_id=r["id"],
            lines=[SalesReturnLine(int(item["id"]), 2_000, "restock")],
            reason="পছন্দ হয়নি",
            refund_amount=20_000,
            refund_method_id=cash_method_id,
        )
        assert result["total_amount"] == 20_000
        assert result["cost_reversed"] == 16_000
        assert products.get(pid)["stock_qty"] == before_stock + 2_000
        assert inventory.reconcile() == []

    def test_damaged_return_does_not_restock(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, inventory, db
    ):
        pid, cid, r = self._sale(sales, products, customers, unit_id, cash_method_id)
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        before = products.get(pid)["stock_qty"]
        result = sales_returns.create(
            sale_id=r["id"],
            lines=[SalesReturnLine(int(item["id"]), 1_000, "damaged")],
            reason="নষ্ট পণ্য",
            refund_amount=10_000,
            refund_method_id=cash_method_id,
        )
        assert products.get(pid)["stock_qty"] == before
        assert result["write_off_cost"] == 8_000
        assert result["cost_reversed"] == 0
        assert inventory.reconcile() == []

    def test_return_reduces_due_first(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, db
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        cid = customers.create(CustomerInput(name="বাকি রিটার্ন"))
        r = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 5_000)],
                customer_id=cid,
                payments=[PaymentInput(cash_method_id, 10_000)],
            )
        )
        assert customers.get(cid)["current_due"] == 40_000
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        result = sales_returns.create(
            sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 2_000)], reason="রিটার্ন"
        )
        assert result["due_adjusted"] == 20_000
        assert result["refund_amount"] == 0
        assert customers.get(cid)["current_due"] == 20_000
        assert customers.reconcile() == []

    def test_cumulative_return_limit(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, db
    ):
        pid, cid, r = self._sale(sales, products, customers, unit_id, cash_method_id, qty=5_000)
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        sales_returns.create(sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 3_000)], reason="প্রথম")
        with pytest.raises(ValidationError, match="সর্বোচ্চ"):
            sales_returns.create(
                sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 3_000)], reason="দ্বিতীয়"
            )
        result = sales_returns.create(
            sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 2_000)], reason="শেষ"
        )
        assert result["total_amount"] == 20_000
        assert sales.get(r["id"])["status"] == "returned"

    def test_partial_return_marks_status(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, db
    ):
        pid, cid, r = self._sale(sales, products, customers, unit_id, cash_method_id)
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        sales_returns.create(sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 1_000)], reason="আংশিক")
        assert sales.get(r["id"])["status"] == "partially_returned"

    def test_full_return_amount_is_exact(
        self, sales, products, customers, sales_returns, unit_id, cash_method_id, open_shift, db
    ):
        pid = make_product(products, unit_id, selling_price=3_333)
        cid = customers.create(CustomerInput(name="ভগ্নাংশ"))
        r = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 3_000)],
                customer_id=cid,
                payments=[PaymentInput(cash_method_id, 9_999)],
            )
        )
        item = db.query_one("SELECT id, net_amount FROM sale_items WHERE sale_id=?", (r["id"],))
        first = sales_returns.create(
            sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 1_000)], reason="a"
        )
        second = sales_returns.create(
            sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 2_000)], reason="b"
        )
        assert first["total_amount"] + second["total_amount"] == int(item["net_amount"])

    def test_return_without_customer_requires_full_refund(
        self, sales, products, sales_returns, unit_id, cash_method_id, open_shift, db
    ):
        pid = make_product(products, unit_id, selling_price=10_000)
        r = sales.create(
            SaleInput(lines=[SaleLineInput(pid, 2_000)], payments=[PaymentInput(cash_method_id, 20_000)])
        )
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r["id"],))
        with pytest.raises(ValidationError, match="অ্যাডভান্স"):
            sales_returns.create(sale_id=r["id"], lines=[SalesReturnLine(int(item["id"]), 1_000)], reason="x")


class TestPurchaseReturns:
    def test_return_reduces_stock_and_payable(
        self,
        purchases,
        purchase_returns,
        products,
        suppliers,
        unit_id,
        cash_method_id,
        open_shift,
        inventory,
        db,
    ):
        pid = make_product(products, unit_id, opening_qty=0, purchase_price=0)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        r = purchases.create(PurchaseInput(supplier_id=sid, lines=[PurchaseLineInput(pid, 10_000, 9_000)]))
        assert products.get(pid)["stock_qty"] == 10_000
        item = db.query_one("SELECT id FROM purchase_items WHERE purchase_id=?", (r["id"],))
        result = purchase_returns.create(
            purchase_id=r["id"], lines=[PurchaseReturnLine(int(item["id"]), 4_000)], reason="ত্রুটিপূর্ণ"
        )
        assert result["total_amount"] == 36_000
        assert products.get(pid)["stock_qty"] == 6_000
        assert suppliers.get(sid)["current_payable"] == 54_000
        assert inventory.reconcile() == []
        assert suppliers.reconcile() == []

    def test_return_quantity_cannot_exceed_purchased(
        self, purchases, purchase_returns, products, suppliers, unit_id, open_shift, db
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        r = purchases.create(PurchaseInput(supplier_id=sid, lines=[PurchaseLineInput(pid, 5_000, 9_000)]))
        item = db.query_one("SELECT id FROM purchase_items WHERE purchase_id=?", (r["id"],))
        with pytest.raises(ValidationError, match="সর্বোচ্চ"):
            purchase_returns.create(
                purchase_id=r["id"], lines=[PurchaseReturnLine(int(item["id"]), 6_000)], reason="x"
            )

    def test_cash_refund_increases_drawer(
        self, purchases, purchase_returns, products, suppliers, unit_id, cash_method_id, open_shift, cash, db
    ):
        pid = make_product(products, unit_id)
        sid = suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        r = purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 5_000, 9_000)],
                payments=[PaymentInput(cash_method_id, 45_000)],
            )
        )
        before = cash.expected_cash(open_shift["id"])
        item = db.query_one("SELECT id FROM purchase_items WHERE purchase_id=?", (r["id"],))
        purchase_returns.create(
            purchase_id=r["id"],
            lines=[PurchaseReturnLine(int(item["id"]), 2_000)],
            reason="ফেরত",
            refund_amount=18_000,
            refund_method_id=cash_method_id,
        )
        assert cash.expected_cash(open_shift["id"]) == before + 18_000


class TestExpenses:
    def test_expense_reduces_cash(self, expenses, cash, open_shift, cash_method_id, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        expenses.create(category_id=cat, amount=15_000, method_id=cash_method_id, description="দোকান ভাড়া")
        assert cash.expected_cash(open_shift["id"]) == 85_000

    def test_non_cash_expense_does_not_touch_drawer(self, expenses, cash, open_shift, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        bkash = int(db.scalar("SELECT id FROM payment_methods WHERE name_normalized='বিকাশ'"))
        expenses.create(category_id=cat, amount=15_000, method_id=bkash)
        assert cash.expected_cash(open_shift["id"]) == 100_000

    def test_zero_amount_rejected(self, expenses, cash_method_id, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        with pytest.raises(ValidationError):
            expenses.create(category_id=cat, amount=0, method_id=cash_method_id)

    def test_category_totals(self, expenses, cash_method_id, open_shift, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        expenses.create(category_id=cat, amount=10_000, method_id=cash_method_id, expense_date="2026-05-10")
        expenses.create(category_id=cat, amount=5_000, method_id=cash_method_id, expense_date="2026-05-20")
        assert expenses.total("2026-05-01", "2026-05-31") == 15_000
        assert expenses.by_category("2026-05-01", "2026-05-31")[0]["total"] == 15_000

    def test_delete_reverses_cash(self, expenses, cash, open_shift, cash_method_id, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        r = expenses.create(category_id=cat, amount=10_000, method_id=cash_method_id)
        expenses.delete(r["id"], reason="ভুল")
        assert cash.expected_cash(open_shift["id"]) == 100_000

    def test_category_in_use_cannot_be_deleted(self, expenses, cash_method_id, open_shift, db):
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        expenses.create(category_id=cat, amount=1_000, method_id=cash_method_id)
        with pytest.raises(BusinessRuleError):
            expenses.delete_category(cat)


class TestCashSessions:
    def test_open_close_with_difference(self, cash, open_shift):
        closed = cash.close_session(session_id=open_shift["id"], actual_cash=99_000)
        assert closed["expected_cash"] == 100_000
        assert closed["difference"] == -1_000
        assert closed["status"] == "closed"

    def test_cannot_double_open(self, cash, open_shift):
        with pytest.raises(BusinessRuleError):
            cash.open_session(opening_cash=1_000)

    def test_cannot_close_twice(self, cash, open_shift):
        cash.close_session(session_id=open_shift["id"], actual_cash=100_000)
        with pytest.raises(BusinessRuleError):
            cash.close_session(session_id=open_shift["id"], actual_cash=100_000)

    def test_manual_cash_in_out(self, cash, open_shift):
        cash.manual_movement(movement_type="cash_in", amount=5_000, reason="খুচরা যোগ")
        cash.manual_movement(movement_type="cash_out", amount=2_000, reason="ব্যাংকে জমা")
        assert cash.expected_cash(open_shift["id"]) == 103_000

    def test_closed_session_rejects_movement(self, cash, open_shift):
        cash.close_session(session_id=open_shift["id"], actual_cash=100_000)
        with pytest.raises(BusinessRuleError):
            cash.manual_movement(movement_type="cash_in", amount=1_000, reason="x")


class TestFullReconciliation:
    def test_mixed_business_day_reconciles_every_ledger(
        self,
        db,
        products,
        customers,
        suppliers,
        sales,
        purchases,
        customer_payments,
        supplier_payments,
        sales_returns,
        purchase_returns,
        expenses,
        inventory,
        cash,
        unit_id,
        cash_method_id,
        open_shift,
    ):
        pid = make_product(products, unit_id, opening_qty=50_000, purchase_price=8000, selling_price=12000)
        cid = customers.create(CustomerInput(name="দৈনিক কাস্টমার", opening_due=10_000))
        sid = suppliers.create(SupplierInput(name="দৈনিক সাপ্লায়ার", opening_payable=20_000))

        purchases.create(
            PurchaseInput(
                supplier_id=sid,
                lines=[PurchaseLineInput(pid, 20_000, 8500)],
                payments=[PaymentInput(cash_method_id, 50_000)],
            )
        )
        r1 = sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 5_000)],
                customer_id=cid,
                payments=[PaymentInput(cash_method_id, 30_000)],
            )
        )
        sales.create(
            SaleInput(
                lines=[SaleLineInput(pid, 3_000)],
                customer_id=cid,
                payments=[PaymentInput(cash_method_id, 36_000)],
            )
        )
        customer_payments.collect(customer_id=cid, amount=15_000, method_id=cash_method_id)
        supplier_payments.pay(supplier_id=sid, amount=30_000, method_id=cash_method_id)
        item = db.query_one("SELECT id FROM sale_items WHERE sale_id=?", (r1["id"],))
        sales_returns.create(
            sale_id=r1["id"], lines=[SalesReturnLine(int(item["id"]), 1_000, "restock")], reason="রিটার্ন"
        )
        cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
        expenses.create(category_id=cat, amount=12_000, method_id=cash_method_id)

        assert inventory.reconcile() == []
        assert customers.reconcile() == []
        assert suppliers.reconcile() == []
        assert customers.ledger(cid)["closing_balance"] == customers.get(cid)["current_due"]
        assert suppliers.ledger(sid)["closing_balance"] == suppliers.get(sid)["current_payable"]
        ok, messages = db.integrity_check()
        assert ok, messages
        assert db.foreign_key_check() == []
        # every stock movement is internally consistent
        bad = db.scalar("SELECT COUNT(*) FROM stock_movements WHERE qty_before + qty_delta <> qty_after")
        assert bad == 0
        # cash drawer equals opening plus all non-opening movements
        movements = db.scalar(
            "SELECT COALESCE(SUM(amount),0) FROM cash_movements WHERE session_id=? AND movement_type<>'opening'",
            (open_shift["id"],),
        )
        assert cash.expected_cash(open_shift["id"]) == 100_000 + movements
