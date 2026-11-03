"""Report registry and engine.

Every report is generated from live database rows — never from cached or sample
data. A single registry drives the UI table, the PDF export, the Excel export and
the CSV export, so an exported file always matches what the user saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..core.errors import NotFoundError, ValidationError
from ..core.validation import validate_date_range
from ..data.db import Database
from .finance import FinanceService, date_range_for
from .inventory import InventoryService
from .parties import CustomerService, SupplierService
from .settings import SettingsService


@dataclass(slots=True)
class Column:
    key: str
    label: str
    kind: str = "text"  # text | money | qty | int | date | percent
    total: bool = False


@dataclass(slots=True)
class ReportDefinition:
    id: str
    title: str
    group: str
    columns: list[Column]
    builder: Callable[..., list[dict[str, Any]]]
    filters: tuple[str, ...] = ("start", "end")
    description: str = ""


@dataclass(slots=True)
class ReportResult:
    id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, int] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def _money(key: str, label: str, total: bool = True) -> Column:
    return Column(key, label, "money", total)


def _qty(key: str, label: str, total: bool = True) -> Column:
    return Column(key, label, "qty", total)


def _int(key: str, label: str, total: bool = False) -> Column:
    return Column(key, label, "int", total)


class ReportService:
    def __init__(self, db: Database, settings: SettingsService | None = None) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.finance = FinanceService(db, self.settings)
        self.inventory = InventoryService(db, self.settings)
        self._registry = self._build_registry()

    # ------------------------------------------------------------------ misc
    def list_reports(self) -> list[dict[str, str]]:
        return [
            {"id": r.id, "title": r.title, "group": r.group, "description": r.description}
            for r in self._registry.values()
        ]

    def groups(self) -> list[str]:
        seen: list[str] = []
        for r in self._registry.values():
            if r.group not in seen:
                seen.append(r.group)
        return seen

    def definition(self, report_id: str) -> ReportDefinition:
        if report_id not in self._registry:
            raise NotFoundError(f"রিপোর্ট খুঁজে পাওয়া যায়নি: {report_id}")
        return self._registry[report_id]

    def run(self, report_id: str, filters: dict[str, Any] | None = None) -> ReportResult:
        definition = self.definition(report_id)
        filters = dict(filters or {})
        if "start" in definition.filters:
            preset = filters.pop("preset", None)
            if preset and not filters.get("start"):
                start, end = date_range_for(preset)
                filters["start"], filters["end"] = start, end
            filters.setdefault("start", date.today().replace(day=1).isoformat())
            filters.setdefault("end", date.today().isoformat())
            filters["start"], filters["end"] = validate_date_range(filters["start"], filters["end"])
        rows = definition.builder(self, filters)
        totals: dict[str, int] = {}
        for column in definition.columns:
            if column.total and column.kind in ("money", "int", "qty"):
                totals[column.key] = sum(int(r.get(column.key, 0) or 0) for r in rows)
        return ReportResult(
            id=definition.id, title=definition.title, columns=definition.columns,
            rows=rows, totals=totals, meta={"filters": filters, "row_count": len(rows)},
        )

    # -------------------------------------------------------------- builders
    def _sales_period(self, filters: dict[str, Any], grain: str) -> list[dict[str, Any]]:
        expr = {
            "day": "s.sale_date",
            "week": "strftime('%Y-W%W', s.sale_date)",
            "month": "strftime('%Y-%m', s.sale_date)",
            "year": "strftime('%Y', s.sale_date)",
        }[grain]
        return [
            dict(r) for r in self.db.query(
                f"""SELECT {expr} AS period, COUNT(*) AS invoice_count,
                          COALESCE(SUM(s.subtotal),0) AS gross_sales,
                          COALESCE(SUM(s.item_discount + s.invoice_discount),0) AS discount,
                          COALESCE(SUM(s.tax_amount),0) AS tax,
                          COALESCE(SUM(s.grand_total),0) AS net_total,
                          COALESCE(SUM(s.paid_amount),0) AS paid,
                          COALESCE(SUM(s.due_amount),0) AS due,
                          COALESCE(SUM(s.total_cost),0) AS cost,
                          COALESCE(SUM(s.grand_total - s.tax_amount - s.total_cost),0) AS profit
                     FROM sales s
                    WHERE s.status<>'cancelled' AND s.sale_date BETWEEN :start AND :end
                    GROUP BY period ORDER BY period""",
                filters,
            )
        ]

    def _sales_detail(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["s.sale_date BETWEEN :start AND :end"]
        params = dict(filters)
        if filters.get("customer_id"):
            where.append("s.customer_id = :customer_id")
        if filters.get("status"):
            where.append("s.status = :status")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT s.invoice_no, s.sale_date, COALESCE(c.name,'ওয়াক-ইন') AS customer,
                          s.subtotal AS gross_sales,
                          s.item_discount + s.invoice_discount AS discount,
                          s.tax_amount AS tax, s.grand_total AS net_total,
                          s.paid_amount AS paid, s.due_amount AS due, s.status
                     FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                    WHERE {' AND '.join(where)} ORDER BY s.sale_date, s.id""",
                params,
            )
        ]

    def _pnl_rows(self, filters: dict[str, Any], variant: str) -> list[dict[str, Any]]:
        pnl = self.finance.profit_and_loss(filters["start"], filters["end"])
        if variant == "gross":
            keys = [
                ("gross_sales", "মোট সেলস"), ("sales_discount", "ডিস্কাউন্ট"),
                ("sales_returns", "সেলস রিটার্ন"), ("net_sales", "নেট সেলস"),
                ("cogs", "বিক্রীত পণ্যের খরচ (COGS)"), ("gross_profit", "গ্রস প্রফিট"),
            ]
        elif variant == "net":
            keys = [
                ("net_sales", "নেট সেলস"), ("cogs", "বিক্রীত পণ্যের খরচ (COGS)"),
                ("gross_profit", "গ্রস প্রফিট"), ("operating_expense", "পরিচালন খরচ"),
                ("total_write_off", "ইনভেন্টরি রাইট-অফ"), ("net_profit", "নেট প্রফিট"),
            ]
        else:
            keys = [
                ("gross_sales", "মোট সেলস (Gross Sales)"),
                ("item_discount", "আইটেম ডিস্কাউন্ট"),
                ("invoice_discount", "ইনভয়েস ডিস্কাউন্ট"),
                ("sales_returns", "সেলস রিটার্ন"),
                ("net_sales", "নেট সেলস"),
                ("cogs", "বিক্রীত পণ্যের খরচ (COGS)"),
                ("gross_profit", "গ্রস প্রফিট"),
                ("operating_expense", "পরিচালন খরচ (Expense)"),
                ("stock_write_off", "স্টক রাইট-অফ (নষ্ট/হারানো/মেয়াদ)"),
                ("return_write_off", "নন-রিস্টক রিটার্ন লস"),
                ("net_profit", "নেট প্রফিট"),
                ("tax_collected", "সংগৃহীত ট্যাক্স (দায়)"),
                ("purchase_value", "মোট পারচেজ"),
            ]
        return [{"particulars": label, "amount": pnl[key]} for key, label in keys]

    def _expense(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["e.expense_date BETWEEN :start AND :end"]
        if filters.get("category_id"):
            where.append("e.category_id = :category_id")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT e.voucher_no, e.expense_date, ec.name AS category,
                          pm.name AS method, e.description, e.amount
                     FROM expenses e
                     JOIN expense_categories ec ON ec.id=e.category_id
                     JOIN payment_methods pm ON pm.id=e.payment_method_id
                    WHERE {' AND '.join(where)} ORDER BY e.expense_date, e.id""",
                filters,
            )
        ]

    def _purchase(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["p.purchase_date BETWEEN :start AND :end"]
        if filters.get("supplier_id"):
            where.append("p.supplier_id = :supplier_id")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT p.invoice_no, p.purchase_date, s.name AS supplier,
                          p.supplier_invoice_no, p.subtotal AS gross_amount,
                          p.discount_amount AS discount, p.grand_total AS net_total,
                          p.paid_amount AS paid, p.due_amount AS due, p.status
                     FROM purchases p JOIN suppliers s ON s.id=p.supplier_id
                    WHERE {' AND '.join(where)} ORDER BY p.purchase_date, p.id""",
                filters,
            )
        ]

    def _stock(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["p.status='active'"]
        params: dict[str, Any] = {}
        if filters.get("category_id"):
            where.append("p.category_id = :category_id")
            params["category_id"] = filters["category_id"]
        if filters.get("stock_filter") == "low":
            where.append("p.stock_qty <= p.min_stock_qty AND p.stock_qty > 0 AND p.track_stock=1")
        elif filters.get("stock_filter") == "out":
            where.append("p.stock_qty <= 0 AND p.track_stock=1")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT p.name, p.sku, COALESCE(c.name,'') AS category, u.symbol AS unit,
                          p.stock_qty, p.min_stock_qty, p.avg_cost, p.stock_value,
                          p.selling_price
                     FROM products p JOIN units u ON u.id=p.unit_id
                     LEFT JOIN categories c ON c.id=p.category_id
                    WHERE {' AND '.join(where)} ORDER BY p.name""",
                params,
            )
        ]

    def _stock_movement(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["m.movement_date BETWEEN :start AND :end"]
        if filters.get("product_id"):
            where.append("m.product_id = :product_id")
        if filters.get("movement_type"):
            where.append("m.movement_type = :movement_type")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT m.movement_date, p.name AS product, p.sku, m.movement_type,
                          m.qty_delta, m.qty_before, m.qty_after, m.unit_cost,
                          m.value_delta, m.reference_type, m.notes
                     FROM stock_movements m JOIN products p ON p.id=m.product_id
                    WHERE {' AND '.join(where)} ORDER BY m.id DESC""",
                filters,
            )
        ]

    def _valuation(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "name": r["name"], "sku": r["sku"], "unit": r["unit_symbol"],
                "stock_qty": r["stock_qty"], "avg_cost": r["avg_cost"], "stock_value": r["stock_value"],
            }
            for r in self.inventory.valuation_rows()
        ]

    def _product_performance(self, filters: dict[str, Any], *, slow: bool = False,
                             best: bool = False) -> list[dict[str, Any]]:
        rows = self.finance.product_performance(
            filters["start"], filters["end"], limit=int(filters.get("limit", 100)), slow_moving=slow
        )
        return [
            {
                "name": r["name"], "sku": r["sku"], "qty_sold": r["qty_sold"],
                "revenue": r["revenue"], "cost": r["cost"], "profit": r["profit"],
            }
            for r in rows
        ]

    def _customers(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["c.status='active'"]
        if filters.get("due_only"):
            where.append("c.current_due > 0")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT c.name, c.phone, c.address, c.opening_due,
                          COALESCE((SELECT SUM(s.grand_total) FROM sales s
                                     WHERE s.customer_id=c.id AND s.status<>'cancelled'),0) AS total_purchase,
                          COALESCE((SELECT SUM(s.paid_amount) FROM sales s
                                     WHERE s.customer_id=c.id AND s.status<>'cancelled'),0)
                        + COALESCE((SELECT SUM(p.amount) FROM customer_payments p
                                     WHERE p.customer_id=c.id),0) AS total_paid,
                          c.current_due
                     FROM customers c WHERE {' AND '.join(where)} ORDER BY c.current_due DESC, c.name""",
                (),
            )
        ]

    def _customer_payments(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["cp.payment_date BETWEEN :start AND :end"]
        if filters.get("customer_id"):
            where.append("cp.customer_id = :customer_id")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT cp.receipt_no, cp.payment_date, c.name AS customer,
                          COALESCE(s.invoice_no,'') AS invoice_no, pm.name AS method,
                          cp.reference, cp.amount
                     FROM customer_payments cp
                     JOIN customers c ON c.id=cp.customer_id
                     JOIN payment_methods pm ON pm.id=cp.payment_method_id
                     LEFT JOIN sales s ON s.id=cp.sale_id
                    WHERE {' AND '.join(where)} ORDER BY cp.payment_date, cp.id""",
                filters,
            )
        ]

    def _customer_ledger(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        customer_id = filters.get("customer_id")
        if not customer_id:
            raise ValidationError("কাস্টমার নির্বাচন করুন")
        ledger = CustomerService(self.db).ledger(
            int(customer_id), start=filters.get("start"), end=filters.get("end")
        )
        return [
            {
                "date": e["date"], "particulars": e["particulars"], "reference": e["reference"],
                "debit": e["debit"], "credit": e["credit"], "balance": e["balance"],
            }
            for e in ledger["entries"]
        ]

    def _suppliers(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["s.status='active'"]
        if filters.get("payable_only"):
            where.append("s.current_payable > 0")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT s.name, s.business_name, s.phone, s.opening_payable,
                          COALESCE((SELECT SUM(p.grand_total) FROM purchases p
                                     WHERE p.supplier_id=s.id AND p.status<>'cancelled'),0) AS total_purchase,
                          COALESCE((SELECT SUM(p.paid_amount) FROM purchases p
                                     WHERE p.supplier_id=s.id AND p.status<>'cancelled'),0)
                        + COALESCE((SELECT SUM(p.amount) FROM supplier_payments p
                                     WHERE p.supplier_id=s.id),0) AS total_paid,
                          s.current_payable
                     FROM suppliers s WHERE {' AND '.join(where)} ORDER BY s.current_payable DESC, s.name""",
                (),
            )
        ]

    def _supplier_payments(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["sp.payment_date BETWEEN :start AND :end"]
        if filters.get("supplier_id"):
            where.append("sp.supplier_id = :supplier_id")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT sp.receipt_no, sp.payment_date, s.name AS supplier,
                          COALESCE(p.invoice_no,'') AS invoice_no, pm.name AS method,
                          sp.reference, sp.amount
                     FROM supplier_payments sp
                     JOIN suppliers s ON s.id=sp.supplier_id
                     JOIN payment_methods pm ON pm.id=sp.payment_method_id
                     LEFT JOIN purchases p ON p.id=sp.purchase_id
                    WHERE {' AND '.join(where)} ORDER BY sp.payment_date, sp.id""",
                filters,
            )
        ]

    def _supplier_ledger(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        supplier_id = filters.get("supplier_id")
        if not supplier_id:
            raise ValidationError("সাপ্লায়ার নির্বাচন করুন")
        ledger = SupplierService(self.db).ledger(
            int(supplier_id), start=filters.get("start"), end=filters.get("end")
        )
        return [
            {
                "date": e["date"], "particulars": e["particulars"], "reference": e["reference"],
                "debit": e["debit"], "credit": e["credit"], "balance": e["balance"],
            }
            for e in ledger["entries"]
        ]

    def _sales_returns(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT r.return_no, r.return_date, s.invoice_no,
                          COALESCE(c.name,'ওয়াক-ইন') AS customer, r.total_amount,
                          r.refund_amount, r.due_adjusted, r.cost_reversed,
                          r.write_off_cost, r.reason
                     FROM sales_returns r JOIN sales s ON s.id=r.sale_id
                     LEFT JOIN customers c ON c.id=r.customer_id
                    WHERE r.return_date BETWEEN :start AND :end ORDER BY r.return_date, r.id""",
                filters,
            )
        ]

    def _purchase_returns(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT r.return_no, r.return_date, p.invoice_no, s.name AS supplier,
                          r.total_amount, r.refund_amount, r.payable_adjusted, r.reason
                     FROM purchase_returns r JOIN purchases p ON p.id=r.purchase_id
                     JOIN suppliers s ON s.id=r.supplier_id
                    WHERE r.return_date BETWEEN :start AND :end ORDER BY r.return_date, r.id""",
                filters,
            )
        ]

    def _payments(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT * FROM (
                      SELECT s.sale_date AS date, s.invoice_no AS document, 'সেলস পেমেন্ট' AS kind,
                             COALESCE(c.name,'ওয়াক-ইন') AS party, pm.name AS method, sp.amount
                        FROM sale_payments sp JOIN sales s ON s.id=sp.sale_id
                        JOIN payment_methods pm ON pm.id=sp.payment_method_id
                        LEFT JOIN customers c ON c.id=s.customer_id
                       WHERE s.status<>'cancelled' AND s.sale_date BETWEEN :start AND :end
                      UNION ALL
                      SELECT cp.payment_date, cp.receipt_no, 'কাস্টমার কালেকশন', c.name, pm.name, cp.amount
                        FROM customer_payments cp JOIN customers c ON c.id=cp.customer_id
                        JOIN payment_methods pm ON pm.id=cp.payment_method_id
                       WHERE cp.payment_date BETWEEN :start AND :end
                      UNION ALL
                      SELECT p.purchase_date, p.invoice_no, 'পারচেজ পেমেন্ট', s.name, pm.name, -pp.amount
                        FROM purchase_payments pp JOIN purchases p ON p.id=pp.purchase_id
                        JOIN payment_methods pm ON pm.id=pp.payment_method_id
                        JOIN suppliers s ON s.id=p.supplier_id
                       WHERE p.status<>'cancelled' AND p.purchase_date BETWEEN :start AND :end
                      UNION ALL
                      SELECT sp.payment_date, sp.receipt_no, 'সাপ্লায়ার পেমেন্ট', s.name, pm.name, -sp.amount
                        FROM supplier_payments sp JOIN suppliers s ON s.id=sp.supplier_id
                        JOIN payment_methods pm ON pm.id=sp.payment_method_id
                       WHERE sp.payment_date BETWEEN :start AND :end
                    ) ORDER BY date, document""",
                filters,
            )
        ]

    def _cash_register(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT date(cs.opened_at) AS date, cr.name AS register, cs.opened_at,
                          cs.closed_at, cs.opening_cash, COALESCE(cs.expected_cash,0) AS expected_cash,
                          COALESCE(cs.actual_cash,0) AS actual_cash, COALESCE(cs.difference,0) AS difference,
                          cs.status, cs.opened_by
                     FROM cash_sessions cs JOIN cash_registers cr ON cr.id=cs.register_id
                    WHERE date(cs.opened_at) BETWEEN :start AND :end ORDER BY cs.id DESC""",
                filters,
            )
        ]

    def _cash_in_out(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT date(cm.movement_at) AS date, cm.movement_type, cm.notes,
                          cm.reference_type, cm.amount, cm.session_id
                     FROM cash_movements cm
                    WHERE date(cm.movement_at) BETWEEN :start AND :end
                    ORDER BY cm.id DESC""",
                filters,
            )
        ]

    def _discount(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT s.invoice_no, s.sale_date, COALESCE(c.name,'ওয়াক-ইন') AS customer,
                          s.subtotal AS gross_sales, s.item_discount, s.invoice_discount,
                          s.item_discount + s.invoice_discount AS total_discount, s.grand_total
                     FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                    WHERE s.status<>'cancelled' AND s.sale_date BETWEEN :start AND :end
                      AND (s.item_discount + s.invoice_discount) > 0
                    ORDER BY s.sale_date, s.id""",
                filters,
            )
        ]

    def _tax(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT s.invoice_no, s.sale_date, si.product_name, si.net_amount AS taxable_amount,
                          si.tax_bp, si.tax_amount
                     FROM sale_items si JOIN sales s ON s.id=si.sale_id
                    WHERE s.status<>'cancelled' AND s.sale_date BETWEEN :start AND :end
                      AND si.tax_amount > 0 ORDER BY s.sale_date, si.id""",
                filters,
            )
        ]

    def _transactions(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where = ["txn_date BETWEEN :start AND :end"]
        if filters.get("txn_type"):
            where.append("txn_type = :txn_type")
        if filters.get("query"):
            where.append("(txn_no LIKE '%' || :query || '%' OR party_name LIKE '%' || :query || '%')")
        return [
            dict(r) for r in self.db.query(
                f"""SELECT txn_date, txn_type, txn_no, party_name, amount, paid_amount,
                          due_amount, payment_summary, status
                     FROM transactions WHERE {' AND '.join(where)} ORDER BY id DESC""",
                filters,
            )
        ]

    # -------------------------------------------------------------- registry
    def _build_registry(self) -> dict[str, ReportDefinition]:
        sales_period_cols = [
            Column("period", "সময়কাল", "text"), _int("invoice_count", "ইনভয়েস সংখ্যা", True),
            _money("gross_sales", "মোট সেলস"), _money("discount", "ডিস্কাউন্ট"),
            _money("tax", "ট্যাক্স"), _money("net_total", "নেট টোটাল"),
            _money("paid", "পরিশোধিত"), _money("due", "বাকি"),
            _money("cost", "খরচ (COGS)"), _money("profit", "লাভ"),
        ]
        sales_detail_cols = [
            Column("invoice_no", "ইনভয়েস নং"), Column("sale_date", "তারিখ", "date"),
            Column("customer", "কাস্টমার"), _money("gross_sales", "মোট সেলস"),
            _money("discount", "ডিস্কাউন্ট"), _money("tax", "ট্যাক্স"),
            _money("net_total", "নেট টোটাল"), _money("paid", "পরিশোধিত"),
            _money("due", "বাকি"), Column("status", "স্ট্যাটাস"),
        ]
        pnl_cols = [Column("particulars", "বিবরণ"), _money("amount", "পরিমাণ", False)]
        party_cols = lambda party: [  # noqa: E731
            Column("name", "নাম"), Column("phone", "মোবাইল"),
            _money("opening_due" if party == "customer" else "opening_payable", "ওপেনিং ব্যালেন্স"),
            _money("total_purchase", "মোট ক্রয়"), _money("total_paid", "মোট পরিশোধ"),
            _money("current_due" if party == "customer" else "current_payable",
                   "বর্তমান বাকি" if party == "customer" else "বর্তমান দেয়"),
        ]
        ledger_cols = [
            Column("date", "তারিখ", "date"), Column("particulars", "বিবরণ"),
            Column("reference", "রেফারেন্স"), _money("debit", "ডেবিট"),
            _money("credit", "ক্রেডিট"), _money("balance", "ব্যালেন্স", False),
        ]
        stock_cols = [
            Column("name", "প্রোডাক্ট"), Column("sku", "এসকেইউ"), Column("category", "ক্যাটাগরি"),
            Column("unit", "ইউনিট"), _qty("stock_qty", "মজুদ"), _qty("min_stock_qty", "মিনিমাম", False),
            _money("avg_cost", "গড় খরচ", False), _money("stock_value", "স্টক মূল্য"),
            _money("selling_price", "বিক্রয় মূল্য", False),
        ]
        perf_cols = [
            Column("name", "প্রোডাক্ট"), Column("sku", "এসকেইউ"), _qty("qty_sold", "বিক্রীত পরিমাণ"),
            _money("revenue", "আয়"), _money("cost", "খরচ"), _money("profit", "লাভ"),
        ]

        definitions = [
            ReportDefinition("daily_sales", "দৈনিক সেলস রিপোর্ট", "সেলস", sales_period_cols,
                             lambda s, f: s._sales_period(f, "day")),
            ReportDefinition("weekly_sales", "সাপ্তাহিক সেলস রিপোর্ট", "সেলস", sales_period_cols,
                             lambda s, f: s._sales_period(f, "week")),
            ReportDefinition("monthly_sales", "মাসিক সেলস রিপোর্ট", "সেলস", sales_period_cols,
                             lambda s, f: s._sales_period(f, "month")),
            ReportDefinition("yearly_sales", "বার্ষিক সেলস রিপোর্ট", "সেলস", sales_period_cols,
                             lambda s, f: s._sales_period(f, "year")),
            ReportDefinition("custom_sales", "কাস্টম রেঞ্জ সেলস রিপোর্ট", "সেলস", sales_detail_cols,
                             lambda s, f: s._sales_detail(f),
                             filters=("start", "end", "customer_id", "status")),
            ReportDefinition("profit_loss", "প্রফিট / লস রিপোর্ট", "হিসাব", pnl_cols,
                             lambda s, f: s._pnl_rows(f, "full")),
            ReportDefinition("gross_profit", "গ্রস প্রফিট রিপোর্ট", "হিসাব", pnl_cols,
                             lambda s, f: s._pnl_rows(f, "gross")),
            ReportDefinition("net_profit", "নেট প্রফিট রিপোর্ট", "হিসাব", pnl_cols,
                             lambda s, f: s._pnl_rows(f, "net")),
            ReportDefinition("expense", "এক্সপেন্স রিপোর্ট", "হিসাব",
                             [Column("voucher_no", "ভাউচার নং"), Column("expense_date", "তারিখ", "date"),
                              Column("category", "ক্যাটাগরি"), Column("method", "পেমেন্ট মেথড"),
                              Column("description", "বিবরণ"), _money("amount", "পরিমাণ")],
                             lambda s, f: s._expense(f), filters=("start", "end", "category_id")),
            ReportDefinition("purchase", "পারচেজ রিপোর্ট", "পারচেজ",
                             [Column("invoice_no", "পারচেজ নং"), Column("purchase_date", "তারিখ", "date"),
                              Column("supplier", "সাপ্লায়ার"), Column("supplier_invoice_no", "সাপ্লায়ার ইনভয়েস"),
                              _money("gross_amount", "মোট"), _money("discount", "ডিস্কাউন্ট"),
                              _money("net_total", "নেট টোটাল"), _money("paid", "পরিশোধিত"),
                              _money("due", "বাকি"), Column("status", "স্ট্যাটাস")],
                             lambda s, f: s._purchase(f), filters=("start", "end", "supplier_id")),
            ReportDefinition("stock", "স্টক রিপোর্ট", "ইনভেন্টরি", stock_cols,
                             lambda s, f: s._stock(f), filters=("category_id", "stock_filter")),
            ReportDefinition("low_stock", "লো স্টক রিপোর্ট", "ইনভেন্টরি", stock_cols,
                             lambda s, f: s._stock({**f, "stock_filter": "low"}),
                             filters=("category_id",)),
            ReportDefinition("out_of_stock", "স্টক আউট রিপোর্ট", "ইনভেন্টরি", stock_cols,
                             lambda s, f: s._stock({**f, "stock_filter": "out"}),
                             filters=("category_id",)),
            ReportDefinition("stock_movement", "স্টক মুভমেন্ট রিপোর্ট", "ইনভেন্টরি",
                             [Column("movement_date", "তারিখ", "date"), Column("product", "প্রোডাক্ট"),
                              Column("sku", "এসকেইউ"), Column("movement_type", "ধরন"),
                              _qty("qty_delta", "পরিমাণ পরিবর্তন"), _qty("qty_before", "পূর্বের মজুদ", False),
                              _qty("qty_after", "পরবর্তী মজুদ", False), _money("unit_cost", "একক খরচ", False),
                              _money("value_delta", "মূল্য পরিবর্তন"), Column("reference_type", "রেফারেন্স"),
                              Column("notes", "নোট")],
                             lambda s, f: s._stock_movement(f),
                             filters=("start", "end", "product_id", "movement_type")),
            ReportDefinition("inventory_valuation", "ইনভেন্টরি ভ্যালুয়েশন রিপোর্ট", "ইনভেন্টরি",
                             [Column("name", "প্রোডাক্ট"), Column("sku", "এসকেইউ"), Column("unit", "ইউনিট"),
                              _qty("stock_qty", "মজুদ"), _money("avg_cost", "গড় খরচ", False),
                              _money("stock_value", "স্টক মূল্য")],
                             lambda s, f: s._valuation(f), filters=()),
            ReportDefinition("product_performance", "প্রোডাক্ট পারফরম্যান্স রিপোর্ট", "সেলস", perf_cols,
                             lambda s, f: s._product_performance(f)),
            ReportDefinition("best_selling", "বেস্ট সেলিং প্রোডাক্ট রিপোর্ট", "সেলস", perf_cols,
                             lambda s, f: s._product_performance(f, best=True)),
            ReportDefinition("slow_moving", "স্লো মুভিং প্রোডাক্ট রিপোর্ট", "সেলস", perf_cols,
                             lambda s, f: s._product_performance(f, slow=True)),
            ReportDefinition("customer", "কাস্টমার রিপোর্ট", "কাস্টমার", party_cols("customer"),
                             lambda s, f: s._customers(f), filters=("due_only",)),
            ReportDefinition("customer_due", "কাস্টমার ডিউ রিপোর্ট", "কাস্টমার", party_cols("customer"),
                             lambda s, f: s._customers({**f, "due_only": True}), filters=()),
            ReportDefinition("customer_payment", "কাস্টমার পেমেন্ট রিপোর্ট", "কাস্টমার",
                             [Column("receipt_no", "রিসিট নং"), Column("payment_date", "তারিখ", "date"),
                              Column("customer", "কাস্টমার"), Column("invoice_no", "ইনভয়েস"),
                              Column("method", "পেমেন্ট মেথড"), Column("reference", "রেফারেন্স"),
                              _money("amount", "পরিমাণ")],
                             lambda s, f: s._customer_payments(f),
                             filters=("start", "end", "customer_id")),
            ReportDefinition("customer_ledger", "কাস্টমার লেজার", "কাস্টমার", ledger_cols,
                             lambda s, f: s._customer_ledger(f),
                             filters=("start", "end", "customer_id")),
            ReportDefinition("supplier", "সাপ্লায়ার রিপোর্ট", "সাপ্লায়ার", party_cols("supplier"),
                             lambda s, f: s._suppliers(f), filters=("payable_only",)),
            ReportDefinition("supplier_payable", "সাপ্লায়ার পেয়েবল রিপোর্ট", "সাপ্লায়ার",
                             party_cols("supplier"),
                             lambda s, f: s._suppliers({**f, "payable_only": True}), filters=()),
            ReportDefinition("supplier_payment", "সাপ্লায়ার পেমেন্ট রিপোর্ট", "সাপ্লায়ার",
                             [Column("receipt_no", "রিসিট নং"), Column("payment_date", "তারিখ", "date"),
                              Column("supplier", "সাপ্লায়ার"), Column("invoice_no", "পারচেজ নং"),
                              Column("method", "পেমেন্ট মেথড"), Column("reference", "রেফারেন্স"),
                              _money("amount", "পরিমাণ")],
                             lambda s, f: s._supplier_payments(f),
                             filters=("start", "end", "supplier_id")),
            ReportDefinition("supplier_ledger", "সাপ্লায়ার লেজার", "সাপ্লায়ার", ledger_cols,
                             lambda s, f: s._supplier_ledger(f),
                             filters=("start", "end", "supplier_id")),
            ReportDefinition("sales_return", "সেলস রিটার্ন রিপোর্ট", "রিটার্ন",
                             [Column("return_no", "রিটার্ন নং"), Column("return_date", "তারিখ", "date"),
                              Column("invoice_no", "ইনভয়েস"), Column("customer", "কাস্টমার"),
                              _money("total_amount", "রিটার্ন মূল্য"), _money("refund_amount", "রিফান্ড"),
                              _money("due_adjusted", "বাকি সমন্বয়"), _money("cost_reversed", "ফেরত খরচ"),
                              _money("write_off_cost", "রাইট-অফ"), Column("reason", "কারণ")],
                             lambda s, f: s._sales_returns(f)),
            ReportDefinition("purchase_return", "পারচেজ রিটার্ন রিপোর্ট", "রিটার্ন",
                             [Column("return_no", "রিটার্ন নং"), Column("return_date", "তারিখ", "date"),
                              Column("invoice_no", "পারচেজ নং"), Column("supplier", "সাপ্লায়ার"),
                              _money("total_amount", "রিটার্ন মূল্য"), _money("refund_amount", "রিফান্ড"),
                              _money("payable_adjusted", "দেয় সমন্বয়"), Column("reason", "কারণ")],
                             lambda s, f: s._purchase_returns(f)),
            ReportDefinition("payment", "পেমেন্ট রিপোর্ট", "হিসাব",
                             [Column("date", "তারিখ", "date"), Column("document", "ডকুমেন্ট"),
                              Column("kind", "ধরন"), Column("party", "পার্টি"),
                              Column("method", "পেমেন্ট মেথড"), _money("amount", "পরিমাণ")],
                             lambda s, f: s._payments(f)),
            ReportDefinition("cash_register", "ক্যাশ রেজিস্টার রিপোর্ট", "ক্যাশ",
                             [Column("date", "তারিখ", "date"), Column("register", "রেজিস্টার"),
                              Column("opened_at", "শুরু"), Column("closed_at", "শেষ"),
                              _money("opening_cash", "ওপেনিং ক্যাশ"), _money("expected_cash", "প্রত্যাশিত"),
                              _money("actual_cash", "প্রকৃত"), _money("difference", "পার্থক্য"),
                              Column("status", "স্ট্যাটাস"), Column("opened_by", "দায়িত্বে")],
                             lambda s, f: s._cash_register(f)),
            ReportDefinition("cash_in_out", "ক্যাশ ইন / আউট রিপোর্ট", "ক্যাশ",
                             [Column("date", "তারিখ", "date"), Column("movement_type", "ধরন"),
                              Column("notes", "বিবরণ"), Column("reference_type", "রেফারেন্স"),
                              _money("amount", "পরিমাণ"), _int("session_id", "শিফট", False)],
                             lambda s, f: s._cash_in_out(f)),
            ReportDefinition("discount", "ডিস্কাউন্ট রিপোর্ট", "সেলস",
                             [Column("invoice_no", "ইনভয়েস"), Column("sale_date", "তারিখ", "date"),
                              Column("customer", "কাস্টমার"), _money("gross_sales", "মোট সেলস"),
                              _money("item_discount", "আইটেম ডিস্কাউন্ট"),
                              _money("invoice_discount", "ইনভয়েস ডিস্কাউন্ট"),
                              _money("total_discount", "মোট ডিস্কাউন্ট"), _money("grand_total", "নেট টোটাল")],
                             lambda s, f: s._discount(f)),
            ReportDefinition("tax", "ট্যাক্স রিপোর্ট", "হিসাব",
                             [Column("invoice_no", "ইনভয়েস"), Column("sale_date", "তারিখ", "date"),
                              Column("product_name", "প্রোডাক্ট"), _money("taxable_amount", "ট্যাক্সযোগ্য"),
                              _int("tax_bp", "হার (bp)"), _money("tax_amount", "ট্যাক্স")],
                             lambda s, f: s._tax(f)),
            ReportDefinition("transaction_history", "ট্রানজেকশন হিস্ট্রি রিপোর্ট", "হিসাব",
                             [Column("txn_date", "তারিখ", "date"), Column("txn_type", "ধরন"),
                              Column("txn_no", "ডকুমেন্ট নং"), Column("party_name", "পার্টি"),
                              _money("amount", "পরিমাণ"), _money("paid_amount", "পরিশোধিত"),
                              _money("due_amount", "বাকি"), Column("payment_summary", "মেথড"),
                              Column("status", "স্ট্যাটাস")],
                             lambda s, f: s._transactions(f),
                             filters=("start", "end", "txn_type", "query")),
        ]
        return {d.id: d for d in definitions}
