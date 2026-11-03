"""Product management: CRUD, barcodes, stock adjustment, import and export."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...services.catalog import ProductInput
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    PageHeader,
    Pagination,
    SearchBox,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)

COLUMNS = [
    TableColumn("id", "আইডি", "int", width=60),
    TableColumn("name", "প্রোডাক্টের নাম", width=220),
    TableColumn("sku", "এসকেইউ", width=110),
    TableColumn("barcode", "বারকোড", width=120),
    TableColumn("category_name", "ক্যাটাগরি", width=120),
    TableColumn("unit_name", "ইউনিট", width=80),
    TableColumn("purchase_price", "পারচেজ দর", "money", width=110),
    TableColumn("selling_price", "বিক্রয় দর", "money", width=110),
    TableColumn("stock_qty", "মজুদ", "qty", width=90),
    TableColumn("stock_value", "স্টক মূল্য", "money", width=120),
    TableColumn("status", "স্ট্যাটাস", width=90),
]


class ProductsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._query = ""
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("প্রোডাক্ট ম্যানেজমেন্ট", "প্রোডাক্ট যোগ, সম্পাদনা, বারকোড ও স্টক সমন্বয়")
        header.add_action("+ নতুন প্রোডাক্ট", self._create, kind="Primary")
        header.add_action("সম্পাদনা", self._edit)
        header.add_action("বারকোড", self._barcodes)
        header.add_action("স্টক সমন্বয়", self._adjust)
        header.add_action("আর্কাইভ / সক্রিয়", self._toggle_status)
        header.add_action("মুছে ফেলুন", self._delete, kind="Danger")
        layout.addWidget(header)

        filters = QHBoxLayout()
        self.search = SearchBox("নাম, এসকেইউ বা বারকোড দিয়ে খুঁজুন…")
        self.search.submitted.connect(self._search)
        filters.addWidget(self.search, 2)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(lambda: self._reload(reset=True))
        filters.addWidget(QLabel("ক্যাটাগরি:"))
        filters.addWidget(self.category_filter, 1)
        self.stock_filter = QComboBox()
        for key, label in (("all", "সব স্টক"), ("in", "স্টকে আছে"), ("low", "লো স্টক"), ("out", "স্টক আউট")):
            self.stock_filter.addItem(label, key)
        self.stock_filter.currentIndexChanged.connect(lambda: self._reload(reset=True))
        filters.addWidget(self.stock_filter)
        self.status_filter = QComboBox()
        for key, label in (("active", "সক্রিয়"), ("archived", "আর্কাইভ"), ("all", "সব")):
            self.status_filter.addItem(label, key)
        self.status_filter.currentIndexChanged.connect(lambda: self._reload(reset=True))
        filters.addWidget(self.status_filter)
        layout.addLayout(filters)

        card = Card()
        self.table = DataTable(COLUMNS)
        self.table.row_activated.connect(lambda _: self._edit())
        card.add(self.table)
        self.pagination = Pagination(page_size=50)
        self.pagination.changed.connect(lambda _: self._reload())
        card.add(self.pagination)
        layout.addWidget(card, 1)

        tools = QHBoxLayout()
        import_button = QLabel("")
        tools.addWidget(import_button)
        tools.addStretch(1)
        for label, handler in (
            ("CSV এক্সপোর্ট", lambda: self._export("csv")),
            ("Excel এক্সপোর্ট", lambda: self._export("xlsx")),
        ):
            button = QLabel(f'<a href="#">{label}</a>')
            button.linkActivated.connect(lambda _, h=handler: h())
            tools.addWidget(button)
        layout.addLayout(tools)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("সব ক্যাটাগরি", None)
        for row in self.services.categories.list():
            self.category_filter.addItem(row["name"], row["id"])
        self.category_filter.blockSignals(False)
        self._reload(reset=True)

    def _search(self, text: str) -> None:
        self._query = text
        self._reload(reset=True)

    def _reload(self, *, reset: bool = False) -> None:
        if reset:
            self.pagination.reset()
        result = guarded(
            self,
            lambda: self.services.products.search(
                query=self._query,
                category_id=self.category_filter.currentData(),
                status=self.status_filter.currentData(),
                stock_filter=self.stock_filter.currentData(),
                limit=self.pagination.page_size,
                offset=self.pagination.offset,
            ),
        )
        if result is None:
            return
        self.table.set_rows(result["rows"])
        self.pagination.set_total(result["total"])

    def _selected(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            show_error(self, "আগে একটি প্রোডাক্ট নির্বাচন করুন")
        return record

    # ----------------------------------------------------------------- form
    def _form_fields(self, existing: dict[str, Any] | None = None) -> list[FieldSpec]:
        units = [(u["id"], f"{u['name']} ({u['symbol']})") for u in self.services.units.list()]
        categories: list[tuple[Any, str]] = [(None, "— ক্যাটাগরি নেই —")]
        categories += [(c["id"], c["name"]) for c in self.services.categories.list()]
        e = existing or {}
        return [
            FieldSpec("name", "প্রোডাক্টের নাম", "text", required=True, value=e.get("name", "")),
            FieldSpec(
                "sku",
                "এসকেইউ (SKU)",
                "text",
                required=True,
                value=e.get("sku", ""),
                help="ইউনিক কোড, যেমন RICE-001",
            ),
            FieldSpec("barcode", "বারকোড", "text", value=e.get("barcode", "")),
            FieldSpec("category_id", "ক্যাটাগরি", "combo", options=categories, value=e.get("category_id")),
            FieldSpec(
                "unit_id",
                "ইউনিট",
                "combo",
                required=True,
                options=units,
                value=e.get("unit_id") or (units[0][0] if units else None),
            ),
            FieldSpec("brand", "ব্র্যান্ড", "text", value=e.get("brand", "")),
            FieldSpec("purchase_price", "পারচেজ মূল্য", "money", value=e.get("purchase_price", 0)),
            FieldSpec("selling_price", "বিক্রয় মূল্য", "money", value=e.get("selling_price", 0)),
            FieldSpec(
                "opening_qty",
                "ওপেনিং স্টক",
                "qty",
                value=e.get("opening_qty", 0),
                help="শুধু নতুন প্রোডাক্টে প্রযোজ্য; পরে স্টক সমন্বয় ব্যবহার করুন",
            ),
            FieldSpec("min_stock_qty", "মিনিমাম স্টক (সতর্কতা)", "qty", value=e.get("min_stock_qty", 0)),
            FieldSpec("description", "বিবরণ", "textarea", value=e.get("description", "")),
            FieldSpec("track_stock", "স্টক ট্র্যাক করুন", "checkbox", value=e.get("track_stock", 1)),
        ]

    def _create(self) -> None:
        values = FormDialog.ask("নতুন প্রোডাক্ট", self._form_fields(), self)
        if values is None:
            return
        data = ProductInput(
            **{k: v for k, v in values.items() if k != "opening_qty"}, opening_qty=values["opening_qty"]
        )
        created = guarded(self, lambda: self.services.products.create(data))
        if created:
            show_info(self, "প্রোডাক্ট সফলভাবে যোগ হয়েছে")
            self._reload()

    def _edit(self) -> None:
        record = self._selected()
        if record is None:
            return
        product = self.services.products.get(record["id"])
        values = FormDialog.ask("প্রোডাক্ট সম্পাদনা", self._form_fields(product), self)
        if values is None:
            return
        data = ProductInput(**{k: v for k, v in values.items() if k != "opening_qty"})
        if guarded(self, lambda: self.services.products.update(product["id"], data)) is not None:
            show_info(self, "প্রোডাক্ট হালনাগাদ হয়েছে")
        self._reload()

    def _toggle_status(self) -> None:
        record = self._selected()
        if record is None:
            return
        new_status = "archived" if record["status"] == "active" else "active"
        guarded(self, lambda: self.services.products.set_status(record["id"], new_status))
        self._reload()

    def _delete(self) -> None:
        record = self._selected()
        if record is None:
            return
        if not confirm(self, f"'{record['name']}' মুছে ফেলবেন? লেনদেন থাকলে মুছে ফেলা যাবে না।"):
            return
        guarded(self, lambda: self.services.products.delete(record["id"]))
        self._reload()

    # -------------------------------------------------------------- barcode
    def _barcodes(self) -> None:
        record = self._selected()
        if record is None:
            return
        product = self.services.products.get(record["id"])
        existing = self.services.barcodes.for_product(product["id"])
        listing = "\n".join(f"• {b['code']}" for b in existing) or "কোনো বারকোড নেই"
        values = FormDialog.ask(
            "বারকোড ব্যবস্থাপনা",
            [
                FieldSpec("current", "বর্তমান বারকোড", "readonly", value=listing.replace("\n", "  |  ")),
                FieldSpec("code", "নতুন বারকোড যোগ করুন", "text"),
                FieldSpec("generate", "স্বয়ংক্রিয় বারকোড তৈরি করুন", "checkbox", value=False),
            ],
            self,
        )
        if values is None:
            return
        if values["generate"]:
            code = guarded(self, lambda: self.services.barcodes.generate(product["id"]))
            if code:
                show_info(self, f"নতুন বারকোড: {code}")
        elif values["code"]:
            if guarded(self, lambda: self.services.barcodes.add(product["id"], values["code"])):
                show_info(self, "বারকোড যোগ হয়েছে")
        self._reload()

    # ------------------------------------------------------------ adjustment
    def _adjust(self) -> None:
        record = self._selected()
        if record is None:
            return
        product = self.services.products.get(record["id"])
        values = FormDialog.ask(
            f"স্টক সমন্বয় — {product['name']}",
            [
                FieldSpec(
                    "kind",
                    "সমন্বয়ের ধরন",
                    "combo",
                    options=[
                        ("damage", "নষ্ট / ড্যামেজ"),
                        ("loss", "হারানো"),
                        ("expiry", "মেয়াদ শেষ"),
                        ("count_increase", "গণনায় বৃদ্ধি"),
                        ("count_decrease", "গণনায় ঘাটতি"),
                    ],
                ),
                FieldSpec("quantity", "পরিমাণ", "qty", value=1000),
                FieldSpec("counted", "গণনাকৃত মোট মজুদ (গণনা হলে)", "qty", value=0),
                FieldSpec("reason", "কারণ", "text", required=True),
                FieldSpec("date", "তারিখ", "date"),
            ],
            self,
        )
        if values is None:
            return
        result = guarded(
            self,
            lambda: self.services.inventory.adjust(
                product_id=product["id"],
                adjustment_type=values["kind"],
                quantity=values["quantity"],
                counted_qty=values["counted"] or None,
                reason=values["reason"],
                adjustment_date=values["date"],
                actor=self.services.settings.get("cashier_name", ""),
            ),
        )
        if result:
            show_info(self, f"সমন্বয় সম্পন্ন — নতুন মজুদ {result['qty_after'] / 1000:g}")
        self._reload()

    # ---------------------------------------------------------------- export
    def _export(self, fmt: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "প্রোডাক্ট তালিকা এক্সপোর্ট",
            f"products.{fmt}",
            f"{fmt.upper()} ফাইল (*.{fmt})",
        )
        if not path:
            return
        result = guarded(self, lambda: self.services.reports.run("stock", {}))
        if result is None:
            return
        saved = guarded(self, lambda: self.services.exporting.export(result, path, fmt))
        if saved:
            show_info(self, f"এক্সপোর্ট সম্পন্ন:\n{saved}")
