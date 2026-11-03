"""Barcode / QR label design and printing."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ..theme import SPACE
from ..widgets import (
    Card,
    PageHeader,
    SearchBox,
    guarded,
    show_error,
    show_info,
)

LABEL_SIZES = [
    ("50x25", "৫০ × ২৫ মিমি (ছোট শেলফ লেবেল)", 50.0, 25.0),
    ("50x30", "৫০ × ৩০ মিমি", 50.0, 30.0),
    ("65x35", "৬৫ × ৩৫ মিমি (স্ট্যান্ডার্ড)", 65.0, 35.0),
    ("75x50", "৭৫ × ৫০ মিমি (বড় লেবেল)", 75.0, 50.0),
]


class LabelsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._selected: dict[int, int] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("বারকোড ও লেবেল প্রিন্ট", "প্রোডাক্টের বারকোড / QR তৈরি করে লেবেল প্রিন্ট করুন")
        header.add_action("প্রিভিউ দেখুন", self._preview, kind="Primary")
        header.add_action("লেবেল প্রিন্ট", self._print, kind="Accent")
        header.add_action("PDF সংরক্ষণ", self._save_pdf)
        header.add_action("বারকোড ছবি সংরক্ষণ", self._save_image)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, SPACE["md"], 0)
        self.search = SearchBox("প্রোডাক্ট খুঁজুন…")
        self.search.submitted.connect(lambda _: self.refresh())
        left_layout.addWidget(self.search)
        self.product_list = QListWidget()
        self.product_list.itemChanged.connect(self._item_changed)
        left_layout.addWidget(self.product_list, 1)
        hint = QLabel("টিক দিয়ে প্রোডাক্ট নির্বাচন করুন। বারকোড না থাকলে স্বয়ংক্রিয়ভাবে তৈরি হবে।")
        hint.setObjectName("HelpText")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        options = Card("লেবেল সেটিংস")

        row = QHBoxLayout()
        row.addWidget(QLabel("লেবেলের মাপ:"))
        self.size_combo = QComboBox()
        for key, label, _w, _h in LABEL_SIZES:
            self.size_combo.addItem(label, key)
        self.size_combo.setCurrentIndex(2)
        self.size_combo.currentIndexChanged.connect(lambda: self._preview())
        row.addWidget(self.size_combo, 1)
        options.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("কোডের ধরন:"))
        self.code_kind = QComboBox()
        self.code_kind.addItem("বারকোড (Code128)", "barcode")
        self.code_kind.addItem("QR কোড", "qr")
        self.code_kind.currentIndexChanged.connect(lambda: self._preview())
        row.addWidget(self.code_kind, 1)
        options.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("প্রতি প্রোডাক্টে কপি:"))
        self.copies = QSpinBox()
        self.copies.setRange(1, 200)
        self.copies.setValue(1)
        row.addWidget(self.copies)
        row.addStretch(1)
        options.add_layout(row)

        self.show_name = QCheckBox("প্রোডাক্টের নাম দেখান")
        self.show_name.setChecked(True)
        self.show_price = QCheckBox("বিক্রয় মূল্য দেখান")
        self.show_price.setChecked(True)
        self.show_business = QCheckBox("দোকানের নাম দেখান")
        self.show_business.setChecked(False)
        self.show_code_text = QCheckBox("কোডের নিচে নম্বর দেখান")
        self.show_code_text.setChecked(True)
        for widget in (self.show_name, self.show_price, self.show_business, self.show_code_text):
            widget.stateChanged.connect(lambda: self._preview())
            options.add(widget)
        right_layout.addWidget(options)

        preview_card = Card("প্রিভিউ")
        self.preview_label = QLabel("প্রোডাক্ট নির্বাচন করে প্রিভিউ দেখুন")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setObjectName("EmptyState")
        preview_card.add(self.preview_label)
        right_layout.addWidget(preview_card, 1)
        splitter.addWidget(right)
        splitter.setSizes([420, 620])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self.product_list.blockSignals(True)
        self.product_list.clear()
        for row in self.services.products.search(query=self.search.text(), limit=500)["rows"]:
            item = QListWidgetItem(f"{row['name']}  ·  {row['sku']}  ·  {row['barcode'] or 'কোড নেই'}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if row["id"] in self._selected else Qt.Unchecked)
            item.setData(Qt.UserRole, row)
            self.product_list.addItem(item)
        self.product_list.blockSignals(False)

    def _item_changed(self, item: QListWidgetItem) -> None:
        product = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._selected[product["id"]] = product["id"]
        else:
            self._selected.pop(product["id"], None)

    def _products(self) -> list[dict[str, Any]]:
        chosen = []
        for index in range(self.product_list.count()):
            item = self.product_list.item(index)
            if item.checkState() == Qt.Checked:
                product = dict(item.data(Qt.UserRole))
                if not product.get("barcode"):
                    product_id = int(product["id"])

                    def generate(pid: int = product_id) -> str:
                        return self.services.barcodes.generate(pid)

                    code = guarded(self, generate)
                    if code:
                        product["barcode"] = code
                chosen.append(product)
        return chosen

    def _size(self) -> tuple[float, float]:
        key = self.size_combo.currentData()
        for size_key, _label, width, height in LABEL_SIZES:
            if size_key == key:
                return width, height
        return 65.0, 35.0

    def _render_label(self, product: dict[str, Any]) -> QImage:
        from ...printing.documents import label_html, render_label_image

        width, height = self._size()
        html_text = label_html(
            product,
            self.services.profile.get(),
            width_mm=width,
            height_mm=height,
            show_name=self.show_name.isChecked(),
            show_price=self.show_price.isChecked(),
            show_business=self.show_business.isChecked(),
            show_code_text=self.show_code_text.isChecked(),
            code_kind=self.code_kind.currentData(),
        )
        return render_label_image(html_text, width_mm=width, height_mm=height)

    # ---------------------------------------------------------------- actions
    def _preview(self) -> None:
        products = self._products()
        if not products:
            self.preview_label.setText("প্রোডাক্ট নির্বাচন করুন")
            self.preview_label.setPixmap(QImage())
            return
        try:
            image = self._render_label(products[0])
        except (RuntimeError, ImportError, OSError) as exc:
            show_error(self, f"প্রিভিউ তৈরি করা যায়নি: {exc}")
            return
        if image.isNull():
            show_error(self, "লেবেল রেন্ডার করা যায়নি")
            return
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap.fromImage(image)
        self.preview_label.setPixmap(pixmap.scaled(420, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _sheet_html(self, products: list[dict[str, Any]]) -> str:
        from ...printing.documents import label_html

        width, height = self._size()
        profile = self.services.profile.get()
        cells = []
        for product in products:
            for _ in range(self.copies.value()):
                cells.append(
                    label_html(
                        product,
                        profile,
                        width_mm=width,
                        height_mm=height,
                        show_name=self.show_name.isChecked(),
                        show_price=self.show_price.isChecked(),
                        show_business=self.show_business.isChecked(),
                        show_code_text=self.show_code_text.isChecked(),
                        code_kind=self.code_kind.currentData(),
                        fragment=True,
                    )
                )
        return (
            "<html><head><meta charset='utf-8'><style>"
            "body{margin:0;font-family:'Noto Sans Bengali',sans-serif;}"
            f".label{{width:{width}mm;height:{height}mm;display:inline-block;"
            "overflow:hidden;box-sizing:border-box;page-break-inside:avoid;}}"
            "</style></head><body>" + "".join(cells) + "</body></html>"
        )

    def _print(self) -> None:
        products = self._products()
        if not products:
            show_error(self, "আগে অন্তত একটি প্রোডাক্ট নির্বাচন করুন")
            return
        printer_name = self.services.settings.get("label_printer_name") or self.services.settings.get(
            "printer_name"
        )
        if not printer_name:
            show_error(self, "সেটিংস থেকে লেবেল প্রিন্টার নির্বাচন করুন")
            return
        from ...printing.documents import print_html

        width, height = self._size()
        try:
            print_html(
                self._sheet_html(products),
                printer_name=printer_name,
                width_mm=width,
                height_mm=height,
                margin_mm=0.0,
            )
        except (RuntimeError, ImportError, OSError) as exc:
            show_error(self, f"প্রিন্ট করা যায়নি: {exc}")
            return
        total = len(products) * self.copies.value()
        show_info(self, f"{total}টি লেবেল প্রিন্টারের পাঠানো হয়েছে")

    def _save_pdf(self) -> None:
        products = self._products()
        if not products:
            show_error(self, "আগে অন্তত একটি প্রোডাক্ট নির্বাচন করুন")
            return
        path, _ = QFileDialog.getSaveFileName(self, "লেবেল PDF", "labels.pdf", "PDF (*.pdf)")
        if not path:
            return
        from ...printing.documents import render_html_pdf

        saved = guarded(
            self,
            lambda: render_html_pdf(
                self._sheet_html(products), path, width_mm=210.0, height_mm=297.0, margin_mm=5.0
            ),
        )
        if saved:
            show_info(self, f"লেবেল PDF সংরক্ষিত:\n{saved}")

    def _save_image(self) -> None:
        products = self._products()
        if not products:
            show_error(self, "আগে একটি প্রোডাক্ট নির্বাচন করুন")
            return
        product = products[0]
        code = product.get("barcode") or product["sku"]
        path, _ = QFileDialog.getSaveFileName(self, "কোডের ছবি সংরক্ষণ", f"{code}.png", "PNG (*.png)")
        if not path:
            return
        from ...printing.documents import barcode_image, qr_image

        try:
            image = qr_image(code) if self.code_kind.currentData() == "qr" else barcode_image(code)
            if image.isNull() or not image.save(path):
                show_error(self, "ছবি সংরক্ষণ করা যায়নি")
                return
        except (RuntimeError, ImportError, OSError, ValueError) as exc:
            show_error(self, f"কোড তৈরি করা যায়নি: {exc}")
            return
        show_info(self, f"সংরক্ষিত:\n{path}\nমূল্য: {format_money(product['selling_price'])}")
