"""Shared pytest fixtures. Test databases are temporary and never touch user data."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retvia.data.db import Database  # noqa: E402
from retvia.services.audit import AuditService  # noqa: E402
from retvia.services.catalog import (  # noqa: E402
    BarcodeService,
    CategoryService,
    ProductService,
    UnitService,
)
from retvia.services.inventory import InventoryService  # noqa: E402
from retvia.services.numbering import NumberingService  # noqa: E402
from retvia.services.settings import SettingsService, seed_defaults  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    seed_defaults(database)
    yield database
    database.close()


@pytest.fixture()
def settings(db):
    return SettingsService(db)


@pytest.fixture()
def audit(db):
    return AuditService(db, actor="tester")


@pytest.fixture()
def numbering(db, settings):
    return NumberingService(db, settings)


@pytest.fixture()
def inventory(db, settings, audit, numbering):
    return InventoryService(db, settings, audit, numbering)


@pytest.fixture()
def products(db, inventory, audit, settings):
    return ProductService(db, inventory, audit, settings)


@pytest.fixture()
def categories(db, audit):
    return CategoryService(db, audit)


@pytest.fixture()
def units(db, audit):
    return UnitService(db, audit)


@pytest.fixture()
def barcodes(db, audit):
    return BarcodeService(db, audit)


@pytest.fixture()
def unit_id(db):
    return int(db.scalar("SELECT id FROM units WHERE name_normalized='পিস'"))


@pytest.fixture()
def kg_unit_id(db):
    return int(db.scalar("SELECT id FROM units WHERE name_normalized='কেজি'"))


@pytest.fixture()
def cash_method_id(db):
    return int(db.scalar("SELECT id FROM payment_methods WHERE is_cash=1"))


@pytest.fixture()
def cash(db, settings, audit):
    from retvia.services.cash import CashService

    return CashService(db, settings, audit)


@pytest.fixture()
def customers(db, audit):
    from retvia.services.parties import CustomerService

    return CustomerService(db, audit)


@pytest.fixture()
def suppliers(db, audit):
    from retvia.services.parties import SupplierService

    return SupplierService(db, audit)


@pytest.fixture()
def sales(db, settings, audit, inventory, numbering, cash):
    from retvia.services.sales import SalesService

    return SalesService(
        db, settings=settings, audit=audit, inventory=inventory, numbering=numbering, cash=cash
    )


@pytest.fixture()
def open_shift(cash):
    return cash.open_session(opening_cash=100_000, actor="tester")


@pytest.fixture()
def purchases(db, settings, audit, inventory, numbering, cash):
    from retvia.services.purchases import PurchaseService

    return PurchaseService(
        db, settings=settings, audit=audit, inventory=inventory, numbering=numbering, cash=cash
    )


@pytest.fixture()
def customer_payments(db, settings, audit, numbering, cash):
    from retvia.services.payments import CustomerPaymentService

    return CustomerPaymentService(db, settings=settings, audit=audit, numbering=numbering, cash=cash)


@pytest.fixture()
def supplier_payments(db, settings, audit, numbering, cash):
    from retvia.services.payments import SupplierPaymentService

    return SupplierPaymentService(db, settings=settings, audit=audit, numbering=numbering, cash=cash)


@pytest.fixture()
def sales_returns(db, settings, audit, inventory, numbering, cash, customer_payments):
    from retvia.services.returns import SalesReturnService

    return SalesReturnService(
        db,
        settings=settings,
        audit=audit,
        inventory=inventory,
        numbering=numbering,
        cash=cash,
        customer_payments=customer_payments,
    )


@pytest.fixture()
def purchase_returns(db, settings, audit, inventory, numbering, cash, supplier_payments):
    from retvia.services.returns import PurchaseReturnService

    return PurchaseReturnService(
        db,
        settings=settings,
        audit=audit,
        inventory=inventory,
        numbering=numbering,
        cash=cash,
        supplier_payments=supplier_payments,
    )


@pytest.fixture()
def expenses(db, settings, audit, numbering, cash):
    from retvia.services.expenses import ExpenseService

    return ExpenseService(db, settings=settings, audit=audit, numbering=numbering, cash=cash)
