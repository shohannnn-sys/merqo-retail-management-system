"""Inventory: stock ledger, valuation, alerts and reconciliation."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    KpiCard,
    PageHeader,
    TableColumn,
    guarded,
    show_info,
)

MOVEMENT_LABELS = {
    "opening": "ওপেনিং স্টক",
    "purchase": "পারচেজ",
    "sale": "সেলস",
    "sales_return_restock": "সেলস রিটার্ন (স্টকে)",
    "purchase_return": "পারচেজ রিটার্ন",
    "adjustment_in": "সমন্বয় বৃদ্ধি",
    "adjustment_out": "সমন্বয় হ্রাস",
}


class InventoryView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("ইনভেন্টরি ম্যানেজমেন্ট", "স্টক লেজার, ভ্যালুয়েশন, সতর্কতা ও সমন্বয় যাচাই")
        header.add_action("লেজার যাচাই করুন", self._reconcile, kind="Primary")
        layout.addWidget(header)

        kpis = QHBoxLayout()
        self.value_card = KpiCard("মোট স্টক মূল্য", "—", tone="accent")
        self.count_card = KpiCard("স্টক ট্র্যাকড প্রোডাক্ট", "০")
        self.low_card = KpiCard("লো স্টক", "০")
        self.out_card = KpiCard("স্টক আউট", "০", tone="danger")
        for card in (self.value_card, self.count_card, self.low_card, self.out_card):
            kpis.addWidget(card)
        layout.addLayout(kpis)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("প্রোডাক্ট:"))
        self.product_filter = QComboBox()
        self.product_filter.currentIndexChanged.connect(lambda: self._load_ledger())
        controls.addWidget(self.product_filter, 2)
        controls.addWidget(QLabel("তারিখ:"))
        self.start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end = QDateEdit(QDate.currentDate())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.dateChanged.connect(lambda: self._load_ledger())
        controls.addWidget(self.start)
        controls.addWidget(QLabel("থেকে"))
        controls.addWidget(self.end)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.tabs = QTabWidget()
        self.ledger = DataTable(
            [
                TableColumn("movement_date", "তারিখ", "date", 100),
                TableColumn("movement_type", "ধরন", width=150),
                TableColumn("qty_delta", "পরিমাণ", "qty", 110),
                TableColumn("qty_before", "পূর্বে", "qty", 100),
                TableColumn("qty_after", "পরে", "qty", 100),
                TableColumn("unit_cost", "একক খরচ", "money", 110),
                TableColumn("value_delta", "মূল্য পরিবর্তন", "money", 130),
                TableColumn("notes", "নোট", width=220),
            ]
        )
        self.valuation = DataTable(
            [
                TableColumn("name", "প্রোডাক্ট", width=240),
                TableColumn("sku", "এসকেইউ", width=120),
                TableColumn("stock_qty", "মজুদ", "qty", 110),
                TableColumn("avg_cost", "গড় খরচ", "money", 120),
                TableColumn("stock_value", "স্টক মূল্য", "money", 140),
            ]
        )
        self.low_table = DataTable(
            [
                TableColumn("name", "প্রোডাক্ট", width=240),
                TableColumn("stock_qty", "মজুদ", "qty", 110),
                TableColumn("min_stock_qty", "মিনিমাম", "qty", 110),
            ]
        )
        self.out_table = DataTable(
            [
                TableColumn("name", "প্রোডাক্ট", width=260),
                TableColumn("sku", "এসকেইউ", width=140),
                TableColumn("min_stock_qty", "মিনিমাম", "qty", 110),
            ]
        )
        self.adjustments = DataTable(
            [
                TableColumn("adjustment_no", "নং", width=130),
                TableColumn("adjustment_date", "তারিখ", "date", 100),
                TableColumn("adjustment_type", "ধরন", width=130),
                TableColumn("qty_delta", "পরিমাণ", "qty", 110),
                TableColumn("value_delta", "মূল্য", "money", 120),
                TableColumn("reason", "কারণ", width=260),
            ]
        )
        for widget, label in (
            (self.ledger, "স্টক লেজার"),
            (self.valuation, "ইনভেন্টরি ভ্যালুয়েশন"),
            (self.low_table, "লো স্টক"),
            (self.out_table, "স্টক আউট"),
            (self.adjustments, "স্টক সমন্বয়"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, SPACE["md"], 0, 0)
            card = Card()
            card.add(widget)
            page_layout.addWidget(card)
            self.tabs.addTab(page, label)
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        valuation = self.services.inventory.valuation()
        self.value_card.set_value(format_money(int(valuation["total_value"]), symbol="৳ "))
        self.count_card.set_value(str(valuation["product_count"]))
        self.low_card.set_value(str(len(self.services.inventory.low_stock(limit=1000))))
        self.out_card.set_value(str(len(self.services.inventory.out_of_stock(limit=1000))))

        self.product_filter.blockSignals(True)
        current = self.product_filter.currentData()
        self.product_filter.clear()
        self.product_filter.addItem("— সব প্রোডাক্ট —", None)
        for row in self.services.products.search(limit=2000, status="all")["rows"]:
            self.product_filter.addItem(f"{row['name']} · {row['sku']}", row["id"])
        index = self.product_filter.findData(current)
        if index >= 0:
            self.product_filter.setCurrentIndex(index)
        self.product_filter.blockSignals(False)

        self.valuation.set_rows(self.services.inventory.valuation_rows())
        self.low_table.set_rows(self.services.inventory.low_stock(limit=500))
        self.out_table.set_rows(self.services.inventory.out_of_stock(limit=500))
        self.adjustments.set_rows(
            [
                dict(r)
                for r in self.services.db.query("SELECT * FROM stock_adjustments ORDER BY id DESC LIMIT 300")
            ]
        )
        self._load_ledger()

    def _load_ledger(self) -> None:
        product_id = self.product_filter.currentData()
        start = self.start.date().toString("yyyy-MM-dd")
        end = self.end.date().toString("yyyy-MM-dd")
        if product_id:
            rows = self.services.inventory.ledger(product_id, start=start, end=end, limit=500)
        else:
            rows = [
                dict(r)
                for r in self.services.db.query(
                    """SELECT m.*, p.name AS product_name FROM stock_movements m
                     JOIN products p ON p.id=m.product_id
                    WHERE m.movement_date BETWEEN ? AND ? ORDER BY m.id DESC LIMIT 500""",
                    (start, end),
                )
            ]
        for row in rows:
            row["movement_type"] = MOVEMENT_LABELS.get(row["movement_type"], row["movement_type"])
        self.ledger.set_rows(rows)

    def _reconcile(self) -> None:
        result = guarded(self, lambda: self.services.finance.reconcile_all())
        if result is None:
            return
        if result["healthy"]:
            show_info(
                self,
                "সব লেজার মিলে গেছে ✓\n\nস্টক, কাস্টমার, সাপ্লায়ার, ইনভয়েস ও ক্যাশ হিসাব সম্পূর্ণ সামঞ্জস্যপূর্ণ।",
                "লেজার যাচাই",
            )
        else:
            details = "\n".join(f"• {key}: {len(value)} সমস্যা" for key, value in result["problems"].items())
            show_info(self, f"অমিল পাওয়া গেছে:\n\n{details}\n\nবিস্তারিত লগে সংরক্ষিত হয়েছে।", "লেজার যাচাই")
