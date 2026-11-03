"""Document views: sales invoices, purchases and returns."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ...core.quantity import format_quantity
from ...services.purchases import PurchaseInput, PurchaseLineInput
from ...services.returns import PurchaseReturnLine, SalesReturnLine
from ...services.sales import PaymentInput
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    PageHeader,
    SearchBox,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)


def _date_range_row(view: QWidget, on_change) -> tuple[QHBoxLayout, QDateEdit, QDateEdit]:
    row = QHBoxLayout()
    start = QDateEdit(QDate.currentDate().addMonths(-1))
    end = QDateEdit(QDate.currentDate())
    for widget in (start, end):
        widget.setCalendarPopup(True)
        widget.setDisplayFormat("yyyy-MM-dd")
        widget.dateChanged.connect(on_change)
    row.addWidget(QLabel("তারিখ:"))
    row.addWidget(start)
    row.addWidget(QLabel("থেকে"))
    row.addWidget(end)
    row.addStretch(1)
    return row, start, end


class SalesView(QWidget):
    """Invoice history with detail, reprint, cancellation and return."""

    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._query = ""
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("সেলস ও ইনভয়েস", "ইনভয়েস অনুসন্ধান, রিপ্রিন্ট, বাতিল ও রিটার্ন")
        header.add_action("ইনভয়েস বিস্তারিত", self._detail)
        header.add_action("রিসিট রিপ্রিন্ট", self._reprint, kind="Primary")
        header.add_action("PDF সংরক্ষণ", self._save_pdf)
        header.add_action("সেলস রিটার্ন", self._return, kind="Accent")
        header.add_action("ইনভয়েস বাতিল", self._cancel, kind="Danger")
        layout.addWidget(header)
        row, self.start, self.end = _date_range_row(self, lambda: self.refresh())
        self.search = SearchBox("ইনভয়েস নং বা কাস্টমার…")
        self.search.submitted.connect(self._on_search)
        row.addWidget(self.search, 2)
        layout.addLayout(row)

        splitter = QSplitter(Qt.Vertical)
        self.table = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("invoice_no", "ইনভয়েস নং", width=150),
                TableColumn("sale_date", "তারিখ", "date", 100),
                TableColumn("customer_name", "কাস্টমার", width=180),
                TableColumn("grand_total", "সর্বমোট", "money", 120),
                TableColumn("paid_amount", "পরিশোধিত", "money", 120),
                TableColumn("due_amount", "বাকি", "money", 110),
                TableColumn("status", "স্ট্যাটাস", width=130),
            ]
        )
        self.table.itemSelectionChanged.connect(self._load_items)
        splitter.addWidget(self.table)
        self.items = DataTable(
            [
                TableColumn("product_name", "প্রোডাক্ট", width=240),
                TableColumn("quantity", "পরিমাণ", "qty", 100),
                TableColumn("unit_price", "দর", "money", 110),
                TableColumn("discount_amount", "ডিস্কাউন্ট", "money", 110),
                TableColumn("net_amount", "নেট", "money", 120),
                TableColumn("returned_qty", "রিটার্ন হয়েছে", "qty", 120),
            ]
        )
        card = Card("ইনভয়েস আইটেম")
        card.add(self.items)
        splitter.addWidget(card)
        splitter.setSizes([340, 260])
        layout.addWidget(splitter, 1)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        layout.addWidget(self.summary)

    def refresh(self) -> None:
        result = guarded(
            self,
            lambda: self.services.sales.search(
                start=self.start.date().toString("yyyy-MM-dd"),
                end=self.end.date().toString("yyyy-MM-dd"),
                query=self._query,
                limit=300,
            ),
        )
        if result is None:
            return
        self.table.set_rows(result["rows"])
        total = sum(int(r["grand_total"]) for r in result["rows"])
        due = sum(int(r["due_amount"]) for r in result["rows"])
        self.summary.setText(
            f"{result['total']} ইনভয়েস  ·  মোট {format_money(total, symbol='৳ ')}  ·  "
            f"বাকি {format_money(due, symbol='৳ ')}"
        )
        self._load_items()

    def _on_search(self, text: str) -> None:
        self._query = text
        self.refresh()

    def _load_items(self) -> None:
        record = self.table.selected_record()
        if record is None:
            self.items.set_rows([])
            return
        sale = guarded(self, lambda: self.services.sales.get(record["id"]))
        if sale:
            self.items.set_rows(sale["items"])

    def _selected(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি ইনভয়েস নির্বাচন করুন")
        return record

    def _detail(self) -> None:
        record = self._selected()
        if record is None:
            return
        sale = self.services.sales.get(record["id"])
        lines = [
            f"ইনভয়েস: {sale['invoice_no']}",
            f"তারিখ: {sale['sale_date']} {sale['sale_time']}",
            f"কাস্টমার: {sale.get('customer_name') or 'ওয়াক-ইন'}",
            f"স্ট্যাটাস: {sale['status']}",
            "",
        ]
        for item in sale["items"]:
            lines.append(
                f"• {item['product_name']} — {format_quantity(item['quantity'])} × "
                f"{format_money(item['unit_price'])} = {format_money(item['net_amount'])}"
            )
        lines += [
            "",
            f"সাবটোটাল: {format_money(sale['subtotal'])}",
            f"ডিস্কাউন্ট: {format_money(sale['item_discount'] + sale['invoice_discount'])}",
            f"ট্যাক্স: {format_money(sale['tax_amount'])}",
            f"সর্বমোট: {format_money(sale['grand_total'])}",
            f"পরিশোধিত: {format_money(sale['paid_amount'])}",
            f"বাকি: {format_money(sale['due_amount'])}",
        ]
        show_info(self, "\n".join(lines), "ইনভয়েস বিস্তারিত")

    def _reprint(self) -> None:
        record = self._selected()
        if record is None:
            return
        settings = self.services.settings
        if not settings.get("printer_name"):
            show_error(self, "প্রথমে সেটিংস থেকে প্রিন্টার নির্বাচন করুন")
            return
        try:
            from ...printing.documents import print_html, receipt_html

            sale = self.services.sales.get(record["id"])
            print_html(
                receipt_html(sale, self.services.profile.get(), settings, copy_label="পুনরায় মুদ্রিত"),
                printer_name=settings.get("printer_name"),
                width_mm=float(settings.get("paper_width_mm", "80")),
                copies=1,
            )
            show_info(self, "রিসিট প্রিন্ট করা হয়েছে")
        except (RuntimeError, OSError, ImportError) as exc:
            show_error(self, f"প্রিন্ট করা যায়নি: {exc}")

    def _save_pdf(self) -> None:
        record = self._selected()
        if record is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "রিসিট PDF সংরক্ষণ", f"{record['invoice_no']}.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        saved = guarded(self, lambda: self.services.receipt_pdf(record["id"], path))
        if saved:
            show_info(self, f"PDF সংরক্ষিত:\n{saved}")

    def _cancel(self) -> None:
        record = self._selected()
        if record is None:
            return
        values = FormDialog.ask(
            "ইনভয়েস বাতিল",
            [
                FieldSpec("reason", "বাতিলের কারণ", "text", required=True),
            ],
            self,
        )
        if values is None:
            return
        if not confirm(self, "বাতিল করলে স্টক ও বাকি হিসাব ফেরত সমন্বয় হবে। নিশ্চিত?"):
            return
        if guarded(self, lambda: self.services.sales.cancel(record["id"], reason=values["reason"])):
            show_info(self, "ইনভয়েস বাতিল হয়েছে এবং হিসাব সমন্বয় করা হয়েছে")
        self.refresh()

    def _return(self) -> None:
        record = self._selected()
        if record is None:
            return
        items = self.services.sales_returns.returnable_items(record["id"])
        if not items:
            show_error(self, "এই ইনভয়েসে রিটার্নযোগ্য আইটেম নেই")
            return
        options = [
            (i["id"], f"{i['product_name']} (বাকি {format_quantity(i['returnable_qty'])})") for i in items
        ]
        methods = [(m["id"], m["name"]) for m in self.services.payment_methods.list()]
        values = FormDialog.ask(
            "সেলস রিটার্ন",
            [
                FieldSpec("item", "প্রোডাক্ট", "combo", required=True, options=options),
                FieldSpec("quantity", "রিটার্ন পরিমাণ", "qty", value=1000),
                FieldSpec(
                    "condition",
                    "পণ্যের অবস্থা",
                    "combo",
                    options=[
                        ("restock", "ভালো — স্টকে ফেরত"),
                        ("damaged", "নষ্ট"),
                        ("no_restock", "স্টকে ফেরত নয়"),
                    ],
                ),
                FieldSpec("reason", "রিটার্নের কারণ", "text", required=True),
                FieldSpec("refund", "নগদ রিফান্ড", "money", value=0, help="বাকি থাকলে প্রথমে বাকির সাথে সমন্বয় হবে"),
                FieldSpec("method", "রিফান্ড মেথড", "combo", options=methods),
                FieldSpec("date", "তারিখ", "date"),
            ],
            self,
        )
        if values is None:
            return
        result = guarded(
            self,
            lambda: self.services.sales_returns.create(
                sale_id=record["id"],
                lines=[
                    SalesReturnLine(values["item"], values["quantity"], values["condition"], values["reason"])
                ],
                reason=values["reason"],
                refund_amount=values["refund"],
                refund_method_id=values["method"] if values["refund"] else None,
                return_date=values["date"],
            ),
        )
        if result:
            show_info(
                self,
                f"রিটার্ন সম্পন্ন\nরিটার্ন নং: {result['return_no']}\n"
                f"মূল্য: {format_money(result['total_amount'], symbol='৳ ')}",
            )
        self.refresh()


class PurchasesView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._lines: list[PurchaseLineInput] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("পারচেজ ম্যানেজমেন্ট", "পারচেজ এন্ট্রি করলে স্টক স্বয়ংক্রিয়ভাবে বৃদ্ধি পায়")
        header.add_action("+ নতুন পারচেজ", self._create, kind="Primary")
        header.add_action("পারচেজ রিটার্ন", self._return, kind="Accent")
        header.add_action("পারচেজ বাতিল", self._cancel, kind="Danger")
        layout.addWidget(header)
        row, self.start, self.end = _date_range_row(self, lambda: self.refresh())
        layout.addLayout(row)
        splitter = QSplitter(Qt.Vertical)
        self.table = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("invoice_no", "পারচেজ নং", width=150),
                TableColumn("purchase_date", "তারিখ", "date", 100),
                TableColumn("supplier_name", "সাপ্লায়ার", width=200),
                TableColumn("grand_total", "সর্বমোট", "money", 120),
                TableColumn("paid_amount", "পরিশোধিত", "money", 120),
                TableColumn("due_amount", "বাকি", "money", 110),
                TableColumn("status", "স্ট্যাটাস", width=130),
            ]
        )
        self.table.itemSelectionChanged.connect(self._load_items)
        splitter.addWidget(self.table)
        self.items = DataTable(
            [
                TableColumn("product_name", "প্রোডাক্ট", width=240),
                TableColumn("quantity", "পরিমাণ", "qty", 110),
                TableColumn("unit_cost", "একক খরচ", "money", 120),
                TableColumn("net_amount", "নেট মূল্য", "money", 130),
                TableColumn("returned_qty", "রিটার্ন হয়েছে", "qty", 120),
            ]
        )
        card = Card("পারচেজ আইটেম")
        card.add(self.items)
        splitter.addWidget(card)
        splitter.setSizes([340, 260])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        result = guarded(
            self,
            lambda: self.services.purchases.search(
                start=self.start.date().toString("yyyy-MM-dd"),
                end=self.end.date().toString("yyyy-MM-dd"),
                limit=300,
            ),
        )
        if result:
            self.table.set_rows(result["rows"])
        self._load_items()

    def _load_items(self) -> None:
        record = self.table.selected_record()
        if record is None:
            self.items.set_rows([])
            return
        purchase = guarded(self, lambda: self.services.purchases.get(record["id"]))
        if purchase:
            self.items.set_rows(purchase["items"])

    def _selected(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি পারচেজ নির্বাচন করুন")
        return record

    def _create(self) -> None:
        suppliers = self.services.suppliers.search(limit=500)["rows"]
        if not suppliers:
            show_error(self, "আগে একজন সাপ্লায়ার যোগ করুন")
            return
        products = self.services.products.search(limit=1000)["rows"]
        if not products:
            show_error(self, "আগে প্রোডাক্ট যোগ করুন")
            return
        methods = [(m["id"], m["name"]) for m in self.services.payment_methods.list()]
        header = FormDialog.ask(
            "নতুন পারচেজ",
            [
                FieldSpec(
                    "supplier_id",
                    "সাপ্লায়ার",
                    "combo",
                    required=True,
                    options=[(s["id"], s["name"]) for s in suppliers],
                ),
                FieldSpec("date", "পারচেজের তারিখ", "date"),
                FieldSpec("supplier_invoice", "সাপ্লায়ার ইনভয়েস নং", "text"),
                FieldSpec("notes", "নোট", "textarea"),
            ],
            self,
        )
        if header is None:
            return
        lines: list[PurchaseLineInput] = []
        while True:
            values = FormDialog.ask(
                f"পারচেজ আইটেম ({len(lines) + 1})",
                [
                    FieldSpec(
                        "product_id",
                        "প্রোডাক্ট",
                        "combo",
                        required=True,
                        options=[(p["id"], f"{p['name']} · {p['sku']}") for p in products],
                    ),
                    FieldSpec("quantity", "পরিমাণ", "qty", value=1000),
                    FieldSpec("unit_cost", "একক পারচেজ মূল্য", "money", value=0),
                    FieldSpec("discount", "লাইন ডিস্কাউন্ট", "money", value=0),
                ],
                self,
            )
            if values is None:
                break
            lines.append(
                PurchaseLineInput(
                    values["product_id"], values["quantity"], values["unit_cost"], values["discount"]
                )
            )
            if not confirm(self, "আরও আইটেম যোগ করবেন?"):
                break
        if not lines:
            show_error(self, "কোনো আইটেম যোগ করা হয়নি")
            return
        total = sum((line.unit_cost * line.quantity) // 1000 - line.discount_amount for line in lines)
        payment = FormDialog.ask(
            "পারচেজ পেমেন্ট",
            [
                FieldSpec("total", "মোট মূল্য", "readonly", value=format_money(total)),
                FieldSpec("paid", "পরিশোধিত", "money", value=total),
                FieldSpec("method_id", "পেমেন্ট মেথড", "combo", required=True, options=methods),
            ],
            self,
        )
        if payment is None:
            return
        payments = [PaymentInput(payment["method_id"], payment["paid"])] if payment["paid"] > 0 else []
        result = guarded(
            self,
            lambda: self.services.purchases.create(
                PurchaseInput(
                    supplier_id=header["supplier_id"],
                    lines=lines,
                    payments=payments,
                    purchase_date=header["date"],
                    supplier_invoice_no=header["supplier_invoice"],
                    notes=header["notes"],
                )
            ),
        )
        if result:
            show_info(
                self,
                f"পারচেজ সম্পন্ন\nনং: {result['invoice_no']}\n"
                f"মোট: {format_money(result['grand_total'], symbol='৳ ')}",
            )
        self.refresh()

    def _cancel(self) -> None:
        record = self._selected()
        if record is None:
            return
        values = FormDialog.ask("পারচেজ বাতিল", [FieldSpec("reason", "কারণ", "text", required=True)], self)
        if values and confirm(self, "স্টক ও দেয় হিসাব ফেরত সমন্বয় হবে। নিশ্চিত?"):
            guarded(self, lambda: self.services.purchases.cancel(record["id"], reason=values["reason"]))
        self.refresh()

    def _return(self) -> None:
        record = self._selected()
        if record is None:
            return
        items = self.services.purchase_returns.returnable_items(record["id"])
        if not items:
            show_error(self, "রিটার্নযোগ্য আইটেম নেই")
            return
        methods = [(m["id"], m["name"]) for m in self.services.payment_methods.list()]
        values = FormDialog.ask(
            "পারচেজ রিটার্ন",
            [
                FieldSpec(
                    "item",
                    "প্রোডাক্ট",
                    "combo",
                    required=True,
                    options=[
                        (i["id"], f"{i['product_name']} (বাকি {format_quantity(i['returnable_qty'])})")
                        for i in items
                    ],
                ),
                FieldSpec("quantity", "রিটার্ন পরিমাণ", "qty", value=1000),
                FieldSpec("reason", "কারণ", "text", required=True),
                FieldSpec("refund", "নগদ ফেরত", "money", value=0),
                FieldSpec("method", "রিফান্ড মেথড", "combo", options=methods),
                FieldSpec("date", "তারিখ", "date"),
            ],
            self,
        )
        if values is None:
            return
        result = guarded(
            self,
            lambda: self.services.purchase_returns.create(
                purchase_id=record["id"],
                lines=[PurchaseReturnLine(values["item"], values["quantity"], values["reason"])],
                reason=values["reason"],
                refund_amount=values["refund"],
                refund_method_id=values["method"] if values["refund"] else None,
                return_date=values["date"],
            ),
        )
        if result:
            show_info(self, f"রিটার্ন সম্পন্ন: {result['return_no']}")
        self.refresh()


class ReturnsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.addWidget(PageHeader("রিটার্ন হিস্ট্রি", "সেলস ও পারচেজ রিটার্নের সম্পূর্ণ রেকর্ড"))
        row, self.start, self.end = _date_range_row(self, lambda: self.refresh())
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.sales_returns = DataTable(
            [
                TableColumn("return_no", "রিটার্ন নং", width=140),
                TableColumn("return_date", "তারিখ", "date", 100),
                TableColumn("invoice_no", "ইনভয়েস", width=140),
                TableColumn("customer_name", "কাস্টমার", width=170),
                TableColumn("total_amount", "রিটার্ন মূল্য", "money", 120),
                TableColumn("refund_amount", "রিফান্ড", "money", 110),
                TableColumn("due_adjusted", "বাকি সমন্বয়", "money", 120),
                TableColumn("reason", "কারণ", width=200),
            ]
        )
        self.purchase_returns = DataTable(
            [
                TableColumn("return_no", "রিটার্ন নং", width=140),
                TableColumn("return_date", "তারিখ", "date", 100),
                TableColumn("invoice_no", "পারচেজ নং", width=140),
                TableColumn("supplier_name", "সাপ্লায়ার", width=180),
                TableColumn("total_amount", "রিটার্ন মূল্য", "money", 130),
                TableColumn("refund_amount", "রিফান্ড", "money", 110),
                TableColumn("reason", "কারণ", width=200),
            ]
        )
        self.tabs.addTab(self.sales_returns, "সেলস রিটার্ন")
        self.tabs.addTab(self.purchase_returns, "পারচেজ রিটার্ন")
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        start = self.start.date().toString("yyyy-MM-dd")
        end = self.end.date().toString("yyyy-MM-dd")
        sales = guarded(self, lambda: self.services.sales_returns.search(start=start, end=end, limit=300))
        if sales:
            self.sales_returns.set_rows(sales["rows"])
        purchases = guarded(
            self, lambda: self.services.purchase_returns.search(start=start, end=end, limit=300)
        )
        if purchases:
            self.purchase_returns.set_rows(purchases["rows"])
