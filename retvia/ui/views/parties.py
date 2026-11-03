"""Customer and supplier management with ledgers, statements and payments."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ...services.parties import CustomerInput, SupplierInput
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    KpiCard,
    PageHeader,
    SearchBox,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)

LEDGER_COLUMNS = [
    TableColumn("date", "তারিখ", "date", 100),
    TableColumn("particulars", "বিবরণ", width=280),
    TableColumn("reference", "রেফারেন্স", width=130),
    TableColumn("debit", "ডেবিট", "money", 110),
    TableColumn("credit", "ক্রেডিট", "money", 110),
    TableColumn("balance", "ব্যালেন্স", "money", 120),
]


class _PartyTab(QWidget):
    def __init__(self, services, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.kind = kind  # customer | supplier
        self.is_customer = kind == "customer"
        self._query = ""
        self._build()
        self.refresh()

    @property
    def service(self):
        return self.services.customers if self.is_customer else self.services.suppliers

    @property
    def payments(self):
        return self.services.customer_payments if self.is_customer else self.services.supplier_payments

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACE["md"], 0, 0)
        title = "কাস্টমার ম্যানেজমেন্ট" if self.is_customer else "সাপ্লায়ার ম্যানেজমেন্ট"
        subtitle = (
            "কাস্টমার প্রোফাইল, বাকি, লেজার ও কালেকশন" if self.is_customer else "সাপ্লায়ার প্রোফাইল, দেয়, লেজার ও পেমেন্ট"
        )
        header = PageHeader(title, subtitle)
        header.add_action("+ নতুন", self._create, kind="Primary")
        header.add_action("সম্পাদনা", self._edit)
        header.add_action("পেমেন্ট", self._payment, kind="Accent")
        header.add_action("লেজার দেখুন", self._show_ledger)
        header.add_action("আর্কাইভ / সক্রিয়", self._toggle)
        header.add_action("মুছে ফেলুন", self._delete, kind="Danger")
        layout.addWidget(header)

        self.search = SearchBox("নাম বা মোবাইল দিয়ে খুঁজুন…")
        self.search.submitted.connect(self._on_search)
        layout.addWidget(self.search)

        kpis = QHBoxLayout()
        self.total_party = KpiCard("মোট " + ("কাস্টমার" if self.is_customer else "সাপ্লায়ার"), "০")
        self.total_balance = KpiCard("মোট বাকি" if self.is_customer else "মোট দেয়", "—", tone="danger")
        self.selected_balance = KpiCard("নির্বাচিত ব্যালেন্স", "—")
        for card in (self.total_party, self.total_balance, self.selected_balance):
            kpis.addWidget(card)
        layout.addLayout(kpis)

        splitter = QSplitter(Qt.Vertical)
        self.table = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("name", "নাম", width=200),
                TableColumn("phone", "মোবাইল", width=130),
                TableColumn("address", "ঠিকানা", width=220),
                TableColumn("opening_due" if self.is_customer else "opening_payable", "ওপেনিং", "money", 110),
                TableColumn(
                    "current_due" if self.is_customer else "current_payable",
                    "বর্তমান বাকি" if self.is_customer else "বর্তমান দেয়",
                    "money",
                    130,
                ),
                TableColumn("status", "স্ট্যাটাস", width=90),
            ]
        )
        self.table.itemSelectionChanged.connect(self._show_ledger)
        splitter.addWidget(self.table)

        ledger_card = Card("লেজার ও স্টেটমেন্ট")
        self.ledger_table = DataTable(LEDGER_COLUMNS)
        ledger_card.add(self.ledger_table)
        self.ledger_summary = QLabel("")
        self.ledger_summary.setObjectName("Muted")
        ledger_card.add(self.ledger_summary)
        splitter.addWidget(ledger_card)
        splitter.setSizes([320, 300])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        result = self.service.search(query=self._query, status="all", limit=500)
        self.table.set_rows(result["rows"])
        self.total_party.set_value(str(result["total"]))
        key = "current_due" if self.is_customer else "current_payable"
        total = sum(max(0, int(r[key])) for r in result["rows"])
        self.total_balance.set_value(format_money(total, symbol="৳ "))
        self._show_ledger()

    def _on_search(self, text: str) -> None:
        self._query = text
        self.refresh()

    def _selected(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি সারি নির্বাচন করুন")
        return record

    def _show_ledger(self) -> None:
        record = self.table.selected_record()
        if record is None:
            self.ledger_table.set_rows([])
            self.ledger_summary.setText("লেজার দেখতে একটি সারি নির্বাচন করুন")
            self.selected_balance.set_value("—")
            return
        ledger = guarded(self, lambda: self.service.ledger(record["id"]))
        if ledger is None:
            return
        self.ledger_table.set_rows(ledger["entries"])
        self.ledger_summary.setText(
            f"ওপেনিং: {format_money(ledger['opening_balance'])}  ·  "
            f"মোট ডেবিট: {format_money(ledger['total_debit'])}  ·  "
            f"মোট ক্রেডিট: {format_money(ledger['total_credit'])}  ·  "
            f"ক্লোজিং: {format_money(ledger['closing_balance'])}"
        )
        key = "current_due" if self.is_customer else "current_payable"
        self.selected_balance.set_value(format_money(int(record[key]), symbol="৳ "))

    # ------------------------------------------------------------------ CRUD
    def _fields(self, existing: dict[str, Any] | None = None) -> list[FieldSpec]:
        e = existing or {}
        fields = [
            FieldSpec("name", "নাম", "text", required=True, value=e.get("name", "")),
            FieldSpec("phone", "মোবাইল নম্বর", "text", value=e.get("phone", "")),
            FieldSpec("address", "ঠিকানা", "textarea", value=e.get("address", "")),
            FieldSpec("email", "ইমেইল", "text", value=e.get("email", "")),
        ]
        if not self.is_customer:
            fields.insert(
                1, FieldSpec("business_name", "প্রতিষ্ঠানের নাম", "text", value=e.get("business_name", ""))
            )
            fields.insert(
                2, FieldSpec("contact_person", "যোগাযোগকারী", "text", value=e.get("contact_person", ""))
            )
        if existing is None:
            fields.append(
                FieldSpec(
                    "opening",
                    "ওপেনিং বাকি" if self.is_customer else "ওপেনিং দেয়",
                    "money",
                    value=0,
                    help="পূর্বের হিসাব থাকলে এখানে লিখুন",
                )
            )
        fields.append(FieldSpec("notes", "নোট", "textarea", value=e.get("notes", "")))
        return fields

    def _create(self) -> None:
        values = FormDialog.ask("নতুন এন্ট্রি", self._fields(), self)
        if values is None:
            return
        if self.is_customer:
            data = CustomerInput(
                name=values["name"],
                phone=values["phone"],
                address=values["address"],
                email=values["email"],
                opening_due=values["opening"],
                notes=values["notes"],
            )
        else:
            data = SupplierInput(
                name=values["name"],
                business_name=values["business_name"],
                contact_person=values["contact_person"],
                phone=values["phone"],
                address=values["address"],
                email=values["email"],
                opening_payable=values["opening"],
                notes=values["notes"],
            )
        if guarded(self, lambda: self.service.create(data)):
            show_info(self, "সফলভাবে যোগ হয়েছে")
        self.refresh()

    def _edit(self) -> None:
        record = self._selected()
        if record is None:
            return
        values = FormDialog.ask("সম্পাদনা", self._fields(record), self)
        if values is None:
            return
        if self.is_customer:
            data = CustomerInput(
                name=values["name"],
                phone=values["phone"],
                address=values["address"],
                email=values["email"],
                notes=values["notes"],
            )
        else:
            data = SupplierInput(
                name=values["name"],
                business_name=values["business_name"],
                contact_person=values["contact_person"],
                phone=values["phone"],
                address=values["address"],
                email=values["email"],
                notes=values["notes"],
            )
        guarded(self, lambda: self.service.update(record["id"], data) or True)
        self.refresh()

    def _toggle(self) -> None:
        record = self._selected()
        if record is None:
            return
        new_status = "archived" if record["status"] == "active" else "active"
        guarded(self, lambda: self.service.set_status(record["id"], new_status) or True)
        self.refresh()

    def _delete(self) -> None:
        record = self._selected()
        if record is None or not confirm(self, f"'{record['name']}' মুছে ফেলবেন?"):
            return
        guarded(self, lambda: self.service.delete(record["id"]) or True)
        self.refresh()

    # --------------------------------------------------------------- payment
    def _payment(self) -> None:
        record = self._selected()
        if record is None:
            return
        methods = [(m["id"], m["name"]) for m in self.services.payment_methods.list()]
        documents: list[tuple[Any, str]] = [(None, "— নির্দিষ্ট ডকুমেন্ট নেই —")]
        if self.is_customer:
            for inv in self.payments.due_invoices(record["id"]):
                documents.append((inv["id"], f"{inv['invoice_no']} · বাকি {format_money(inv['outstanding'])}"))
        else:
            for inv in self.payments.due_purchases(record["id"]):
                documents.append((inv["id"], f"{inv['invoice_no']} · বাকি {format_money(inv['outstanding'])}"))
        key = "current_due" if self.is_customer else "current_payable"
        values = FormDialog.ask(
            "কালেকশন" if self.is_customer else "সাপ্লায়ার পেমেন্ট",
            [
                FieldSpec("party", "নাম", "readonly", value=record["name"]),
                FieldSpec("balance", "বর্তমান ব্যালেন্স", "readonly", value=format_money(int(record[key]))),
                FieldSpec("amount", "পরিমাণ", "money", required=True, value=0),
                FieldSpec("method_id", "পেমেন্ট মেথড", "combo", required=True, options=methods),
                FieldSpec("document", "ইনভয়েস / পারচেজ", "combo", options=documents),
                FieldSpec("date", "তারিখ", "date"),
                FieldSpec("reference", "রেফারেন্স", "text"),
                FieldSpec("notes", "নোট", "textarea"),
            ],
            self,
        )
        if values is None or values["amount"] <= 0:
            return
        if self.is_customer:
            result = guarded(
                self,
                lambda: self.payments.collect(
                    customer_id=record["id"],
                    amount=values["amount"],
                    method_id=values["method_id"],
                    sale_id=values["document"],
                    payment_date=values["date"],
                    reference=values["reference"],
                    notes=values["notes"],
                ),
            )
        else:
            result = guarded(
                self,
                lambda: self.payments.pay(
                    supplier_id=record["id"],
                    amount=values["amount"],
                    method_id=values["method_id"],
                    purchase_id=values["document"],
                    payment_date=values["date"],
                    reference=values["reference"],
                    notes=values["notes"],
                ),
            )
        if result:
            show_info(self, f"পেমেন্ট সম্পন্ন\nরিসিট নং: {result['receipt_no']}")
            self._print_payment_receipt(result)
        self.refresh()

    def _print_payment_receipt(self, result: dict[str, Any]) -> None:
        settings = self.services.settings
        if not settings.get("printer_name"):
            return
        try:
            from ...printing.documents import print_html

            profile = self.services.profile.get()
            html_text = f"""<html><head><meta charset="utf-8"><style>
              body {{ font-family:'Noto Sans Bengali'; font-size:10pt; }}
              .c {{ text-align:center; }} .b {{ font-weight:700; font-size:13pt; }}
              </style></head><body>
              <div class="c b">{profile.name}</div>
              <div class="c">{profile.address}</div>
              <div class="c">পেমেন্ট রিসিট</div><hr>
              <p>রিসিট নং: {result["receipt_no"]}</p>
              <p>পরিমাণ: {format_money(result["amount"], symbol="৳ ")}</p>
              <hr><div class="c">{profile.receipt_footer or "ধন্যবাদ"}</div>
              </body></html>"""
            print_html(
                html_text,
                printer_name=settings.get("printer_name"),
                width_mm=float(settings.get("paper_width_mm", "80")),
            )
        except (RuntimeError, OSError, ImportError) as exc:
            show_error(self, f"রিসিট প্রিন্ট করা যায়নি: {exc}")


class PartiesView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        self.tabs = QTabWidget()
        self.customers = _PartyTab(services, "customer")
        self.suppliers = _PartyTab(services, "supplier")
        self.tabs.addTab(self.customers, "কাস্টমার")
        self.tabs.addTab(self.suppliers, "সাপ্লায়ার")
        layout.addWidget(self.tabs)

    def refresh(self) -> None:
        self.customers.refresh()
        self.suppliers.refresh()
