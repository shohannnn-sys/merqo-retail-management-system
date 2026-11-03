"""Shared UI component library built on the Retvia design system.

Every screen composes these widgets so tables, forms, dialogs and empty states
behave identically across the product.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import RetviaError
from ..core.money import format_money, parse_money
from ..core.quantity import format_quantity, parse_quantity
from .theme import COLORS, SPACE


# --------------------------------------------------------------------- helpers
def show_error(parent: QWidget, error: Exception | str) -> None:
    message = error.message if isinstance(error, RetviaError) else str(error)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("সমস্যা হয়েছে")
    box.setText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.button(QMessageBox.Ok).setText("ঠিক আছে")
    box.exec()


def show_info(parent: QWidget, message: str, title: str = "সম্পন্ন") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.button(QMessageBox.Ok).setText("ঠিক আছে")
    box.exec()


def confirm(parent: QWidget, message: str, title: str = "নিশ্চিত করুন") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(message)
    yes = box.addButton("হ্যাঁ", QMessageBox.YesRole)
    no = box.addButton("না", QMessageBox.NoRole)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


def guarded(
    parent: QWidget, action: Callable[[], Any], on_success: Callable[[Any], None] | None = None
) -> Any:
    """Run a service call, converting domain errors into a friendly dialog."""
    try:
        result = action()
    except RetviaError as exc:
        show_error(parent, exc)
        return None
    except (OSError, ValueError, RuntimeError) as exc:
        show_error(parent, f"অপ্রত্যাশিত সমস্যা: {exc}")
        return None
    if on_success is not None:
        on_success(result)
    return result


# ---------------------------------------------------------------------- layout
class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        self._outer.setSpacing(SPACE["md"])
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self._outer.addWidget(label)
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE["sm"])
        self._outer.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout: Any) -> None:
        self.body.addLayout(layout)


class KpiCard(QFrame):
    def __init__(
        self,
        label: str,
        value: str = "—",
        hint: str = "",
        tone: str = "default",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(2)
        self._label = QLabel(label)
        self._label.setObjectName("KpiLabel")
        self._value = QLabel(value)
        self._value.setObjectName(
            {"accent": "KpiValueAccent", "danger": "KpiValueDanger"}.get(tone, "KpiValue")
        )
        self._value.setWordWrap(False)
        self._hint = QLabel(hint)
        self._hint.setObjectName("KpiHint")
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._hint)
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: str, hint: str = "") -> None:
        self._value.setText(value)
        self._value.setToolTip(value)
        if hint:
            self._hint.setText(hint)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACE["md"])
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        text.addWidget(heading)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE["sm"])
        layout.addLayout(self.actions)

    def add_action(self, text: str, callback: Callable[[], None], *, kind: str = "") -> QPushButton:
        button = QPushButton(text)
        if kind:
            button.setObjectName(kind)
        button.clicked.connect(lambda: callback())
        self.actions.addWidget(button)
        return button


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)


# ---------------------------------------------------------------------- inputs
class MoneyEdit(QLineEdit):
    """Accepts Bangla or English digits and exposes an integer-poisha value."""

    def __init__(self, poisha: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("0.00")
        self.setAlignment(Qt.AlignRight)
        self.set_poisha(poisha)

    def poisha(self) -> int:
        return parse_money(self.text())

    def set_poisha(self, value: int) -> None:
        self.setText(format_money(value, grouping=False))


class QuantityEdit(QLineEdit):
    def __init__(self, milli: int = 1000, precision: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._precision = precision
        self.setPlaceholderText("1")
        self.setAlignment(Qt.AlignRight)
        self.set_milli(milli)

    def milli(self) -> int:
        return parse_quantity(self.text(), precision=self._precision)

    def set_milli(self, value: int) -> None:
        self.setText(format_quantity(value, precision=self._precision))

    def set_precision(self, precision: int) -> None:
        self._precision = precision


class SearchBox(QLineEdit):
    submitted = Signal(str)

    def __init__(self, placeholder: str = "খুঁজুন…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(220)
        self.returnPressed.connect(lambda: self.submitted.emit(self.text()))
        self.textChanged.connect(lambda text: self.submitted.emit(text))


# ----------------------------------------------------------------------- table
@dataclass(slots=True)
class TableColumn:
    key: str
    label: str
    kind: str = "text"  # text | money | qty | int | date | percent
    width: int = 0
    align: str = "left"


class DataTable(QTableWidget):
    """Sortable, selectable table with a real empty state."""

    row_activated = Signal(dict)

    def __init__(self, columns: Sequence[TableColumn], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[dict[str, Any]] = []
        self.setColumnCount(len(self._columns))
        self.setHorizontalHeaderLabels([c.label for c in self._columns])
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(34)
        for index, column in enumerate(self._columns):
            if column.width:
                self.setColumnWidth(index, column.width)
        self.cellDoubleClicked.connect(self._emit_activated)
        self._empty = QLabel("কোনো তথ্য নেই", self.viewport())
        self._empty.setObjectName("EmptyState")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setVisible(False)
        self._empty.setGeometry(self.viewport().rect())

    def empty_widget(self) -> QWidget:
        return self._empty

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._empty.setGeometry(self.viewport().rect())

    def format_cell(self, column: TableColumn, value: Any) -> str:
        if value is None:
            return ""
        if column.kind == "money":
            return format_money(int(value))
        if column.kind == "qty":
            return format_quantity(int(value))
        if column.kind == "percent":
            return f"{int(value) / 100:.2f}%"
        return str(value)

    def set_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        self.setSortingEnabled(False)
        self._rows = list(rows)
        self.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            for col_index, column in enumerate(self._columns):
                text = self.format_cell(column, row.get(column.key))
                raw = row.get(column.key)
                numeric = column.kind in ("money", "qty", "int", "percent") and isinstance(raw, int)
                item = NumericTableItem(text) if numeric else QTableWidgetItem(text)
                if column.kind in ("money", "qty", "int", "percent"):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif column.align == "center":
                    item.setTextAlignment(Qt.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setToolTip(text)
                if isinstance(raw, int | float):
                    item.setData(Qt.UserRole, raw)
                self.setItem(row_index, col_index, item)
        self.setSortingEnabled(True)
        self._empty.setVisible(not self._rows)

    def rows(self) -> list[dict[str, Any]]:
        return self._rows

    def selected_record(self) -> dict[str, Any] | None:
        indexes = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not indexes:
            return None
        visual = indexes[0].row()
        key_item = self.item(visual, 0)
        if key_item is None:
            return None
        # Map the visible row back to the source record via the id column when present.
        identifier = None
        for col_index, column in enumerate(self._columns):
            if column.key == "id":
                cell = self.item(visual, col_index)
                identifier = cell.data(Qt.UserRole) if cell else None
                break
        if identifier is not None:
            for row in self._rows:
                if row.get("id") == identifier:
                    return row
        text = key_item.text()
        for row in self._rows:
            if self.format_cell(self._columns[0], row.get(self._columns[0].key)) == text:
                return row
        return None

    def _emit_activated(self, row: int, _column: int) -> None:
        record = self.selected_record()
        if record:
            self.row_activated.emit(record)


class NumericTableItem(QTableWidgetItem):
    """Sorts numerically while displaying formatted text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        left = self.data(Qt.UserRole)
        right = other.data(Qt.UserRole)
        if left is not None and right is not None:
            return float(left) < float(right)
        return self.text() < other.text()


class Pagination(QWidget):
    changed = Signal(int)

    def __init__(self, page_size: int = 50, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_size = page_size
        self.offset = 0
        self.total = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACE["sm"], 0, 0)
        self.info = QLabel("০ রেকর্ড")
        self.info.setObjectName("Muted")
        self.prev = QPushButton("◀ পূর্ববর্তী")
        self.next = QPushButton("পরবর্তী ▶")
        self.prev.clicked.connect(lambda: self._move(-1))
        self.next.clicked.connect(lambda: self._move(1))
        layout.addWidget(self.info, 1)
        layout.addWidget(self.prev)
        layout.addWidget(self.next)
        self._sync()

    def set_total(self, total: int) -> None:
        self.total = total
        self._sync()

    def _move(self, direction: int) -> None:
        new_offset = max(0, self.offset + direction * self.page_size)
        if new_offset >= self.total and direction > 0:
            return
        self.offset = new_offset
        self._sync()
        self.changed.emit(self.offset)

    def reset(self) -> None:
        self.offset = 0
        self._sync()

    def _sync(self) -> None:
        start = self.offset + 1 if self.total else 0
        end = min(self.offset + self.page_size, self.total)
        self.info.setText(f"{start}–{end} / মোট {self.total} রেকর্ড")
        self.prev.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + self.page_size < self.total)


# ------------------------------------------------------------------------ form
@dataclass(slots=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"  # text|money|qty|int|combo|date|checkbox|textarea|readonly
    required: bool = False
    options: list[tuple[Any, str]] = field(default_factory=list)
    value: Any = None
    help: str = ""
    precision: int = 3
    placeholder: str = ""


class FormDialog(QDialog):
    """Builds a validated form from field specifications."""

    def __init__(
        self,
        title: str,
        fields: Sequence[FieldSpec],
        parent: QWidget | None = None,
        validator: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._fields = list(fields)
        self._widgets: dict[str, QWidget] = {}
        self._validator = validator
        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["md"])
        form = QFormLayout()
        form.setSpacing(SPACE["sm"])
        form.setLabelAlignment(Qt.AlignLeft)
        for spec in self._fields:
            widget = self._build(spec)
            self._widgets[spec.key] = widget
            label_text = spec.label + (" *" if spec.required else "")
            label = QLabel(label_text)
            label.setObjectName("FieldLabel")
            container = QVBoxLayout()
            container.setSpacing(2)
            container.addWidget(widget)
            if spec.help:
                help_label = QLabel(spec.help)
                help_label.setObjectName("HelpText")
                help_label.setWordWrap(True)
                container.addWidget(help_label)
            wrapper = QWidget()
            wrapper.setLayout(container)
            form.addRow(label, wrapper)
        outer.addLayout(form)
        self._error = QLabel("")
        self._error.setObjectName("FieldError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        outer.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("সংরক্ষণ করুন")
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Cancel).setText("বাতিল")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._accept)
        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

    def _build(self, spec: FieldSpec) -> QWidget:
        if spec.kind == "money":
            return MoneyEdit(int(spec.value or 0))
        if spec.kind == "qty":
            return QuantityEdit(int(spec.value if spec.value is not None else 1000), spec.precision)
        if spec.kind == "int":
            widget = QLineEdit(str(spec.value if spec.value is not None else 0))
            widget.setAlignment(Qt.AlignRight)
            return widget
        if spec.kind == "combo":
            combo = QComboBox()
            for value, label in spec.options:
                combo.addItem(label, value)
            if spec.value is not None:
                index = combo.findData(spec.value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            return combo
        if spec.kind == "date":
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            if spec.value:
                parsed = QDate.fromString(str(spec.value), "yyyy-MM-dd")
                date_edit.setDate(parsed if parsed.isValid() else QDate.currentDate())
            else:
                date_edit.setDate(QDate.currentDate())
            return date_edit
        if spec.kind == "checkbox":
            check = QCheckBox(spec.help or "")
            check.setChecked(bool(spec.value))
            return check
        if spec.kind == "textarea":
            text = QPlainTextEdit(str(spec.value or ""))
            text.setFixedHeight(72)
            return text
        if spec.kind == "readonly":
            readonly = QLineEdit(str(spec.value or ""))
            readonly.setReadOnly(True)
            return readonly
        widget = QLineEdit(str(spec.value or ""))
        if spec.placeholder:
            widget.setPlaceholderText(spec.placeholder)
        return widget

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for spec in self._fields:
            widget = self._widgets[spec.key]
            if isinstance(widget, MoneyEdit):
                result[spec.key] = widget.poisha()
            elif isinstance(widget, QuantityEdit):
                result[spec.key] = widget.milli()
            elif isinstance(widget, QComboBox):
                result[spec.key] = widget.currentData()
            elif isinstance(widget, QDateEdit):
                result[spec.key] = widget.date().toString("yyyy-MM-dd")
            elif isinstance(widget, QCheckBox):
                result[spec.key] = widget.isChecked()
            elif isinstance(widget, QPlainTextEdit):
                result[spec.key] = widget.toPlainText()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                if spec.kind == "int":
                    from ..core.money import normalize_digits

                    try:
                        result[spec.key] = int(normalize_digits(text) or 0)
                    except ValueError:
                        result[spec.key] = 0
                else:
                    result[spec.key] = text
            else:
                result[spec.key] = None
        return result

    def _accept(self) -> None:
        values = self.values()
        for spec in self._fields:
            if (
                spec.required
                and spec.kind in ("text", "textarea")
                and not str(values.get(spec.key, "")).strip()
            ):
                self._fail(f"{spec.label} আবশ্যক")
                return
            if spec.required and spec.kind == "combo" and values.get(spec.key) in (None, ""):
                self._fail(f"{spec.label} নির্বাচন করুন")
                return
        if self._validator:
            message = self._validator(values)
            if message:
                self._fail(message)
                return
        self.accept()

    def _fail(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    @staticmethod
    def ask(
        title: str,
        fields: Sequence[FieldSpec],
        parent: QWidget | None = None,
        validator: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> dict[str, Any] | None:
        dialog = FormDialog(title, fields, parent, validator)
        if dialog.exec() == QDialog.Accepted:
            return dialog.values()
        return None


def bold_font(size: int = 13) -> QFont:
    font = QFont()
    font.setPointSize(size)
    font.setBold(True)
    return font


def muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def status_chip(text: str, *, warn: bool = False) -> QLabel:
    chip = QLabel(text)
    chip.setObjectName("StatusChipWarn" if warn else "StatusChip")
    return chip


def hline() -> QFrame:
    return Divider()


def color_for(kind: str) -> str:
    return {
        "success": COLORS["accent"],
        "danger": COLORS["danger"],
        "warning": COLORS["warning"],
        "info": COLORS["info"],
    }.get(kind, COLORS["text"])
