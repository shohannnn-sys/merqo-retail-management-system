"""POS — fast, keyboard-first checkout with barcode scanning and split payments."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import BusinessRuleError, RetviaError
from ...core.money import format_money
from ...core.quantity import format_quantity, parse_quantity
from ...services.parties import CustomerInput
from ...services.sales import PaymentInput, SaleInput, SaleLineInput
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    MoneyEdit,
    PageHeader,
    QuantityEdit,
    SearchBox,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)


class PaymentDialog(QDialog):
    """Collect one or more payment lines (split payment)."""

    def __init__(self, total: int, methods: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("পেমেন্ট গ্রহণ")
        self.setMinimumWidth(480)
        self._total = total
        self._methods = methods
        self._lines: list[tuple[QComboBox, MoneyEdit]] = []
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])
        due_label = QLabel(f"পরিশোধযোগ্য: {format_money(total, symbol='৳ ')}")
        due_label.setObjectName("SectionTitle")
        layout.addWidget(due_label)
        self._rows_layout = QVBoxLayout()
        layout.addLayout(self._rows_layout)
        add = QPushButton("+ আরও পেমেন্ট মেথড যোগ করুন")
        add.clicked.connect(lambda: self._add_row())
        layout.addWidget(add)
        self._summary = QLabel("")
        self._summary.setObjectName("FieldError")
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("নিশ্চিত করুন")
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Cancel).setText("বাতিল")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._add_row(total)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._accept)

    def _add_row(self, amount: int | None = None) -> None:
        row = QHBoxLayout()
        combo = QComboBox()
        for method in self._methods:
            combo.addItem(method["name"], method["id"])
        remaining = self._total - sum(edit.poisha() for _, edit in self._lines)
        edit = MoneyEdit(amount if amount is not None else max(0, remaining))
        remove = QPushButton("✕")
        remove.setFixedWidth(34)
        remove.clicked.connect(lambda: self._remove_row(row, combo, edit))
        row.addWidget(combo, 2)
        row.addWidget(edit, 1)
        row.addWidget(remove)
        self._rows_layout.addLayout(row)
        self._lines.append((combo, edit))
        edit.textChanged.connect(self._update_summary)
        self._update_summary()

    def _remove_row(self, row, combo, edit) -> None:
        if len(self._lines) <= 1:
            return
        self._lines = [(c, e) for c, e in self._lines if e is not edit]
        for i in reversed(range(row.count())):
            widget = row.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self._rows_layout.removeItem(row)
        self._update_summary()

    def _update_summary(self) -> None:
        paid = sum(edit.poisha() for _, edit in self._lines)
        diff = self._total - paid
        if diff > 0:
            self._summary.setText(f"বাকি থাকবে: {format_money(diff, symbol='৳ ')}")
        elif diff < 0:
            self._summary.setText(f"ইনভয়েসের চেয়ে বেশি: {format_money(-diff, symbol='৳ ')}")
        else:
            self._summary.setText("সম্পূর্ণ পরিশোধিত")

    def _accept(self) -> None:
        paid = sum(edit.poisha() for _, edit in self._lines)
        if paid > self._total:
            self._summary.setText("পরিশোধিত টাকা ইনভয়েস মোটের চেয়ে বেশি হতে পারে না")
            return
        self.accept()

    def payments(self) -> list[PaymentInput]:
        return [
            PaymentInput(method_id=int(combo.currentData()), amount=edit.poisha())
            for combo, edit in self._lines
            if edit.poisha() > 0
        ]


class PosView(QWidget):
    sale_completed = Signal(dict)

    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._cart: list[dict[str, Any]] = []
        self._customer_id: int | None = None
        self._build()
        self._shortcuts()
        self.refresh_methods()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("পিওএস — সেলস", "বারকোড স্ক্যান করুন বা প্রোডাক্ট খুঁজুন · F2 সার্চ · F8 সেভ · Esc কার্ট খালি")
        outer.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- left: search + results
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, SPACE["md"], 0)
        self.search = SearchBox("বারকোড স্ক্যান বা নাম / এসকেইউ লিখুন…")
        self.search.submitted.connect(self._on_search)
        left_layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._add_from_result)
        self.results.itemActivated.connect(self._add_from_result)
        left_layout.addWidget(self.results, 1)
        hint = QLabel("ডাবল-ক্লিক বা Enter দিয়ে কার্টে যোগ করুন")
        hint.setObjectName("HelpText")
        left_layout.addWidget(hint)
        splitter.addWidget(left)

        # ---- middle: cart
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, SPACE["md"], 0)
        self.cart_table = DataTable(
            [
                TableColumn("name", "প্রোডাক্ট"),
                TableColumn("qty_text", "পরিমাণ", "text", align="right"),
                TableColumn("unit_price", "দর", "money"),
                TableColumn("discount_text", "ডিস্কাউন্ট", "text", align="right"),
                TableColumn("line_total", "মোট", "money"),
            ]
        )
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        middle_layout.addWidget(self.cart_table, 1)

        controls = QHBoxLayout()
        self.qty_edit = QuantityEdit(1000)
        self.qty_edit.setFixedWidth(90)
        plus = QPushButton("+ পরিমাণ")
        minus = QPushButton("− পরিমাণ")
        set_qty = QPushButton("পরিমাণ সেট")
        discount = QPushButton("আইটেম ডিস্কাউন্ট")
        remove = QPushButton("আইটেম বাদ")
        remove.setObjectName("Danger")
        plus.clicked.connect(lambda: self._change_qty(1))
        minus.clicked.connect(lambda: self._change_qty(-1))
        set_qty.clicked.connect(self._set_qty)
        discount.clicked.connect(self._item_discount)
        remove.clicked.connect(self._remove_item)
        for widget in (QLabel("পরিমাণ:"), self.qty_edit, plus, minus, set_qty, discount, remove):
            controls.addWidget(widget)
        controls.addStretch(1)
        middle_layout.addLayout(controls)
        splitter.addWidget(middle)

        # ---- right: totals + checkout
        right = QWidget()
        right.setMaximumWidth(340)
        right.setMinimumWidth(300)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(SPACE["md"])

        customer_card = Card("কাস্টমার")
        customer_row = QHBoxLayout()
        self.customer_combo = QComboBox()
        self.customer_combo.setMinimumWidth(160)
        new_customer = QPushButton("+ নতুন")
        new_customer.clicked.connect(self._new_customer)
        customer_row.addWidget(self.customer_combo, 1)
        customer_row.addWidget(new_customer)
        customer_card.add_layout(customer_row)
        right_layout.addWidget(customer_card)

        discount_card = Card("ইনভয়েস ডিস্কাউন্ট")
        discount_row = QHBoxLayout()
        self.discount_type = QComboBox()
        self.discount_type.addItem("নেই", "none")
        self.discount_type.addItem("শতকরা %", "percent")
        self.discount_type.addItem("নির্দিষ্ট টাকা", "fixed")
        self.discount_value = MoneyEdit(0)
        self.discount_type.currentIndexChanged.connect(self._recalculate)
        self.discount_value.textChanged.connect(self._recalculate)
        discount_row.addWidget(self.discount_type, 1)
        discount_row.addWidget(self.discount_value, 1)
        discount_card.add_layout(discount_row)
        right_layout.addWidget(discount_card)

        totals_card = Card("হিসাব")
        self.total_labels: dict[str, QLabel] = {}
        for key, label in (
            ("subtotal", "সাবটোটাল"),
            ("item_discount", "আইটেম ডিস্কাউন্ট"),
            ("invoice_discount", "ইনভয়েস ডিস্কাউন্ট"),
            ("tax", "ট্যাক্স"),
            ("grand_total", "সর্বমোট"),
        ):
            row = QHBoxLayout()
            name = QLabel(label)
            value = QLabel("০.০০")
            value.setAlignment(Qt.AlignRight)
            if key == "grand_total":
                name.setObjectName("SectionTitle")
                value.setObjectName("KpiValueAccent")
            row.addWidget(name)
            row.addWidget(value)
            totals_card.add_layout(row)
            self.total_labels[key] = value
        right_layout.addWidget(totals_card)

        self.checkout = QPushButton("সেলস সম্পন্ন করুন  (F8)")
        self.checkout.setObjectName("BigAction")
        self.checkout.clicked.connect(self._checkout)
        right_layout.addWidget(self.checkout)
        clear = QPushButton("কার্ট খালি করুন  (Esc)")
        clear.clicked.connect(self._clear_cart)
        right_layout.addWidget(clear)
        self.session_label = QLabel("")
        self.session_label.setObjectName("HelpText")
        self.session_label.setWordWrap(True)
        right_layout.addWidget(self.session_label)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([280, 560, 330])
        self.reload_customers()
        self._refresh_session_label()

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("F2"), self, activated=lambda: self.search.setFocus())
        QShortcut(QKeySequence("F8"), self, activated=self._checkout)
        QShortcut(QKeySequence("F4"), self, activated=self._new_customer)
        QShortcut(QKeySequence("Esc"), self, activated=self._clear_cart)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search.setFocus())

    # ------------------------------------------------------------------ data
    def refresh_methods(self) -> None:
        self._methods = self.services.payment_methods.list()

    def reload_customers(self) -> None:
        self.customer_combo.clear()
        self.customer_combo.addItem("ওয়াক-ইন কাস্টমার", None)
        for row in self.services.customers.search(limit=500)["rows"]:
            self.customer_combo.addItem(f"{row['name']} ({row['phone'] or '—'})", row["id"])

    def _refresh_session_label(self) -> None:
        session = self.services.cash.current_session()
        if session:
            self.session_label.setText(
                f"ক্যাশ শিফট খোলা · প্রত্যাশিত ক্যাশ "
                f"{format_money(self.services.cash.expected_cash(session['id']), symbol='৳ ')}"
            )
        else:
            self.session_label.setText("ক্যাশ শিফট বন্ধ — ক্যাশ নিতে হলে আগে শিফট খুলুন")

    # ---------------------------------------------------------------- search
    def _on_search(self, text: str) -> None:
        text = text.strip()
        self.results.clear()
        if not text:
            return
        # A scanner delivers a full code very fast; try an exact barcode hit first.
        product = self.services.barcodes.lookup(text)
        if product is not None:
            self._add_product(product)
            self.search.clear()
            return
        for row in self.services.products.quick_search(text, limit=25):
            label = (
                f"{row['name']}  ·  {row['sku']}  ·  "
                f"{format_money(row['selling_price'], symbol='৳ ')}  ·  "
                f"মজুদ {format_quantity(row['stock_qty'])}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, row)
            self.results.addItem(item)

    def _add_from_result(self, item: QListWidgetItem) -> None:
        product = item.data(Qt.UserRole)
        if product:
            self._add_product(product)
            self.search.clear()
            self.results.clear()
            self.search.setFocus()

    def _add_product(self, product: dict[str, Any]) -> None:
        for line in self._cart:
            if line["product_id"] == product["id"]:
                line["quantity"] += 1000
                self._recalculate()
                return
        self._cart.append(
            {
                "product_id": int(product["id"]),
                "name": product["name"],
                "unit_name": product.get("unit_name", ""),
                "quantity": 1000,
                "unit_price": int(product["selling_price"]),
                "discount_type": "none",
                "discount_value": 0,
                "precision": int(product.get("decimal_precision", 3)),
            }
        )
        self._recalculate()

    # ------------------------------------------------------------------ cart
    def _selected_index(self) -> int | None:
        row = self.cart_table.currentRow()
        if row < 0:
            return None
        record = self.cart_table.selected_record()
        if record is None:
            return None
        for index, line in enumerate(self._cart):
            if line["product_id"] == record.get("product_id"):
                return index
        return None

    def _change_qty(self, direction: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        step = parse_quantity(self.qty_edit.text()) or 1000
        line = self._cart[index]
        line["quantity"] = max(0, line["quantity"] + direction * step)
        if line["quantity"] == 0:
            self._cart.pop(index)
        self._recalculate()

    def _set_qty(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        line = self._cart[index]
        values = FormDialog.ask(
            "পরিমাণ নির্ধারণ",
            [FieldSpec("quantity", "পরিমাণ", "qty", value=line["quantity"], precision=line["precision"])],
            self,
        )
        if values and values["quantity"] > 0:
            line["quantity"] = values["quantity"]
            self._recalculate()

    def _item_discount(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        line = self._cart[index]
        values = FormDialog.ask(
            "আইটেম ডিস্কাউন্ট",
            [
                FieldSpec(
                    "kind",
                    "ডিস্কাউন্টের ধরন",
                    "combo",
                    value=line["discount_type"],
                    options=[("none", "নেই"), ("percent", "শতকরা %"), ("fixed", "নির্দিষ্ট টাকা")],
                ),
                FieldSpec(
                    "value",
                    "পরিমাণ",
                    "money",
                    value=line["discount_value"],
                    help="শতকরা হলে টাকার ঘরে ১০ লিখলে ১০% ধরা হবে",
                ),
            ],
            self,
        )
        if values is None:
            return
        line["discount_type"] = values["kind"]
        # 10.00 parses to 1000 poisha, which is exactly 1000 basis points (10%).
        line["discount_value"] = values["value"]
        self._recalculate()

    def _remove_item(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self._cart.pop(index)
        self._recalculate()

    def _clear_cart(self) -> None:
        if not self._cart:
            return
        if confirm(self, "কার্টের সব আইটেম বাদ দেবেন?"):
            self._cart.clear()
            self._recalculate()

    def _new_customer(self) -> None:
        values = FormDialog.ask(
            "নতুন কাস্টমার",
            [
                FieldSpec("name", "কাস্টমারের নাম", "text", required=True),
                FieldSpec("phone", "মোবাইল নম্বর", "text"),
                FieldSpec("address", "ঠিকানা", "textarea"),
            ],
            self,
        )
        if values is None:
            return
        new_id = guarded(
            self,
            lambda: self.services.customers.create(
                CustomerInput(name=values["name"], phone=values["phone"], address=values["address"])
            ),
        )
        if new_id:
            self.reload_customers()
            index = self.customer_combo.findData(new_id)
            if index >= 0:
                self.customer_combo.setCurrentIndex(index)

    # ------------------------------------------------------------- calculate
    def _sale_input(self, payments: list[PaymentInput] | None = None) -> SaleInput:
        kind = self.discount_type.currentData()
        raw = self.discount_value.poisha()
        value = raw  # poisha == basis points for a percentage entry
        return SaleInput(
            lines=[
                SaleLineInput(
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                    discount_type=line["discount_type"],
                    discount_value=line["discount_value"],
                )
                for line in self._cart
            ],
            payments=payments or [],
            customer_id=self.customer_combo.currentData(),
            invoice_discount_type=kind,
            invoice_discount_value=value if kind != "none" else 0,
        )

    def _recalculate(self) -> None:
        rows = []
        totals = None
        if self._cart:
            try:
                totals = self.services.sales.preview(self._sale_input())
            except RetviaError as exc:
                self.total_labels["grand_total"].setText("—")
                self.checkout.setEnabled(False)
                self.session_label.setText(str(exc))
                self._render_cart(rows)
                return
        for index, line in enumerate(self._cart):
            computed = totals.lines[index] if totals else None
            discount_text = "—"
            if line["discount_type"] == "percent":
                discount_text = f"{line['discount_value'] / 100:.2f}%"
            elif line["discount_type"] == "fixed":
                discount_text = format_money(line["discount_value"])
            rows.append(
                {
                    "product_id": line["product_id"],
                    "name": line["name"],
                    "qty_text": f"{format_quantity(line['quantity'])} {line['unit_name']}",
                    "unit_price": line["unit_price"],
                    "discount_text": discount_text,
                    "line_total": computed.net_amount if computed else 0,
                }
            )
        self._render_cart(rows)
        symbol = self.services.settings.get("currency_symbol", "৳")
        if totals:
            self.total_labels["subtotal"].setText(format_money(totals.subtotal, symbol=symbol))
            self.total_labels["item_discount"].setText(format_money(totals.item_discount, symbol=symbol))
            self.total_labels["invoice_discount"].setText(
                format_money(totals.invoice_discount, symbol=symbol)
            )
            self.total_labels["tax"].setText(format_money(totals.tax_amount, symbol=symbol))
            self.total_labels["grand_total"].setText(format_money(totals.grand_total, symbol=symbol))
        else:
            for label in self.total_labels.values():
                label.setText(format_money(0, symbol=symbol))
        self.checkout.setEnabled(bool(self._cart))

    def _render_cart(self, rows: list[dict[str, Any]]) -> None:
        self.cart_table.set_rows(rows)

    # -------------------------------------------------------------- checkout
    def _checkout(self) -> None:
        if not self._cart:
            return
        try:
            totals = self.services.sales.preview(self._sale_input())
        except RetviaError as exc:
            show_error(self, exc)
            return
        self.refresh_methods()
        dialog = PaymentDialog(totals.grand_total, self._methods, self)
        if dialog.exec() != QDialog.Accepted:
            return
        payments = dialog.payments()
        data = self._sale_input(payments)
        try:
            result = self.services.sales.create(data)
        except BusinessRuleError as exc:
            if "শিফট" in str(exc):
                if confirm(self, f"{exc}\n\nএখনই ক্যাশ শিফট খুলবেন?"):
                    self._open_shift_and_retry(data)
                return
            show_error(self, exc)
            return
        except RetviaError as exc:
            show_error(self, exc)
            return
        self._after_sale(result)

    def _open_shift_and_retry(self, data: SaleInput) -> None:
        values = FormDialog.ask(
            "ক্যাশ শিফট খুলুন",
            [FieldSpec("opening_cash", "ওপেনিং ক্যাশ", "money", value=0)],
            self,
        )
        if values is None:
            return
        opened = guarded(self, lambda: self.services.cash.open_session(opening_cash=values["opening_cash"]))
        if not opened:
            return
        result = guarded(self, lambda: self.services.sales.create(data))
        if result:
            self._after_sale(result)

    def _after_sale(self, result: dict[str, Any]) -> None:
        self._cart.clear()
        self.discount_type.setCurrentIndex(0)
        self.discount_value.set_poisha(0)
        self._recalculate()
        self._refresh_session_label()
        self.sale_completed.emit(result)
        printed = self._print_receipt(result["id"])
        message = (
            f"ইনভয়েস: {result['invoice_no']}\n"
            f"সর্বমোট: {format_money(result['grand_total'], symbol='৳ ')}\n"
            f"বাকি: {format_money(result['due_amount'], symbol='৳ ')}"
        )
        if printed:
            message += "\n\nরিসিট প্রিন্ট করা হয়েছে।"
        show_info(self, message, "সেলস সম্পন্ন")
        self.search.setFocus()

    def _print_receipt(self, sale_id: int) -> bool:
        settings = self.services.settings
        if not settings.get("printer_name"):
            return False
        try:
            from ...printing.documents import print_html, receipt_html

            sale = self.services.sales.get(sale_id)
            html_text = receipt_html(sale, self.services.profile.get(), settings)
            print_html(
                html_text,
                printer_name=settings.get("printer_name"),
                width_mm=float(settings.get("paper_width_mm", "80")),
                margin_mm=float(settings.get_int("receipt_margin_mm", 3)),
                copies=settings.get_int("receipt_copies", 1),
            )
            return True
        except (RuntimeError, OSError, ImportError) as exc:
            show_error(self, f"রিসিট প্রিন্ট করা যায়নি: {exc}")
            return False
