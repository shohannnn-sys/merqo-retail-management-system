"""Service container: one place that wires the object graph.

The UI receives this container and calls services; it never constructs SQL or
performs financial arithmetic itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .. import APP_USER_DIR_NAME
from ..data.db import Database
from .audit import AuditService
from .backup import BackupService
from .cash import CashService
from .catalog import BarcodeService, CategoryService, ProductService, UnitService
from .expenses import ExpenseService
from .exporting import ExportService
from .finance import FinanceService
from .inventory import InventoryService
from .licensing import ActivationService
from .numbering import NumberingService
from .parties import CustomerService, PaymentMethodService, SupplierService
from .payments import CustomerPaymentService, SupplierPaymentService
from .purchases import PurchaseService
from .reports import ReportService
from .returns import PurchaseReturnService, SalesReturnService
from .sales import SalesService
from .settings import BusinessProfileService, SettingsService, seed_defaults
from .users import PERMISSIONS, UserService


def user_data_dir() -> Path:
    """Per-user writable data directory, never inside Program Files."""
    override = os.environ.get("RETVIA_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        base = Path(root) / APP_USER_DIR_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_USER_DIR_NAME
    else:
        root = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        base = Path(root) / APP_USER_DIR_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


class ServiceContainer:
    """Lazily constructs and shares every application service."""

    def __init__(self, data_dir: Path | None = None, *, actor: str = "") -> None:
        self.data_dir = Path(data_dir) if data_dir else user_data_dir()
        (self.data_dir / "data").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "backups").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "assets" / "business").mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "data" / "retvia.db")
        self.db.migrate()
        seed_defaults(self.db)

        self.settings = SettingsService(self.db)
        self.audit = AuditService(self.db, actor=actor or self.settings.get("cashier_name", ""))
        self.numbering = NumberingService(self.db, self.settings)
        self.profile = BusinessProfileService(self.db)
        self.inventory = InventoryService(self.db, self.settings, self.audit, self.numbering)
        self.categories = CategoryService(self.db, self.audit)
        self.units = UnitService(self.db, self.audit)
        self.products = ProductService(self.db, self.inventory, self.audit, self.settings)
        self.barcodes = BarcodeService(self.db, self.audit)
        self.customers = CustomerService(self.db, self.audit)
        self.suppliers = SupplierService(self.db, self.audit)
        self.payment_methods = PaymentMethodService(self.db, self.audit)
        self.cash = CashService(self.db, self.settings, self.audit)
        self.sales = SalesService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            inventory=self.inventory,
            numbering=self.numbering,
            cash=self.cash,
        )
        self.purchases = PurchaseService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            inventory=self.inventory,
            numbering=self.numbering,
            cash=self.cash,
        )
        self.customer_payments = CustomerPaymentService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            numbering=self.numbering,
            cash=self.cash,
        )
        self.supplier_payments = SupplierPaymentService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            numbering=self.numbering,
            cash=self.cash,
        )
        self.sales_returns = SalesReturnService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            inventory=self.inventory,
            numbering=self.numbering,
            cash=self.cash,
            customer_payments=self.customer_payments,
        )
        self.purchase_returns = PurchaseReturnService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            inventory=self.inventory,
            numbering=self.numbering,
            cash=self.cash,
            supplier_payments=self.supplier_payments,
        )
        self.expenses = ExpenseService(
            self.db,
            settings=self.settings,
            audit=self.audit,
            numbering=self.numbering,
            cash=self.cash,
        )
        self.finance = FinanceService(self.db, self.settings, self.inventory)
        self.reports = ReportService(self.db, self.settings)
        self.exporting = ExportService(self.settings, self.profile)
        self.backup = BackupService(self.db, self.data_dir, settings=self.settings, audit=self.audit)
        self.users = UserService(self.db, self.audit)
        self.activation = ActivationService(self.db)
        self.current_user: dict[str, Any] | None = None

    def set_actor(self, actor: str) -> None:
        self.audit.actor = actor

    # ----------------------------------------------------------------- session
    def login(self, username: str, password: str) -> dict[str, Any]:
        user = self.users.authenticate(username, password)
        self.current_user = user
        self.set_actor(user["display_name"] or user["username"])
        return user

    def logout(self) -> None:
        if self.current_user and self.audit:
            self.audit.log("user", self.current_user["id"], "logout", "লগআউট")
        self.current_user = None
        self.set_actor("")

    def can(self, permission: str) -> bool:
        if self.current_user is None:
            return False
        return permission in PERMISSIONS.get(self.current_user["role"], set())

    # ---------------------------------------------------------------- printing
    def receipt_pdf(self, sale_id: int, path: str | Path) -> Path:
        """Render a sale receipt to a PDF file with the embedded Bangla font."""
        from ..printing.documents import render_receipt_pdf

        sale = self.sales.get(sale_id)
        return render_receipt_pdf(sale, self.profile.get(), self.settings, path)

    def print_receipt(self, sale_id: int, *, copy_label: str = "") -> None:
        from ..printing.documents import print_html, receipt_html

        sale = self.sales.get(sale_id)
        html_text = receipt_html(sale, self.profile.get(), self.settings, copy_label=copy_label)
        print_html(
            html_text,
            printer_name=self.settings.get("printer_name"),
            width_mm=float(self.settings.get("paper_width_mm", "80")),
            margin_mm=float(self.settings.get_int("receipt_margin_mm", 3)),
            copies=self.settings.get_int("receipt_copies", 1),
            raster=self.settings.get_bool("receipt_raster_mode", True),
        )

    def health(self) -> dict[str, Any]:
        """Human-readable system health, used by the About screen."""
        reconciliation = self.finance.reconcile_all()
        counts = self.db.table_counts()
        problems = reconciliation["problems"]
        issue_count = sum(len(v) for v in problems.values())
        checks = [
            {"check": "ডেটা ফোল্ডার", "result": str(self.data_dir)},
            {"check": "ডেটাবেস ফাইল", "result": str(self.db.path)},
            {"check": "স্কিমা সংস্করণ", "result": str(self.db.schema_version)},
            {"check": "ইন্টিগ্রিটি চেক", "result": reconciliation["integrity_check"]},
            {
                "check": "ফরেন কি যাচাই",
                "result": "কোনো সমস্যা নেই ✓"
                if not reconciliation["foreign_key_violations"]
                else f"{len(reconciliation['foreign_key_violations'])} সমস্যা",
            },
            {
                "check": "লেজার সমন্বয়",
                "result": "সব হিসাব মিলে গেছে ✓" if reconciliation["healthy"] else f"{issue_count} অমিল",
            },
            {"check": "প্রোডাক্ট সংখ্যা", "result": str(counts.get("products", 0))},
            {"check": "ইনভয়েস সংখ্যা", "result": str(counts.get("sales", 0))},
            {"check": "ব্যাকআপ সংখ্যা", "result": str(len(self.backup.list_files()))},
            {
                "check": "লাইসেন্স",
                "result": "সক্রিয় ✓" if self.activation.status().get("activated") else "সক্রিয় নয়",
            },
        ]
        return {
            "data_dir": str(self.data_dir),
            "database": str(self.db.path),
            "schema_version": self.db.schema_version,
            "reconciliation": reconciliation,
            "counts": counts,
            "checks": checks,
            "healthy": reconciliation["healthy"],
        }

    def maybe_auto_backup(self) -> dict[str, Any] | None:
        """Run an automatic backup when the configured interval has elapsed."""
        history = [h for h in self.backup.history(limit=50) if h["backup_type"] == "automatic"]
        last_run = None
        if history:
            from datetime import datetime

            try:
                last_run = datetime.fromisoformat(history[0]["created_at"])
            except ValueError:
                last_run = None
        if not self.backup.should_auto_backup(last_run):
            return None
        result = self.backup.create(backup_type="automatic")
        self.backup.prune()
        return result

    def close(self) -> None:
        self.db.close()
