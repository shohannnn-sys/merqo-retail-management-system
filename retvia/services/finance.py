"""Centralized financial engine: COGS, profit, dashboard KPIs and reconciliation.

Every number here is derived from the live database with the same policy used by
the transaction services, so the dashboard, the profit report and the ledgers
always agree for the same date range.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..core.validation import validate_date_range
from ..data.db import Database
from .inventory import InventoryService
from .settings import SettingsService

# Revenue portion of a returned line, excluding the tax that was collected.
_RETURN_REVENUE_SQL = """
    CASE WHEN (si.net_amount + si.tax_amount) > 0
         THEN (sri.amount * si.net_amount) / (si.net_amount + si.tax_amount)
         ELSE sri.amount END
"""


def today() -> str:
    return date.today().isoformat()


def date_range_for(preset: str, *, reference: date | None = None) -> tuple[str, str]:
    """Resolve a dashboard preset into an ISO date range."""
    ref = reference or date.today()
    if preset == "today":
        return ref.isoformat(), ref.isoformat()
    if preset == "yesterday":
        y = ref - timedelta(days=1)
        return y.isoformat(), y.isoformat()
    if preset == "this_week":
        start = ref - timedelta(days=ref.weekday())
        return start.isoformat(), ref.isoformat()
    if preset == "this_month":
        return ref.replace(day=1).isoformat(), ref.isoformat()
    if preset == "this_year":
        return ref.replace(month=1, day=1).isoformat(), ref.isoformat()
    if preset == "last_30":
        return (ref - timedelta(days=29)).isoformat(), ref.isoformat()
    raise ValueError(f"অজানা ডেট প্রিসেট: {preset}")


class FinanceService:
    def __init__(
        self,
        db: Database,
        settings: SettingsService | None = None,
        inventory: InventoryService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.inventory = inventory or InventoryService(db, self.settings)

    # ------------------------------------------------------------ components
    def sales_components(self, start: str, end: str) -> dict[str, int]:
        row = self.db.query_one(
            """SELECT
                 COALESCE(SUM(si.gross_amount),0)               AS gross_sales,
                 COALESCE(SUM(si.discount_amount),0)            AS item_discount,
                 COALESCE(SUM(si.invoice_discount_allocated),0) AS invoice_discount,
                 COALESCE(SUM(si.net_amount),0)                 AS net_before_returns,
                 COALESCE(SUM(si.tax_amount),0)                 AS tax_collected,
                 COALESCE(SUM(si.total_cost),0)                 AS gross_cogs,
                 COUNT(DISTINCT s.id)                           AS sale_count,
                 COALESCE(SUM(s.grand_total),0)                 AS grand_total,
                 COALESCE(SUM(s.paid_amount),0)                 AS paid_at_sale,
                 COALESCE(SUM(s.due_amount),0)                  AS due_created
               FROM sales s JOIN sale_items si ON si.sale_id = s.id
              WHERE s.status <> 'cancelled' AND s.sale_date BETWEEN ? AND ?""",
            (start, end),
        )
        return {k: int(row[k]) for k in row.keys()} if row else {}  # noqa: SIM118 - sqlite3.Row

    def return_components(self, start: str, end: str) -> dict[str, int]:
        row = self.db.query_one(
            f"""SELECT
                  COALESCE(SUM({_RETURN_REVENUE_SQL}),0) AS returned_revenue,
                  COALESCE(SUM(sri.amount),0)            AS returned_total,
                  COALESCE(SUM(CASE WHEN sri.condition='restock' THEN sri.cost_amount ELSE 0 END),0)
                                                         AS cost_reversed,
                  COALESCE(SUM(CASE WHEN sri.condition<>'restock' THEN sri.cost_amount ELSE 0 END),0)
                                                         AS write_off_cost
                FROM sales_returns r
                JOIN sales_return_items sri ON sri.return_id = r.id
                JOIN sale_items si ON si.id = sri.sale_item_id
               WHERE r.return_date BETWEEN ? AND ?""",
            (start, end),
        )
        data = {k: int(row[k]) for k in row.keys()} if row else {}  # noqa: SIM118 - sqlite3.Row
        data["returned_tax"] = data.get("returned_total", 0) - data.get("returned_revenue", 0)
        return data

    def profit_and_loss(self, start: str, end: str) -> dict[str, Any]:
        start, end = validate_date_range(start, end)
        sales = self.sales_components(start, end)
        returns = self.return_components(start, end)
        gross_sales = sales.get("gross_sales", 0)
        discounts = sales.get("item_discount", 0) + sales.get("invoice_discount", 0)
        returned_revenue = returns.get("returned_revenue", 0)
        net_sales = gross_sales - discounts - returned_revenue
        cogs = sales.get("gross_cogs", 0) - returns.get("cost_reversed", 0)
        gross_profit = net_sales - cogs
        operating_expense = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        stock_write_off = self.inventory.write_off_value(start, end)
        return_write_off = returns.get("write_off_cost", 0)
        total_write_off = stock_write_off + return_write_off
        net_profit = gross_profit - operating_expense - total_write_off
        purchase_value = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(grand_total),0) FROM purchases "
                "WHERE status<>'cancelled' AND purchase_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        return {
            "start": start,
            "end": end,
            "gross_sales": gross_sales,
            "item_discount": sales.get("item_discount", 0),
            "invoice_discount": sales.get("invoice_discount", 0),
            "sales_discount": discounts,
            "sales_returns": returned_revenue,
            "net_sales": net_sales,
            "tax_collected": sales.get("tax_collected", 0) - returns.get("returned_tax", 0),
            "cogs": cogs,
            "gross_profit": gross_profit,
            "operating_expense": operating_expense,
            "stock_write_off": stock_write_off,
            "return_write_off": return_write_off,
            "total_write_off": total_write_off,
            "net_profit": net_profit,
            "estimated_profit": gross_profit,
            "sale_count": sales.get("sale_count", 0),
            "purchase_value": purchase_value,
            "gross_margin_bp": ((gross_profit * 10_000 // net_sales) if net_sales > 0 else 0),
        }

    def receivable_payable(self) -> dict[str, int]:
        return {
            "customer_receivable": int(
                self.db.scalar("SELECT COALESCE(SUM(MAX(current_due,0)),0) FROM customers")
            ),
            "customer_advance": int(
                self.db.scalar("SELECT COALESCE(SUM(MIN(current_due,0)),0) FROM customers")
            ),
            "supplier_payable": int(
                self.db.scalar("SELECT COALESCE(SUM(MAX(current_payable,0)),0) FROM suppliers")
            ),
            "supplier_advance": int(
                self.db.scalar("SELECT COALESCE(SUM(MIN(current_payable,0)),0) FROM suppliers")
            ),
        }

    def collections(self, start: str, end: str) -> dict[str, int]:
        at_sale = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(paid_amount),0) FROM sales "
                "WHERE status<>'cancelled' AND sale_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        later = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE payment_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        supplier_paid = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE payment_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        purchase_paid = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(paid_amount),0) FROM purchases "
                "WHERE status<>'cancelled' AND purchase_date BETWEEN ? AND ?",
                (start, end),
            )
        )
        return {
            "collected_at_sale": at_sale,
            "collected_later": later,
            "total_collection": at_sale + later,
            "paid_at_purchase": purchase_paid,
            "paid_later": supplier_paid,
            "total_supplier_payment": purchase_paid + supplier_paid,
        }

    # -------------------------------------------------------------- dashboard
    def dashboard(self, start: str, end: str) -> dict[str, Any]:
        start, end = validate_date_range(start, end)
        pnl = self.profit_and_loss(start, end)
        balances = self.receivable_payable()
        collections = self.collections(start, end)
        valuation = self.inventory.valuation()
        today_iso = today()
        today_sales = self.db.query_one(
            """SELECT COUNT(*) AS count, COALESCE(SUM(grand_total),0) AS amount
                 FROM sales WHERE status<>'cancelled' AND sale_date=?""",
            (today_iso,),
        )
        assert today_sales is not None  # an aggregate query always yields one row
        return {
            "range": {"start": start, "end": end},
            "today": {
                "sales_count": int(today_sales["count"]),
                "sales_amount": int(today_sales["amount"]),
            },
            "kpi": {
                "total_sales": pnl["gross_sales"] - pnl["sales_discount"],
                "gross_sales": pnl["gross_sales"],
                "sales_discount": pnl["sales_discount"],
                "sales_returns": pnl["sales_returns"],
                "net_sales": pnl["net_sales"],
                "gross_profit": pnl["gross_profit"],
                "net_profit": pnl["net_profit"],
                "estimated_profit": pnl["estimated_profit"],
                "total_purchase": pnl["purchase_value"],
                "total_expense": pnl["operating_expense"],
                "total_collection": collections["total_collection"],
                "customer_due": balances["customer_receivable"],
                "supplier_payable": balances["supplier_payable"],
                "stock_value": int(valuation["total_value"]),
                "sale_count": pnl["sale_count"],
                "low_stock_count": len(self.inventory.low_stock(limit=1000)),
                "out_of_stock_count": len(self.inventory.out_of_stock(limit=1000)),
            },
            "balances": balances,
            "collections": collections,
            "charts": {
                "sales_trend": self.sales_trend(start, end),
                "profit_trend": self.profit_trend(start, end),
                "purchase_trend": self.purchase_trend(start, end),
                "expense_overview": self.expense_overview(start, end),
                "product_performance": self.product_performance(start, end, limit=10),
                "payment_overview": self.payment_overview(start, end),
            },
            "recent_sales": self.recent_sales(10),
            "recent_transactions": self.recent_transactions(10),
            "recent_payments": self.recent_payments(10),
            "low_stock": self.inventory.low_stock(limit=10),
            "out_of_stock": self.inventory.out_of_stock(limit=10),
        }

    # ----------------------------------------------------------------- charts
    def sales_trend(self, start: str, end: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT sale_date AS label, COUNT(*) AS count,
                          COALESCE(SUM(grand_total),0) AS amount,
                          COALESCE(SUM(total_cost),0) AS cost
                     FROM sales WHERE status<>'cancelled' AND sale_date BETWEEN ? AND ?
                    GROUP BY sale_date ORDER BY sale_date""",
                (start, end),
            )
        ]

    def profit_trend(self, start: str, end: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT s.sale_date AS label,
                      COALESCE(SUM(si.net_amount),0) AS revenue,
                      COALESCE(SUM(si.total_cost),0) AS cost
                 FROM sales s JOIN sale_items si ON si.sale_id=s.id
                WHERE s.status<>'cancelled' AND s.sale_date BETWEEN ? AND ?
                GROUP BY s.sale_date ORDER BY s.sale_date""",
            (start, end),
        )
        expenses = {
            r["expense_date"]: int(r["total"])
            for r in self.db.query(
                "SELECT expense_date, SUM(amount) AS total FROM expenses "
                "WHERE expense_date BETWEEN ? AND ? GROUP BY expense_date",
                (start, end),
            )
        }
        return [
            {
                "label": r["label"],
                "revenue": int(r["revenue"]),
                "cost": int(r["cost"]),
                "gross_profit": int(r["revenue"]) - int(r["cost"]),
                "expense": expenses.get(r["label"], 0),
                "net_profit": int(r["revenue"]) - int(r["cost"]) - expenses.get(r["label"], 0),
            }
            for r in rows
        ]

    def purchase_trend(self, start: str, end: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT purchase_date AS label, COUNT(*) AS count,
                          COALESCE(SUM(grand_total),0) AS amount
                     FROM purchases WHERE status<>'cancelled' AND purchase_date BETWEEN ? AND ?
                    GROUP BY purchase_date ORDER BY purchase_date""",
                (start, end),
            )
        ]

    def expense_overview(self, start: str, end: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT ec.name AS label, COALESCE(SUM(e.amount),0) AS amount, COUNT(e.id) AS count
                     FROM expenses e JOIN expense_categories ec ON ec.id=e.category_id
                    WHERE e.expense_date BETWEEN ? AND ?
                    GROUP BY ec.id ORDER BY amount DESC""",
                (start, end),
            )
        ]

    def payment_overview(self, start: str, end: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT pm.name AS label, COALESCE(SUM(x.amount),0) AS amount, COUNT(*) AS count
                     FROM (
                        SELECT sp.payment_method_id, sp.amount FROM sale_payments sp
                          JOIN sales s ON s.id=sp.sale_id
                         WHERE s.status<>'cancelled' AND s.sale_date BETWEEN ? AND ?
                        UNION ALL
                        SELECT cp.payment_method_id, cp.amount FROM customer_payments cp
                         WHERE cp.payment_date BETWEEN ? AND ?
                     ) x JOIN payment_methods pm ON pm.id=x.payment_method_id
                    GROUP BY pm.id ORDER BY amount DESC""",
                (start, end, start, end),
            )
        ]

    def product_performance(
        self, start: str, end: str, *, limit: int = 50, slow_moving: bool = False
    ) -> list[dict[str, Any]]:
        order = "ASC" if slow_moving else "DESC"
        return [
            dict(r)
            for r in self.db.query(
                f"""SELECT p.id, p.name, p.sku,
                          COALESCE(SUM(si.quantity),0) AS qty_sold,
                          COALESCE(SUM(si.net_amount),0) AS revenue,
                          COALESCE(SUM(si.total_cost),0) AS cost,
                          COALESCE(SUM(si.net_amount),0) - COALESCE(SUM(si.total_cost),0) AS profit
                     FROM sale_items si
                     JOIN sales s ON s.id=si.sale_id
                     JOIN products p ON p.id=si.product_id
                    WHERE s.status<>'cancelled' AND s.sale_date BETWEEN ? AND ?
                    GROUP BY p.id ORDER BY qty_sold {order}, revenue {order} LIMIT ?""",
                (start, end, limit),
            )
        ]

    # ----------------------------------------------------------------- recent
    def recent_sales(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT s.id, s.invoice_no, s.sale_date, s.grand_total, s.due_amount, s.status,
                          c.name AS customer_name
                     FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                    ORDER BY s.id DESC LIMIT ?""",
                (limit,),
            )
        ]

    def recent_transactions(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query("SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,))
        ]

    def transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        txn_type: str | None = None,
        party_type: str = "",
        party_id: int | None = None,
        query: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Immutable financial transaction register with filters."""
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("txn_date >= ?")
            params.append(start)
        if end:
            where.append("txn_date <= ?")
            params.append(end)
        if txn_type:
            where.append("txn_type = ?")
            params.append(txn_type)
        if party_type:
            where.append("party_type = ?")
            params.append(party_type)
        if party_id is not None:
            where.append("party_id = ?")
            params.append(party_id)
        if query:
            where.append("(txn_no LIKE ? OR party_name LIKE ? OR notes LIKE ?)")
            pattern = f"%{query}%"
            params += [pattern, pattern, pattern]
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM transactions WHERE {clause}", params))
        rows = self.db.query(
            f"""SELECT * FROM transactions WHERE {clause}
                 ORDER BY txn_date DESC, id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def recent_payments(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT * FROM (
                      SELECT cp.receipt_no AS no, cp.payment_date AS date, cp.amount,
                             c.name AS party, 'customer_payment' AS kind
                        FROM customer_payments cp JOIN customers c ON c.id=cp.customer_id
                      UNION ALL
                      SELECT sp.receipt_no, sp.payment_date, sp.amount, s.name, 'supplier_payment'
                        FROM supplier_payments sp JOIN suppliers s ON s.id=sp.supplier_id
                    ) ORDER BY date DESC, no DESC LIMIT ?""",
                (limit,),
            )
        ]

    # --------------------------------------------------------- reconciliation
    def reconcile_all(self) -> dict[str, Any]:
        """Cross-check every ledger against its summary. Empty lists mean healthy."""
        from .parties import CustomerService, SupplierService

        problems: dict[str, Any] = {
            "inventory": self.inventory.reconcile(),
            "customers": CustomerService(self.db).reconcile(),
            "suppliers": SupplierService(self.db).reconcile(),
            "sale_payment_balance": [],
            "invoice_discount_allocation": [],
            "stock_movement_arithmetic": [],
            "orphan_transactions": [],
        }
        for r in self.db.query(
            "SELECT id, invoice_no, grand_total, paid_amount, due_amount FROM sales WHERE status<>'cancelled'"
        ):
            if int(r["paid_amount"]) + int(r["due_amount"]) != int(r["grand_total"]):
                problems["sale_payment_balance"].append(dict(r))
        for r in self.db.query(
            """SELECT s.id, s.invoice_no, s.invoice_discount,
                      COALESCE(SUM(si.invoice_discount_allocated),0) AS allocated,
                      s.subtotal - s.item_discount - s.invoice_discount AS expected_net,
                      COALESCE(SUM(si.net_amount),0) AS actual_net
                 FROM sales s JOIN sale_items si ON si.sale_id=s.id
                WHERE s.status<>'cancelled' GROUP BY s.id"""
        ):
            if int(r["invoice_discount"]) != int(r["allocated"]) or int(r["expected_net"]) != int(
                r["actual_net"]
            ):
                problems["invoice_discount_allocation"].append(dict(r))
        bad = int(
            self.db.scalar("SELECT COUNT(*) FROM stock_movements WHERE qty_before + qty_delta <> qty_after")
        )
        if bad:
            problems["stock_movement_arithmetic"].append({"invalid_rows": bad})
        integrity_ok, integrity_messages = self.db.integrity_check()
        return {
            "healthy": all(not v for v in problems.values()) and integrity_ok,
            "problems": {k: v for k, v in problems.items() if v},
            "integrity_check": integrity_messages,
            "foreign_key_violations": self.db.foreign_key_check(),
        }
