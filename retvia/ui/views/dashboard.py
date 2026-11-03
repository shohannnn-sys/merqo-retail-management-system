"""Dashboard — every number comes from the live database."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_money
from ...services.finance import date_range_for
from ..charts import ChartWidget, DonutWidget
from ..theme import SPACE
from ..widgets import Card, DataTable, KpiCard, PageHeader, TableColumn, guarded


class DashboardView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._start, self._end = date_range_for("this_month")
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("ড্যাশবোর্ড", "আপনার ব্যবসার সর্বশেষ অবস্থা — সম্পূর্ণ লাইভ ডেটা থেকে")
        outer.addWidget(header)

        controls = QHBoxLayout()
        controls.setSpacing(SPACE["sm"])
        controls.addWidget(QLabel("সময়কাল:"))
        self.preset = QComboBox()
        for key, label in (
            ("today", "আজ"),
            ("yesterday", "গতকাল"),
            ("this_week", "এই সপ্তাহ"),
            ("this_month", "এই মাস"),
            ("this_year", "এই বছর"),
            ("last_30", "গত ৩০ দিন"),
            ("custom", "কাস্টম রেঞ্জ"),
        ):
            self.preset.addItem(label, key)
        self.preset.setCurrentIndex(3)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        controls.addWidget(self.preset)
        self.start_edit = QDateEdit(QDate.fromString(self._start, "yyyy-MM-dd"))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.dateChanged.connect(self._custom_changed)
        self.end_edit = QDateEdit(QDate.fromString(self._end, "yyyy-MM-dd"))
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.dateChanged.connect(self._custom_changed)
        controls.addWidget(QLabel("থেকে"))
        controls.addWidget(self.start_edit)
        controls.addWidget(QLabel("পর্যন্ত"))
        controls.addWidget(self.end_edit)
        controls.addStretch(1)
        self.health_chip = QLabel("")
        self.health_chip.setObjectName("StatusChip")
        controls.addWidget(self.health_chip)
        outer.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(SPACE["lg"])
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.kpi_grid = QGridLayout()
        self.kpi_grid.setSpacing(SPACE["md"])
        self.kpis: dict[str, KpiCard] = {}
        specs = [
            ("today_sales", "আজকের সেলস", "default"),
            ("net_sales", "নেট সেলস", "default"),
            ("gross_profit", "গ্রস প্রফিট", "accent"),
            ("net_profit", "নেট প্রফিট", "accent"),
            ("total_purchase", "মোট পারচেজ", "default"),
            ("total_expense", "মোট এক্সপেন্স", "danger"),
            ("customer_due", "কাস্টমার বাকি", "danger"),
            ("supplier_payable", "সাপ্লায়ার দেয়", "danger"),
            ("total_collection", "মোট কালেকশন", "accent"),
            ("stock_value", "স্টক মূল্য", "default"),
            ("low_stock", "লো স্টক প্রোডাক্ট", "default"),
            ("out_of_stock", "স্টক আউট প্রোডাক্ট", "danger"),
        ]
        for index, (key, label, tone) in enumerate(specs):
            card = KpiCard(label, "—", tone=tone)
            self.kpis[key] = card
            self.kpi_grid.addWidget(card, index // 4, index % 4)
        self.content_layout.addLayout(self.kpi_grid)

        chart_grid = QGridLayout()
        chart_grid.setSpacing(SPACE["md"])
        self.sales_chart = ChartWidget("সেলস ট্রেন্ড", "line")
        self.profit_chart = ChartWidget("প্রফিট ট্রেন্ড", "line")
        self.purchase_chart = ChartWidget("পারচেজ ট্রেন্ড", "bar")
        self.expense_chart = DonutWidget("এক্সপেন্স বিশ্লেষণ")
        self.payment_chart = DonutWidget("পেমেন্ট মেথড বিশ্লেষণ")
        self.product_chart = ChartWidget("সেরা বিক্রীত প্রোডাক্ট", "bar")
        for widget, (row, col) in (
            (self.sales_chart, (0, 0)),
            (self.profit_chart, (0, 1)),
            (self.purchase_chart, (1, 0)),
            (self.expense_chart, (1, 1)),
            (self.payment_chart, (2, 0)),
            (self.product_chart, (2, 1)),
        ):
            card = Card()
            card.add(widget)
            chart_grid.addWidget(card, row, col)
        self.content_layout.addLayout(chart_grid)

        tables = QHBoxLayout()
        tables.setSpacing(SPACE["md"])
        self.recent_sales = DataTable(
            [
                TableColumn("invoice_no", "ইনভয়েস"),
                TableColumn("customer_name", "কাস্টমার"),
                TableColumn("grand_total", "মোট", "money"),
                TableColumn("due_amount", "বাকি", "money"),
            ]
        )
        self.recent_sales.set_rows([])
        recent_card = Card("সাম্প্রতিক সেলস")
        recent_card.add(self.recent_sales)
        self.low_stock_table = DataTable(
            [
                TableColumn("name", "প্রোডাক্ট"),
                TableColumn("stock_qty", "মজুদ", "qty"),
                TableColumn("min_stock_qty", "মিনিমাম", "qty"),
            ]
        )
        low_card = Card("লো স্টক সতর্কতা")
        low_card.add(self.low_stock_table)
        tables.addWidget(recent_card, 1)
        tables.addWidget(low_card, 1)
        self.content_layout.addLayout(tables)

        self.transactions_table = DataTable(
            [
                TableColumn("txn_date", "তারিখ", "date"),
                TableColumn("txn_type", "ধরন"),
                TableColumn("txn_no", "ডকুমেন্ট"),
                TableColumn("party_name", "পার্টি"),
                TableColumn("amount", "পরিমাণ", "money"),
            ]
        )
        tx_card = Card("সাম্প্রতিক লেনদেন")
        tx_card.add(self.transactions_table)
        self.content_layout.addWidget(tx_card)
        self.content_layout.addStretch(1)

    def _preset_changed(self) -> None:
        key = self.preset.currentData()
        if key == "custom":
            return
        self._start, self._end = date_range_for(key)
        self.start_edit.blockSignals(True)
        self.end_edit.blockSignals(True)
        self.start_edit.setDate(QDate.fromString(self._start, "yyyy-MM-dd"))
        self.end_edit.setDate(QDate.fromString(self._end, "yyyy-MM-dd"))
        self.start_edit.blockSignals(False)
        self.end_edit.blockSignals(False)
        self.refresh()

    def _custom_changed(self) -> None:
        if self.preset.currentData() != "custom":
            self.preset.setCurrentIndex(6)
        self._start = self.start_edit.date().toString("yyyy-MM-dd")
        self._end = self.end_edit.date().toString("yyyy-MM-dd")
        self.refresh()

    def refresh(self) -> None:
        data = guarded(self, lambda: self.services.finance.dashboard(self._start, self._end))
        if data is None:
            return
        kpi = data["kpi"]
        symbol = self.services.settings.get("currency_symbol", "৳")
        money = lambda v: f"{symbol} {format_money(int(v))}"  # noqa: E731
        self.kpis["today_sales"].set_value(
            money(data["today"]["sales_amount"]), f"{data['today']['sales_count']} ইনভয়েস আজ"
        )
        self.kpis["net_sales"].set_value(money(kpi["net_sales"]), f"{kpi['sale_count']} ইনভয়েস")
        self.kpis["gross_profit"].set_value(money(kpi["gross_profit"]), "রিটার্ন ও COGS বাদে")
        self.kpis["net_profit"].set_value(money(kpi["net_profit"]), "এক্সপেন্স ও রাইট-অফ বাদে")
        self.kpis["total_purchase"].set_value(money(kpi["total_purchase"]))
        self.kpis["total_expense"].set_value(money(kpi["total_expense"]))
        self.kpis["customer_due"].set_value(money(kpi["customer_due"]))
        self.kpis["supplier_payable"].set_value(money(kpi["supplier_payable"]))
        self.kpis["total_collection"].set_value(money(kpi["total_collection"]))
        self.kpis["stock_value"].set_value(money(kpi["stock_value"]))
        self.kpis["low_stock"].set_value(str(kpi["low_stock_count"]), "মিনিমামের নিচে")
        self.kpis["out_of_stock"].set_value(str(kpi["out_of_stock_count"]), "মজুদ শূন্য")

        charts = data["charts"]
        self.sales_chart.set_data([(r["label"], r["amount"]) for r in charts["sales_trend"]])
        self.profit_chart.set_data(
            [(r["label"], r["gross_profit"]) for r in charts["profit_trend"]],
            [r["net_profit"] for r in charts["profit_trend"]],
        )
        self.purchase_chart.set_data([(r["label"], r["amount"]) for r in charts["purchase_trend"]])
        self.expense_chart.set_data([(r["label"], r["amount"]) for r in charts["expense_overview"]])
        self.payment_chart.set_data([(r["label"], r["amount"]) for r in charts["payment_overview"]])
        self.product_chart.set_data(
            [(r["name"], r["qty_sold"]) for r in charts["product_performance"]], money=False
        )
        self.recent_sales.set_rows(data["recent_sales"])
        self.low_stock_table.set_rows(data["low_stock"])
        self.transactions_table.set_rows(data["recent_transactions"])

        health = self.services.finance.reconcile_all()
        if health["healthy"]:
            self.health_chip.setText("✓ সব লেজার মিলে গেছে")
            self.health_chip.setObjectName("StatusChip")
        else:
            self.health_chip.setText("⚠ লেজার অমিল — সেটিংসে যাচাই করুন")
            self.health_chip.setObjectName("StatusChipWarn")
        self.health_chip.style().unpolish(self.health_chip)
        self.health_chip.style().polish(self.health_chip)
