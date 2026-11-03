"""End-to-end integration through ServiceContainer — the exact graph the UI uses.

These tests prove the wiring, not just the individual services: every call the
screens make is exercised against a real on-disk database.
"""

from __future__ import annotations

import pytest

from retvia.core.errors import BusinessRuleError, ValidationError
from retvia.services.catalog import ProductInput
from retvia.services.container import ServiceContainer, user_data_dir
from retvia.services.parties import CustomerInput, SupplierInput
from retvia.services.purchases import PurchaseInput, PurchaseLineInput
from retvia.services.returns import PurchaseReturnLine, SalesReturnLine
from retvia.services.sales import PaymentInput, SaleInput, SaleLineInput
from retvia.services.settings import BusinessProfile


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RETVIA_LICENSE_PUBLIC_KEY", "")
    container = ServiceContainer(tmp_path / "data")
    container.profile.update(
        BusinessProfile(
            name="রহমান স্টোর",
            address="টাঙ্গাইল সদর",
            phone="01711111111",
            receipt_footer="ধন্যবাদ, আবার আসবেন",
            tagline="বিশ্বস্ত সেবা",
        )
    )
    container.users.ensure_owner(username="admin", password="password1", display_name="মালিক")
    container.login("admin", "password1")
    yield container
    container.close()


def _product(app, name="চাল মিনিকেট", sku="RICE-001", price=7500, cost=6000, precision=3):
    unit = next(u for u in app.units.list() if u["name"] == "কেজি")
    return app.products.create(
        ProductInput(
            name=name,
            sku=sku,
            unit_id=unit["id"],
            purchase_price=cost,
            selling_price=price,
            opening_qty=100_000,
            min_stock_qty=10_000,
        )
    )


class TestBootstrap:
    def test_data_directories_created(self, app):
        for folder in ("data", "backups", "logs", "assets/business"):
            assert (app.data_dir / folder).is_dir()

    def test_database_migrated_to_latest(self, app):
        assert app.db.schema_version == 3
        assert "users" in app.db.table_counts()
        assert "customer_payment_allocations" in app.db.table_counts()

    def test_defaults_seeded_without_demo_data(self, app):
        assert len(app.units.list()) >= 9
        assert len(app.payment_methods.list()) >= 6
        assert app.products.count() == 0, "no demo products"
        assert app.customers.search()["total"] == 0, "no demo customers"
        assert app.sales.search()["total"] == 0, "no demo sales"

    def test_user_data_dir_honours_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RETVIA_DATA_DIR", str(tmp_path / "custom"))
        assert user_data_dir() == tmp_path / "custom"

    def test_health_reports_ten_checks(self, app):
        health = app.health()
        assert len(health["checks"]) == 10
        assert health["healthy"] is True


class TestSession:
    def test_login_sets_actor_for_audit(self, app):
        assert app.current_user["username"] == "admin"
        _product(app)
        rows = app.audit.recent(limit=5)
        assert rows[0]["actor"] == "মালিক"

    def test_permissions_follow_role(self, app):
        assert app.can("pos.sell")
        assert app.can("user.manage")
        app.current_user = {**app.current_user, "role": "cashier"}
        assert app.can("pos.sell")
        assert not app.can("user.manage")

    def test_logout_clears_session(self, app):
        app.logout()
        assert app.current_user is None
        assert app.can("pos.sell") is False


class TestBusinessCycle:
    def test_full_cycle_reconciles(self, app):
        product_id = _product(app)
        customer_id = app.customers.create(CustomerInput(name="করিম মিয়া", phone="01811111111"))
        supplier_id = app.suppliers.create(SupplierInput(name="আড়তদার ভাই", phone="01911111111"))
        cash_method = next(m["id"] for m in app.payment_methods.list() if m["is_cash"])
        bkash = next(m["id"] for m in app.payment_methods.list() if m["name"] == "বিকাশ")
        app.cash.open_session(opening_cash=500_000)

        # purchase increases stock
        purchase = app.purchases.create(
            PurchaseInput(
                supplier_id=supplier_id,
                lines=[PurchaseLineInput(product_id, 50_000, 6200)],
                payments=[PaymentInput(cash_method, 200_000)],
            )
        )
        assert purchase["due_amount"] > 0

        # split-payment sale
        sale = app.sales.create(
            SaleInput(
                lines=[SaleLineInput(product_id, 5_000, 7500)],
                payments=[PaymentInput(cash_method, 20_000), PaymentInput(bkash, 10_000)],
                customer_id=customer_id,
            )
        )
        assert sale["grand_total"] == 37_500
        assert sale["due_amount"] == 7_500

        # collect part of the due
        receipt = app.customer_payments.collect(
            customer_id=customer_id,
            amount=2_500,
            method_id=cash_method,
            sale_id=sale["id"],
        )
        assert receipt["amount"] == 2_500
        assert app.customer_payments.invoice_outstanding(sale["id"]) == 5_000

        # pay the supplier
        app.supplier_payments.pay(
            supplier_id=supplier_id,
            amount=50_000,
            method_id=cash_method,
            purchase_id=purchase["id"],
        )

        # sales return restocks and adjusts the due
        item = app.sales_returns.returnable_items(sale["id"])[0]
        sreturn = app.sales_returns.create(
            sale_id=sale["id"],
            lines=[SalesReturnLine(item["id"], 1_000, "restock", "পছন্দ হয়নি")],
            reason="পছন্দ হয়নি",
        )
        assert sreturn["total_amount"] > 0

        # purchase return
        pitem = app.purchase_returns.returnable_items(purchase["id"])[0]
        app.purchase_returns.create(
            purchase_id=purchase["id"],
            lines=[PurchaseReturnLine(pitem["id"], 2_000, "মান খারাপ")],
            reason="মান খারাপ",
        )

        # expense and stock adjustment
        category = app.expenses.categories()[0]["id"]
        app.expenses.create(category_id=category, amount=50_00, method_id=cash_method, description="দোকান ভাড়া")
        app.inventory.adjust(
            product_id=product_id,
            adjustment_type="damage",
            quantity=500,
            reason="নষ্ট হয়েছে",
            adjustment_date="2026-01-15",
        )

        # close the shift
        session = app.cash.current_session()
        expected = app.cash.expected_cash(session["id"])
        closed = app.cash.close_session(session_id=session["id"], actual_cash=expected)
        assert closed["difference"] == 0

        assert app.finance.reconcile_all()["healthy"] is True
        assert app.inventory.reconcile() == []

    def test_sale_cancellation_reverses_stock_and_due(self, app):
        product_id = _product(app)
        customer_id = app.customers.create(CustomerInput(name="করিম"))
        cash_method = next(m["id"] for m in app.payment_methods.list() if m["is_cash"])
        app.cash.open_session(opening_cash=0)
        before = app.products.get(product_id)["stock_qty"]
        sale = app.sales.create(
            SaleInput(
                lines=[SaleLineInput(product_id, 3_000, 7500)],
                payments=[PaymentInput(cash_method, 100_00)],
                customer_id=customer_id,
            )
        )
        app.sales.cancel(sale["id"], reason="ভুল ইনভয়েস")
        assert app.products.get(product_id)["stock_qty"] == before
        assert app.customers.get(customer_id)["current_due"] == 0
        assert app.finance.reconcile_all()["healthy"] is True

    def test_credit_sale_requires_customer(self, app):
        product_id = _product(app)
        with pytest.raises((BusinessRuleError, ValidationError)):
            app.sales.create(SaleInput(lines=[SaleLineInput(product_id, 1_000, 7500)], payments=[]))

    def test_transaction_register_and_audit_grow(self, app):
        product_id = _product(app)
        cash_method = next(m["id"] for m in app.payment_methods.list() if m["is_cash"])
        app.cash.open_session(opening_cash=0)
        app.sales.create(
            SaleInput(
                lines=[SaleLineInput(product_id, 1_000, 7500)],
                payments=[PaymentInput(cash_method, 75_00)],
            )
        )
        register = app.finance.transactions()
        assert register["total"] >= 1
        assert register["rows"][0]["txn_type"] == "sale"
        assert len(app.audit.search(entity_type="sale")) >= 1


class TestReportsAndExport:
    def test_all_34_reports_run_through_container(self, app):
        _product(app)
        customer_id = app.customers.create(CustomerInput(name="করিম"))
        supplier_id = app.suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        definitions = app.reports.list_reports()
        assert len(definitions) == 34
        for meta in definitions:
            definition = app.reports.definition(meta["id"])
            filters = {}
            if definition.requires_party == "customer":
                filters["customer_id"] = customer_id
            elif definition.requires_party == "supplier":
                filters["supplier_id"] = supplier_id
            result = app.reports.run(meta["id"], filters)
            assert result.id == meta["id"]
            assert isinstance(result.rows, list)

    def test_party_metadata_exposed_for_ui(self, app):
        assert app.reports.definition("customer_ledger").requires_party == "customer"
        assert app.reports.definition("supplier_ledger").requires_party == "supplier"
        assert app.reports.definition("stock").requires_party == ""

    def test_csv_and_xlsx_export_every_report(self, app, tmp_path):
        _product(app)
        customer_id = app.customers.create(CustomerInput(name="করিম"))
        supplier_id = app.suppliers.create(SupplierInput(name="সাপ্লায়ার"))
        out = tmp_path / "exports"
        for meta in app.reports.list_reports():
            definition = app.reports.definition(meta["id"])
            filters = {}
            if definition.requires_party == "customer":
                filters["customer_id"] = customer_id
            elif definition.requires_party == "supplier":
                filters["supplier_id"] = supplier_id
            result = app.reports.run(meta["id"], filters)
            csv_path = app.exporting.export(result, out / f"{meta['id']}.csv", "csv")
            xlsx_path = app.exporting.export(result, out / f"{meta['id']}.xlsx", "xlsx")
            assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
            assert xlsx_path.stat().st_size > 0


class TestBackupThroughContainer:
    def test_create_validate_restore_cycle(self, app, tmp_path):
        product_id = _product(app)
        created = app.backup.create()
        report = app.backup.validate(created["path"])
        assert report["schema_version"] == 3
        # mutate, then restore
        app.products.set_status(product_id, "archived")
        assert app.products.get(product_id)["status"] == "archived"
        app.backup.restore(created["path"], confirmed=True)
        assert app.products.get(product_id)["status"] == "active"
        assert app.db.integrity_check()[0] is True
        assert len(app.backup.list_files()) >= 2, "a pre-restore safety backup is kept"

    def test_auto_backup_respects_interval(self, app):
        app.settings.update({"backup_auto_enabled": "1", "backup_interval_minutes": "5"})
        first = app.maybe_auto_backup()
        assert first is not None
        app.settings.update({"backup_auto_enabled": "0"})
        assert app.maybe_auto_backup() is None


class TestProfile:
    def test_extended_profile_fields_persist(self, app):
        profile = app.profile.get()
        assert profile.name == "রহমান স্টোর"
        assert profile.tagline == "বিশ্বস্ত সেবা"
        app.profile.update(
            BusinessProfile(
                name="নতুন নাম",
                website="retvia.example",
                receipt_header="স্বাগতম",
            )
        )
        again = app.profile.get()
        assert again.name == "নতুন নাম"
        assert again.website == "retvia.example"
        assert again.receipt_header == "স্বাগতম"

    def test_profile_survives_reopen(self, app):
        app.db.reopen()
        assert app.profile.get().name == "রহমান স্টোর"
