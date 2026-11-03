"""Expense and cash-register screens."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    KpiCard,
    PageHeader,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)


class ExpensesView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("এক্সপেন্স ম্যানেজমেন্ট", "দৈনিক খরচ নথিভুক্ত করুন — নেট প্রফিটে স্বয়ংক্রিয়ভাবে যুক্ত হবে")
        header.add_action("+ নতুন এক্সপেন্স", self._create, kind="Primary")
        header.add_action("বাতিল করুন", self._delete, kind="Danger")
        layout.addWidget(header)

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
        controls.addStretch(1)
        self.total_card = KpiCard("মোট এক্সপেন্স", "—", tone="danger")
        controls.addWidget(self.total_card)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)
        self.table = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("voucher_no", "ভাউচার", width=130),
                TableColumn("expense_date", "তারিখ", "date", 100),
                TableColumn("category_name", "ক্যাটাগরি", width=160),
                TableColumn("method_name", "মেথড", width=110),
                TableColumn("description", "বিবরণ", width=240),
                TableColumn("amount", "পরিমাণ", "money", 120),
            ]
        )
        splitter.addWidget(self.table)
        self.by_category = DataTable(
            [
                TableColumn("name", "ক্যাটাগরি", width=200),
                TableColumn("count", "সংখ্যা", "int", 80),
                TableColumn("total", "মোট", "money", 130),
            ]
        )
        card = Card("ক্যাটাগরি অনুযায়ী")
        card.add(self.by_category)
        splitter.addWidget(card)
        splitter.setSizes([720, 340])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        start = self.start.date().toString("yyyy-MM-dd")
        end = self.end.date().toString("yyyy-MM-dd")
        result = guarded(self, lambda: self.services.expenses.search(start=start, end=end, limit=500))
        if result:
            self.table.set_rows(result["rows"])
            self.total_card.set_value(format_money(result["total_amount"], symbol="৳ "))
        self.by_category.set_rows(self.services.expenses.by_category(start, end))

    def _create(self) -> None:
        categories = [(c["id"], c["name"]) for c in self.services.expenses.categories(active_only=True)]
        methods = [(m["id"], m["name"]) for m in self.services.payment_methods.list()]
        if not categories:
            show_error(self, "আগে একটি এক্সপেন্স ক্যাটাগরি তৈরি করুন")
            return
        values = FormDialog.ask(
            "নতুন এক্সপেন্স",
            [
                FieldSpec("category_id", "ক্যাটাগরি", "combo", required=True, options=categories),
                FieldSpec("amount", "পরিমাণ", "money", required=True, value=0),
                FieldSpec("date", "তারিখ", "date"),
                FieldSpec("method_id", "পেমেন্ট মেথড", "combo", required=True, options=methods),
                FieldSpec("description", "বিবরণ", "text"),
                FieldSpec("reference", "রেফারেন্স", "text"),
                FieldSpec("notes", "নোট", "textarea"),
            ],
            self,
        )
        if values is None or values["amount"] <= 0:
            return
        result = guarded(
            self,
            lambda: self.services.expenses.create(
                category_id=values["category_id"],
                amount=values["amount"],
                method_id=values["method_id"],
                expense_date=values["date"],
                description=values["description"],
                reference=values["reference"],
                notes=values["notes"],
            ),
        )
        if result:
            show_info(self, f"এক্সপেন্স সংরক্ষিত\nভাউচার: {result['voucher_no']}")
        self.refresh()

    def _delete(self) -> None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি এক্সপেন্স নির্বাচন করুন")
            return
        values = FormDialog.ask("এক্সপেন্স বাতিল", [FieldSpec("reason", "কারণ", "text", required=True)], self)
        if values is None:
            return
        guarded(self, lambda: self.services.expenses.delete(record["id"], reason=values["reason"]) or True)
        self.refresh()


class CashView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("ক্যাশ রেজিস্টার ও শিফট", "ক্যাশ ড্রয়ার খোলা, ক্যাশ ইন/আউট এবং শিফট ক্লোজিং")
        header.add_action("শিফট খুলুন", self._open, kind="Primary")
        header.add_action("ক্যাশ ইন", lambda: self._manual("cash_in"), kind="Accent")
        header.add_action("ক্যাশ আউট", lambda: self._manual("cash_out"))
        header.add_action("শিফট বন্ধ করুন", self._close, kind="Danger")
        layout.addWidget(header)

        kpis = QHBoxLayout()
        self.opening = KpiCard("ওপেনিং ক্যাশ", "—")
        self.expected = KpiCard("প্রত্যাশিত ক্যাশ", "—", tone="accent")
        self.status = KpiCard("শিফট স্ট্যাটাস", "বন্ধ")
        self.difference = KpiCard("সর্বশেষ পার্থক্য", "—")
        for card in (self.opening, self.expected, self.status, self.difference):
            kpis.addWidget(card)
        layout.addLayout(kpis)

        self.tabs = QTabWidget()
        self.movements = DataTable(
            [
                TableColumn("movement_at", "সময়", width=160),
                TableColumn("movement_type", "ধরন", width=170),
                TableColumn("method_name", "মেথড", width=110),
                TableColumn("amount", "পরিমাণ", "money", 130),
                TableColumn("notes", "বিবরণ", width=280),
            ]
        )
        self.summary = DataTable(
            [
                TableColumn("label", "ধরন", width=240),
                TableColumn("count", "সংখ্যা", "int", 90),
                TableColumn("total", "মোট", "money", 140),
            ]
        )
        self.sessions = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("opened_at", "শুরু", width=160),
                TableColumn("closed_at", "শেষ", width=160),
                TableColumn("opening_cash", "ওপেনিং", "money", 110),
                TableColumn("expected_cash", "প্রত্যাশিত", "money", 120),
                TableColumn("actual_cash", "প্রকৃত", "money", 110),
                TableColumn("difference", "পার্থক্য", "money", 110),
                TableColumn("status", "স্ট্যাটাস", width=90),
            ]
        )
        for widget, label in (
            (self.movements, "ক্যাশ মুভমেন্ট"),
            (self.summary, "সারাংশ"),
            (self.sessions, "শিফট হিস্ট্রি"),
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
        from ...services.cash import MOVEMENT_LABELS

        session = self.services.cash.current_session()
        if session:
            self.status.set_value("খোলা", f"শিফট #{session['id']}")
            self.opening.set_value(format_money(int(session["opening_cash"]), symbol="৳ "))
            self.expected.set_value(
                format_money(self.services.cash.expected_cash(session["id"]), symbol="৳ ")
            )
            rows = self.services.cash.movements(session["id"])
            for row in rows:
                row["movement_type"] = MOVEMENT_LABELS.get(row["movement_type"], row["movement_type"])
            self.movements.set_rows(rows)
            self.summary.set_rows(self.services.cash.summary_by_type(session["id"]))
        else:
            self.status.set_value("বন্ধ", "ক্যাশ নিতে শিফট খুলুন")
            self.opening.set_value("—")
            self.expected.set_value("—")
            self.movements.set_rows([])
            self.summary.set_rows([])
        sessions = self.services.cash.sessions(limit=100)
        self.sessions.set_rows(sessions)
        closed = [s for s in sessions if s["status"] == "closed" and s["difference"] is not None]
        self.difference.set_value(format_money(int(closed[0]["difference"]), symbol="৳ ") if closed else "—")

    def _open(self) -> None:
        values = FormDialog.ask(
            "নতুন ক্যাশ শিফট",
            [
                FieldSpec("opening_cash", "ওপেনিং ক্যাশ", "money", value=0),
                FieldSpec("notes", "নোট", "textarea"),
            ],
            self,
        )
        if values is None:
            return
        if guarded(
            self,
            lambda: self.services.cash.open_session(
                opening_cash=values["opening_cash"],
                actor=self.services.settings.get("cashier_name", ""),
                notes=values["notes"],
            ),
        ):
            show_info(self, "ক্যাশ শিফট খোলা হয়েছে")
        self.refresh()

    def _manual(self, kind: str) -> None:
        values = FormDialog.ask(
            "ক্যাশ ইন" if kind == "cash_in" else "ক্যাশ আউট",
            [
                FieldSpec("amount", "পরিমাণ", "money", required=True, value=0),
                FieldSpec("reason", "কারণ", "text", required=True),
            ],
            self,
        )
        if values is None or values["amount"] <= 0:
            return
        guarded(
            self,
            lambda: self.services.cash.manual_movement(
                movement_type=kind,
                amount=values["amount"],
                reason=values["reason"],
                actor=self.services.settings.get("cashier_name", ""),
            ),
        )
        self.refresh()

    def _close(self) -> None:
        session = self.services.cash.current_session()
        if session is None:
            show_error(self, "কোনো শিফট খোলা নেই")
            return
        expected = self.services.cash.expected_cash(session["id"])
        values = FormDialog.ask(
            "শিফট বন্ধ করুন",
            [
                FieldSpec("expected", "প্রত্যাশিত ক্যাশ", "readonly", value=format_money(expected)),
                FieldSpec("actual", "প্রকৃত গণনাকৃত ক্যাশ", "money", required=True, value=expected),
                FieldSpec("notes", "নোট", "textarea"),
            ],
            self,
        )
        if values is None:
            return
        if not confirm(self, "শিফট বন্ধ করলে আর লেনদেন যোগ করা যাবে না। নিশ্চিত?"):
            return
        result = guarded(
            self,
            lambda: self.services.cash.close_session(
                session_id=session["id"],
                actual_cash=values["actual"],
                actor=self.services.settings.get("cashier_name", ""),
                notes=values["notes"],
            ),
        )
        if result:
            show_info(self, f"শিফট বন্ধ হয়েছে\nপার্থক্য: {format_money(int(result['difference']), symbol='৳ ')}")
        self.refresh()
