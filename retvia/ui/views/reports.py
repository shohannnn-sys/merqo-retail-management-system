"""Report centre — all 34 reports with filters and CSV / Excel / PDF export."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    PageHeader,
    TableColumn,
    guarded,
    show_error,
    show_info,
)


class ReportsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._result = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("রিপোর্ট সেন্টার", "৩৪টি রিপোর্ট — CSV, Excel ও বাংলা PDF এক্সপোর্ট")
        header.add_action("রিপোর্ট চালান", self._run, kind="Primary")
        header.add_action("CSV", lambda: self._export("csv"))
        header.add_action("Excel", lambda: self._export("xlsx"), kind="Accent")
        header.add_action("PDF", lambda: self._export("pdf"))
        layout.addWidget(header)

        filters = QHBoxLayout()
        filters.setSpacing(SPACE["sm"])
        filters.addWidget(QLabel("সময়কাল:"))
        self.preset = QComboBox()
        for key, label in (
            ("today", "আজ"),
            ("yesterday", "গতকাল"),
            ("this_week", "এই সপ্তাহ"),
            ("this_month", "এই মাস"),
            ("this_year", "এই বছর"),
            ("last_30", "গত ৩০ দিন"),
            ("custom", "কাস্টম"),
        ):
            self.preset.addItem(label, key)
        self.preset.setCurrentIndex(3)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        filters.addWidget(self.preset)
        self.start = QDateEdit(QDate.currentDate().addDays(-29))
        self.end = QDateEdit(QDate.currentDate())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
        filters.addWidget(self.start)
        filters.addWidget(QLabel("থেকে"))
        filters.addWidget(self.end)
        filters.addWidget(QLabel("পার্টি:"))
        self.party = QComboBox()
        filters.addWidget(self.party, 1)
        filters.addWidget(QLabel("সীমা:"))
        self.limit = QComboBox()
        for value in (10, 20, 50, 100, 500):
            self.limit.addItem(str(value), value)
        self.limit.setCurrentIndex(1)
        filters.addWidget(self.limit)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.report_list = QListWidget()
        self.report_list.itemSelectionChanged.connect(self._selection_changed)
        self.report_list.itemDoubleClicked.connect(lambda _: self._run())
        splitter.addWidget(self.report_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(SPACE["md"], 0, 0, 0)
        self.description = QLabel("বাম দিক থেকে একটি রিপোর্ট নির্বাচন করুন")
        self.description.setObjectName("PageSubtitle")
        self.description.setWordWrap(True)
        right_layout.addWidget(self.description)
        self.table = DataTable([])
        self._table_card = Card()
        self._table_card.add(self.table)
        right_layout.addWidget(self._table_card, 1)
        self.totals_label = QLabel("")
        self.totals_label.setObjectName("Muted")
        self.totals_label.setWordWrap(True)
        right_layout.addWidget(self.totals_label)
        splitter.addWidget(right)
        splitter.setSizes([280, 800])
        layout.addWidget(splitter, 1)
        self._populate()

    def _populate(self) -> None:
        self.report_list.clear()
        grouped: dict[str, list] = {}
        for meta in self.services.reports.list_reports():
            grouped.setdefault(meta["group"], []).append(meta)
        for group, definitions in grouped.items():
            header = QListWidgetItem(f"— {group} —")
            header.setFlags(Qt.NoItemFlags)
            self.report_list.addItem(header)
            for meta in definitions:
                item = QListWidgetItem(f"  {meta['title']}")
                item.setData(Qt.UserRole, meta["id"])
                self.report_list.addItem(item)

    def refresh(self) -> None:
        current = self.party.currentData()
        self.party.clear()
        self.party.addItem("— প্রযোজ্য নয় —", None)
        definition = self._current_definition()
        if definition and definition.party_filter == "customer":
            for row in self.services.customers.search(limit=500)["rows"]:
                self.party.addItem(f"কাস্টমার: {row['name']}", ("customer", row["id"]))
        if definition and definition.party_filter == "supplier":
            for row in self.services.suppliers.search(limit=500)["rows"]:
                self.party.addItem(f"সাপ্লায়ার: {row['name']}", ("supplier", row["id"]))
        index = self.party.findData(current)
        if index >= 0:
            self.party.setCurrentIndex(index)

    def _current_definition(self):
        item = self.report_list.currentItem()
        if item is None:
            return None
        report_id = item.data(Qt.UserRole)
        if not report_id:
            return None
        return self.services.reports.definition(report_id)

    def _selection_changed(self) -> None:
        definition = self._current_definition()
        if definition:
            self.description.setText(definition.description)
        self.refresh()

    def _preset_changed(self) -> None:
        from ...services.finance import date_range_for

        key = self.preset.currentData()
        if key == "custom":
            return
        start, end = date_range_for(key)
        self.start.setDate(QDate.fromString(start, "yyyy-MM-dd"))
        self.end.setDate(QDate.fromString(end, "yyyy-MM-dd"))

    def _filters(self) -> dict:
        filters = {
            "start": self.start.date().toString("yyyy-MM-dd"),
            "end": self.end.date().toString("yyyy-MM-dd"),
            "limit": self.limit.currentData(),
        }
        party = self.party.currentData()
        if party:
            kind, identifier = party
            filters["customer_id" if kind == "customer" else "supplier_id"] = identifier
        return filters

    def _run(self) -> None:
        definition = self._current_definition()
        if definition is None:
            show_error(self, "আগে একটি রিপোর্ট নির্বাচন করুন")
            return
        filters = self._filters()
        if definition.requires_party and f"{definition.requires_party}_id" not in filters:
            show_error(self, "এই রিপোর্টের জন্য একটি পার্টি নির্বাচন করা আবশ্যক")
            return
        result = guarded(self, lambda: self.services.reports.run(definition.id, filters))
        if result is None:
            return
        self._result = result
        widths = {"money": 130, "qty": 110, "date": 105, "int": 90, "percent": 100}
        columns = [TableColumn(c.key, c.label, c.kind, width=widths.get(c.kind, 180)) for c in result.columns]
        previous = self.table
        self.table = DataTable(columns)
        self.table.set_rows(result.rows)
        if self._table_card is not None:
            self._table_card.body.replaceWidget(previous, self.table)
        previous.setParent(None)
        previous.deleteLater()
        parts = []
        for key, value in result.totals.items():
            column = next((c for c in result.columns if c.key == key), None)
            label = column.label if column else key
            shown = format_money(int(value)) if column and column.kind == "money" else str(value)
            parts.append(f"{label}: {shown}")
        self.totals_label.setText(f"{len(result.rows)} সারি  ·  " + "  |  ".join(parts))

    def _export(self, fmt: str) -> None:
        if self._result is None:
            show_error(self, "আগে রিপোর্ট চালান")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "রিপোর্ট এক্সপোর্ট", f"{self._result.id}.{fmt}", f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        saved = guarded(self, lambda: self.services.exporting.export(self._result, path, fmt))
        if saved:
            show_info(self, f"এক্সপোর্ট সম্পন্ন:\n{saved}")


class TransactionsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.addWidget(
            PageHeader(
                "লেনদেন হিস্ট্রি",
                "সব আর্থিক লেনদেনের অপরিবর্তনযোগ্য রেকর্ড — সংশোধন কেবল রিভার্সাল এন্ট্রি দিয়ে",
            )
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("তারিখ:"))
        self.start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end = QDateEdit(QDate.currentDate())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.dateChanged.connect(lambda: self.refresh())
        controls.addWidget(self.start)
        controls.addWidget(QLabel("থেকে"))
        controls.addWidget(self.end)
        controls.addWidget(QLabel("ধরন:"))
        self.kind = QComboBox()
        self.kind.addItem("সব", None)
        for value, label in (
            ("sale", "সেলস"),
            ("sale_cancel", "সেলস বাতিল"),
            ("sales_return", "সেলস রিটার্ন"),
            ("purchase", "পারচেজ"),
            ("purchase_return", "পারচেজ রিটার্ন"),
            ("customer_payment", "কাস্টমার পেমেন্ট"),
            ("supplier_payment", "সাপ্লায়ার পেমেন্ট"),
            ("expense", "এক্সপেন্স"),
            ("cash_in", "ক্যাশ ইন"),
            ("cash_out", "ক্যাশ আউট"),
        ):
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(lambda: self.refresh())
        controls.addWidget(self.kind, 1)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.table = DataTable(
            [
                TableColumn("txn_no", "লেনদেন নং", width=140),
                TableColumn("txn_date", "তারিখ", "date", 100),
                TableColumn("reference_type", "উৎস", width=120),
                TableColumn("txn_type", "ধরন", width=160),
                TableColumn("payment_summary", "পেমেন্ট", width=150),
                TableColumn("party_name", "পার্টি", width=180),
                TableColumn("status", "স্ট্যাটাস", width=110),
                TableColumn("amount", "পরিমাণ", "money", 120),
                TableColumn("notes", "নোট", width=220),
            ]
        )
        card = Card()
        card.add(self.table)
        layout.addWidget(card, 1)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        layout.addWidget(self.summary)

    def refresh(self) -> None:
        result = guarded(
            self,
            lambda: self.services.finance.transactions(
                start=self.start.date().toString("yyyy-MM-dd"),
                end=self.end.date().toString("yyyy-MM-dd"),
                txn_type=self.kind.currentData(),
                limit=1000,
            ),
        )
        if result is None:
            return
        self.table.set_rows(result["rows"])
        total = sum(int(r["amount"]) for r in result["rows"])
        self.summary.setText(f"{result['total']} লেনদেন  ·  মোট {format_money(total, symbol='৳ ')}")
