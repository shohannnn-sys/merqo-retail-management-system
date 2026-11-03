"""Category, unit and payment-method configuration screens."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..theme import SPACE
from ..widgets import (
    DataTable,
    FieldSpec,
    FormDialog,
    PageHeader,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)


class _SimpleCrudTab(QWidget):
    """Shared behaviour for the small configuration tables."""

    def __init__(self, services, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACE["md"], 0, 0)
        titles = {
            "category": ("ক্যাটাগরি", "প্রোডাক্ট ক্যাটাগরি তৈরি ও ব্যবস্থাপনা"),
            "unit": ("ইউনিট", "পরিমাপের ইউনিট ও দশমিক নির্ভুলতা"),
            "method": ("পেমেন্ট মেথড", "ক্যাশ, মোবাইল ব্যাংকিং ও অন্যান্য মেথড"),
            "expense_category": ("এক্সপেন্স ক্যাটাগরি", "খরচের খাতসমূহ"),
        }
        title, subtitle = titles[kind]
        header = PageHeader(title, subtitle)
        header.add_action("+ নতুন", self._create, kind="Primary")
        if kind != "method":
            header.add_action("সম্পাদনা", self._edit)
            header.add_action("মুছে ফেলুন", self._delete, kind="Danger")
        else:
            header.add_action("সক্রিয় / নিষ্ক্রিয়", self._toggle)
        layout.addWidget(header)
        self.table = DataTable(self._columns())
        layout.addWidget(self.table, 1)
        self.refresh()

    def _columns(self) -> list[TableColumn]:
        if self.kind == "category":
            return [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("name", "নাম", width=260),
                TableColumn("description", "বিবরণ", width=300),
                TableColumn("product_count", "প্রোডাক্ট সংখ্যা", "int", 120),
            ]
        if self.kind == "unit":
            return [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("name", "নাম", width=200),
                TableColumn("symbol", "প্রতীক", width=100),
                TableColumn("decimal_precision", "দশমিক ঘর", "int", 120),
            ]
        if self.kind == "method":
            return [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("name", "নাম", width=220),
                TableColumn("is_cash", "ক্যাশ?", "int", 90),
                TableColumn("is_active", "সক্রিয়?", "int", 90),
            ]
        return [TableColumn("id", "আইডি", "int", 60), TableColumn("name", "নাম", width=300)]

    def refresh(self) -> None:
        if self.kind == "category":
            rows = self.services.categories.list()
        elif self.kind == "unit":
            rows = self.services.units.list()
        elif self.kind == "method":
            rows = self.services.payment_methods.list(active_only=False)
        else:
            rows = self.services.expenses.categories()
        self.table.set_rows(rows)

    def _selected(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি সারি নির্বাচন করুন")
        return record

    def _fields(self, existing: dict[str, Any] | None = None) -> list[FieldSpec]:
        e = existing or {}
        if self.kind == "category":
            return [
                FieldSpec("name", "ক্যাটাগরির নাম", "text", required=True, value=e.get("name", "")),
                FieldSpec("description", "বিবরণ", "textarea", value=e.get("description", "")),
            ]
        if self.kind == "unit":
            return [
                FieldSpec("name", "ইউনিটের নাম", "text", required=True, value=e.get("name", "")),
                FieldSpec("symbol", "প্রতীক", "text", value=e.get("symbol", "")),
                FieldSpec(
                    "precision",
                    "দশমিক ঘর (০–৩)",
                    "int",
                    value=e.get("decimal_precision", 0),
                    help="কেজি/লিটারের জন্য ৩, পিসের জন্য ০",
                ),
            ]
        if self.kind == "method":
            return [
                FieldSpec("name", "মেথডের নাম", "text", required=True),
                FieldSpec("is_cash", "এটি ক্যাশ মেথড (ড্রয়ারে যোগ হবে)", "checkbox", value=False),
            ]
        return [FieldSpec("name", "ক্যাটাগরির নাম", "text", required=True)]

    def _create(self) -> None:
        values = FormDialog.ask("নতুন এন্ট্রি", self._fields(), self)
        if values is None:
            return

        def action():
            if self.kind == "category":
                return self.services.categories.create(values["name"], description=values["description"])
            if self.kind == "unit":
                return self.services.units.create(
                    values["name"], symbol=values["symbol"], precision=values["precision"]
                )
            if self.kind == "method":
                return self.services.payment_methods.create(values["name"], is_cash=values["is_cash"])
            return self.services.expenses.create_category(values["name"])

        if guarded(self, action):
            show_info(self, "সফলভাবে যোগ হয়েছে")
        self.refresh()

    def _edit(self) -> None:
        record = self._selected()
        if record is None:
            return
        values = FormDialog.ask("সম্পাদনা", self._fields(record), self)
        if values is None:
            return

        def action():
            if self.kind == "category":
                return (
                    self.services.categories.update(
                        record["id"], values["name"], description=values["description"]
                    )
                    or True
                )
            return (
                self.services.units.update(
                    record["id"], values["name"], symbol=values["symbol"], precision=values["precision"]
                )
                or True
            )

        guarded(self, action)
        self.refresh()

    def _delete(self) -> None:
        record = self._selected()
        if record is None or not confirm(self, f"'{record['name']}' মুছে ফেলবেন?"):
            return

        def action():
            if self.kind == "category":
                return self.services.categories.delete(record["id"]) or True
            if self.kind == "unit":
                return self.services.units.delete(record["id"]) or True
            return self.services.expenses.delete_category(record["id"]) or True

        guarded(self, action)
        self.refresh()

    def _toggle(self) -> None:
        record = self._selected()
        if record is None:
            return
        guarded(
            self,
            lambda: self.services.payment_methods.set_active(record["id"], not bool(record["is_active"]))
            or True,
        )
        self.refresh()


class CatalogView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        self.tabs = QTabWidget()
        self.category_tab = _SimpleCrudTab(services, "category")
        self.unit_tab = _SimpleCrudTab(services, "unit")
        self.method_tab = _SimpleCrudTab(services, "method")
        self.expense_tab = _SimpleCrudTab(services, "expense_category")
        self.tabs.addTab(self.category_tab, "ক্যাটাগরি")
        self.tabs.addTab(self.unit_tab, "ইউনিট")
        self.tabs.addTab(self.method_tab, "পেমেন্ট মেথড")
        self.tabs.addTab(self.expense_tab, "এক্সপেন্স ক্যাটাগরি")
        layout.addWidget(self.tabs)

    def refresh(self) -> None:
        self.category_tab.refresh()
        self.unit_tab.refresh()
        self.method_tab.refresh()
        self.expense_tab.refresh()
