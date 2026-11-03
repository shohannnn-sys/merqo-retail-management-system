"""Financial engine and report-registry tests, including cross-report agreement."""

import pytest

from retvia.core.errors import ValidationError
from retvia.services.catalog import ProductInput
from retvia.services.finance import FinanceService, date_range_for
from retvia.services.parties import CustomerInput, SupplierInput
from retvia.services.purchases import PurchaseInput, PurchaseLineInput
from retvia.services.reports import ReportService
from retvia.services.returns import SalesReturnLine
from retvia.services.sales import PaymentInput, SaleInput, SaleLineInput


@pytest.fixture()
def finance(db, settings, inventory):
    return FinanceService(db, settings, inventory)


@pytest.fixture()
def reports(db, settings):
    return ReportService(db, settings)


@pytest.fixture()
def populated(db, products, customers, suppliers, sales, purchases, customer_payments,
              supplier_payments, sales_returns, expenses, unit_id, cash_method_id, open_shift):
    """A realistic month of activity built only from real service calls."""
    pid = products.create(ProductInput(
        name="সয়াবিন তেল", sku="OIL-1", unit_id=unit_id,
        purchase_price=15000, selling_price=18000, opening_qty=100_000,
    ))
    pid2 = products.create(ProductInput(
        name="চিনি", sku="SUG-1", unit_id=unit_id,
        purchase_price=9000, selling_price=11000, opening_qty=100_000,
    ))
    cid = customers.create(CustomerInput(name="আব্দুল করিম", phone="01712345678", opening_due=10000))
    sid = suppliers.create(SupplierInput(name="মেসার্স রহমান ট্রেডার্স", opening_payable=25000))

    purchases.create(PurchaseInput(
        supplier_id=sid, lines=[PurchaseLineInput(pid, 20_000, 15500)],
        payments=[PaymentInput(cash_method_id, 100000)], purchase_date="2026-06-03",
    ))
    r1 = sales.create(SaleInput(
        lines=[SaleLineInput(pid, 5_000), SaleLineInput(pid2, 3_000)], customer_id=cid,
        payments=[PaymentInput(cash_method_id, 50000)], sale_date="2026-06-05",
        invoice_discount_type="percent", invoice_discount_value=500,
    ))
    sales.create(SaleInput(
        lines=[SaleLineInput(pid2, 4_000)], customer_id=cid,
        payments=[PaymentInput(cash_method_id, 44000)], sale_date="2026-06-10",
    ))
    sales.create(SaleInput(
        lines=[SaleLineInput(pid, 2_000)], payments=[PaymentInput(cash_method_id, 36000)],
        sale_date="2026-06-15",
    ))
    customer_payments.collect(customer_id=cid, amount=30000, method_id=cash_method_id,
                              payment_date="2026-06-18")
    supplier_payments.pay(supplier_id=sid, amount=100000, method_id=cash_method_id,
                          payment_date="2026-06-20")
    item = db.query_one("SELECT id FROM sale_items WHERE sale_id=? ORDER BY id LIMIT 1", (r1["id"],))
    sales_returns.create(sale_id=r1["id"], lines=[SalesReturnLine(int(item["id"]), 1_000, "restock")],
                         reason="রিটার্ন", return_date="2026-06-22")
    damaged = db.query_one("SELECT id FROM sale_items WHERE sale_id=? ORDER BY id DESC LIMIT 1", (r1["id"],))
    sales_returns.create(sale_id=r1["id"], lines=[SalesReturnLine(int(damaged["id"]), 1_000, "damaged")],
                         reason="নষ্ট", return_date="2026-06-23")
    cat = int(db.scalar("SELECT id FROM expense_categories LIMIT 1"))
    expenses.create(category_id=cat, amount=150000, method_id=cash_method_id,
                    expense_date="2026-06-25", description="দোকান ভাড়া")
    return {"product": pid, "product2": pid2, "customer": cid, "supplier": sid,
            "start": "2026-06-01", "end": "2026-06-30"}


class TestProfitAndLoss:
    def test_gross_and_net_profit_are_distinct(self, finance, populated):
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert pnl["gross_profit"] != pnl["net_profit"]
        assert pnl["net_profit"] == pnl["gross_profit"] - pnl["operating_expense"] - pnl["total_write_off"]

    def test_net_sales_identity(self, finance, populated):
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert pnl["net_sales"] == pnl["gross_sales"] - pnl["sales_discount"] - pnl["sales_returns"]

    def test_gross_profit_identity(self, finance, populated):
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert pnl["gross_profit"] == pnl["net_sales"] - pnl["cogs"]

    def test_expense_is_included(self, finance, populated):
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert pnl["operating_expense"] == 150000

    def test_write_offs_separated(self, finance, populated):
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert pnl["return_write_off"] > 0
        assert pnl["total_write_off"] == pnl["stock_write_off"] + pnl["return_write_off"]

    def test_empty_range_is_zero(self, finance, populated):
        pnl = finance.profit_and_loss("2020-01-01", "2020-01-31")
        assert pnl["net_sales"] == 0
        assert pnl["gross_profit"] == 0
        assert pnl["net_profit"] == 0

    def test_invalid_range_rejected(self, finance):
        with pytest.raises(ValidationError):
            finance.profit_and_loss("2026-06-30", "2026-06-01")

    def test_cogs_uses_moving_average_not_list_price(self, finance, populated, products, db):
        # A purchase at 155.00 raised MAC above the 150.00 opening cost.
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        row = db.query_one("SELECT SUM(total_cost) AS c FROM sale_items")
        assert pnl["cogs"] <= int(row["c"])
        assert int(products.get(populated["product"])["avg_cost"]) > 15000


class TestDashboard:
    def test_kpis_are_computed_from_data(self, finance, populated):
        dash = finance.dashboard(populated["start"], populated["end"])
        assert dash["kpi"]["sale_count"] == 3
        assert dash["kpi"]["total_expense"] == 150000
        assert dash["kpi"]["stock_value"] > 0
        assert dash["kpi"]["customer_due"] >= 0

    def test_dashboard_matches_profit_report(self, finance, populated):
        dash = finance.dashboard(populated["start"], populated["end"])
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert dash["kpi"]["gross_profit"] == pnl["gross_profit"]
        assert dash["kpi"]["net_profit"] == pnl["net_profit"]
        assert dash["kpi"]["net_sales"] == pnl["net_sales"]

    def test_charts_present_and_populated(self, finance, populated):
        charts = finance.dashboard(populated["start"], populated["end"])["charts"]
        assert len(charts["sales_trend"]) == 3
        assert len(charts["expense_overview"]) >= 1
        assert len(charts["product_performance"]) >= 1
        assert len(charts["payment_overview"]) >= 1

    def test_empty_database_dashboard_is_zero_not_fake(self, finance):
        dash = finance.dashboard("2026-01-01", "2026-01-31")
        assert dash["kpi"]["total_sales"] == 0
        assert dash["kpi"]["net_profit"] == 0
        assert dash["recent_sales"] == []
        assert dash["charts"]["sales_trend"] == []

    def test_date_presets(self):
        from datetime import date

        ref = date(2026, 6, 15)
        assert date_range_for("today", reference=ref) == ("2026-06-15", "2026-06-15")
        assert date_range_for("yesterday", reference=ref) == ("2026-06-14", "2026-06-14")
        assert date_range_for("this_month", reference=ref) == ("2026-06-01", "2026-06-15")
        assert date_range_for("this_year", reference=ref) == ("2026-01-01", "2026-06-15")
        assert date_range_for("this_week", reference=ref) == ("2026-06-15", "2026-06-15")


class TestReconciliation:
    def test_all_ledgers_healthy(self, finance, populated):
        result = finance.reconcile_all()
        assert result["healthy"], result["problems"]
        assert result["foreign_key_violations"] == []

    def test_detects_tampered_stock(self, finance, populated, db):
        db.execute("UPDATE products SET stock_qty = stock_qty + 5000 WHERE id=?",
                   (populated["product"],))
        result = finance.reconcile_all()
        assert not result["healthy"]
        assert "inventory" in result["problems"]

    def test_detects_tampered_customer_due(self, finance, populated, db):
        db.execute("UPDATE customers SET current_due = current_due + 12345 WHERE id=?",
                   (populated["customer"],))
        result = finance.reconcile_all()
        assert not result["healthy"]
        assert "customers" in result["problems"]


class TestReportRegistry:
    def test_thirty_four_reports_registered(self, reports):
        assert len(reports.list_reports()) == 34

    def test_every_report_runs_on_populated_data(self, reports, populated):
        failures = []
        for meta in reports.list_reports():
            filters = {"start": populated["start"], "end": populated["end"]}
            if meta["id"] == "customer_ledger":
                filters["customer_id"] = populated["customer"]
            if meta["id"] == "supplier_ledger":
                filters["supplier_id"] = populated["supplier"]
            try:
                result = reports.run(meta["id"], filters)
                assert result.title
                assert result.columns
            except Exception as exc:  # noqa: BLE001
                failures.append((meta["id"], repr(exc)))
        assert not failures, failures

    def test_every_report_runs_on_empty_database(self, reports):
        failures = []
        for meta in reports.list_reports():
            if meta["id"] in ("customer_ledger", "supplier_ledger"):
                continue
            try:
                result = reports.run(meta["id"], {"start": "2026-01-01", "end": "2026-12-31"})
                assert isinstance(result.rows, list)
            except Exception as exc:  # noqa: BLE001
                failures.append((meta["id"], repr(exc)))
        assert not failures, failures

    def test_sales_report_totals_match_finance(self, reports, finance, populated):
        result = reports.run("daily_sales", {"start": populated["start"], "end": populated["end"]})
        pnl = finance.profit_and_loss(populated["start"], populated["end"])
        assert result.totals["gross_sales"] == pnl["gross_sales"]
        assert result.totals["discount"] == pnl["sales_discount"]

    def test_detail_and_period_reports_agree(self, reports, populated):
        period = reports.run("daily_sales", {"start": populated["start"], "end": populated["end"]})
        detail = reports.run("custom_sales", {"start": populated["start"], "end": populated["end"]})
        assert period.totals["net_total"] == detail.totals["net_total"]
        assert period.totals["due"] == detail.totals["due"]

    def test_expense_report_total(self, reports, populated):
        result = reports.run("expense", {"start": populated["start"], "end": populated["end"]})
        assert result.totals["amount"] == 150000

    def test_low_and_out_of_stock_reports(self, reports, products, unit_id, populated):
        products.create(ProductInput(name="শেষ পণ্য", sku="OUT-1", unit_id=unit_id,
                                     opening_qty=0, min_stock_qty=5000))
        out = reports.run("out_of_stock", {})
        assert any(r["sku"] == "OUT-1" for r in out.rows)

    def test_ledger_requires_party(self, reports, populated):
        with pytest.raises(ValidationError):
            reports.run("customer_ledger", {"start": populated["start"], "end": populated["end"]})

    def test_unknown_report_rejected(self, reports):
        from retvia.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            reports.run("does_not_exist", {})

    def test_customer_due_report_only_debtors(self, reports, customers, populated):
        customers.create(CustomerInput(name="নগদ ক্রেতা"))
        result = reports.run("customer_due", {})
        assert all(r["current_due"] > 0 for r in result.rows)

    def test_transaction_history_covers_all_types(self, reports, populated):
        result = reports.run("transaction_history",
                             {"start": populated["start"], "end": populated["end"]})
        kinds = {r["txn_type"] for r in result.rows}
        assert {"sale", "purchase", "customer_payment", "supplier_payment",
                "sales_return", "expense"} <= kinds

    def test_bangla_text_survives_report_roundtrip(self, reports, populated):
        result = reports.run("custom_sales", {"start": populated["start"], "end": populated["end"]})
        assert any("আব্দুল করিম" == r["customer"] for r in result.rows)
