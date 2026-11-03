"""Due collection and supplier payment services with invoice-level allocation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..core.errors import NotFoundError, ValidationError
from ..core.validation import optional_text, require_id, validate_date
from ..data.db import Database
from .audit import AuditService
from .cash import CashService
from .numbering import NumberingService
from .settings import SettingsService


class CustomerPaymentService:
    def __init__(
        self, db: Database, *, settings: SettingsService | None = None,
        audit: AuditService | None = None, numbering: NumberingService | None = None,
        cash: CashService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.numbering = numbering or NumberingService(db, self.settings)
        self.cash = cash or CashService(db, self.settings, self.audit)

    def invoice_outstanding(self, sale_id: int) -> int:
        row = self.db.query_one(
            "SELECT grand_total, paid_amount, status FROM sales WHERE id=?", (sale_id,)
        )
        if row is None:
            raise NotFoundError("ইনভয়েস খুঁজে পাওয়া যায়নি")
        if row["status"] == "cancelled":
            return 0
        allocated = int(self.db.scalar(
            "SELECT COALESCE(SUM(amount),0) FROM customer_payment_allocations WHERE sale_id=?",
            (sale_id,),
        ))
        returned = int(self.db.scalar(
            "SELECT COALESCE(SUM(due_adjusted),0) FROM sales_returns WHERE sale_id=?", (sale_id,)
        ))
        return max(0, int(row["grand_total"]) - int(row["paid_amount"]) - allocated - returned)

    def due_invoices(self, customer_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT s.id, s.invoice_no, s.sale_date, s.grand_total, s.paid_amount
                 FROM sales s WHERE s.customer_id=? AND s.status<>'cancelled'
                ORDER BY s.sale_date, s.id""",
            (customer_id,),
        )
        result = []
        for r in rows:
            outstanding = self.invoice_outstanding(int(r["id"]))
            if outstanding > 0:
                result.append({**dict(r), "outstanding": outstanding})
        return result

    def collect(
        self, *, customer_id: int, amount: int, method_id: int,
        sale_id: int | None = None, payment_date: str | date | None = None,
        reference: str = "", notes: str = "", allow_advance: bool = True,
    ) -> dict[str, Any]:
        require_id(customer_id, "কাস্টমার")
        require_id(method_id, "পেমেন্ট মেথড")
        if amount <= 0:
            raise ValidationError("পেমেন্টের পরিমাণ ধনাত্মক হতে হবে")
        customer = self.db.query_one("SELECT * FROM customers WHERE id=?", (customer_id,))
        if customer is None:
            raise NotFoundError("কাস্টমার খুঁজে পাওয়া যায়নি")
        method = self.db.query_one(
            "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (method_id,)
        )
        if method is None:
            raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")
        day = validate_date(payment_date or date.today(), "পেমেন্টের তারিখ")

        if sale_id is not None:
            sale = self.db.query_one(
                "SELECT id, customer_id, invoice_no FROM sales WHERE id=?", (sale_id,)
            )
            if sale is None:
                raise NotFoundError("ইনভয়েস খুঁজে পাওয়া যায়নি")
            if sale["customer_id"] != customer_id:
                raise ValidationError("এই ইনভয়েস নির্বাচিত কাস্টমারের নয়")
            outstanding = self.invoice_outstanding(sale_id)
            if amount > outstanding and not allow_advance:
                raise ValidationError("পেমেন্ট ইনভয়েসের বাকির চেয়ে বেশি হতে পারে না")
        else:
            outstanding = 0
            if not allow_advance and amount > int(customer["current_due"]):
                raise ValidationError("পেমেন্ট কাস্টমারের মোট বাকির চেয়ে বেশি হতে পারে না")

        allocation = min(amount, outstanding) if sale_id is not None else 0
        with self.db.transaction():
            receipt_no = self.numbering.next_number("customer_payment", on_date=day)
            session_id = None
            if method["is_cash"]:
                session_id = self.cash.require_open_session()
            payment_id = self.db.insert(
                """INSERT INTO customer_payments
                   (receipt_no, customer_id, sale_id, payment_method_id, amount, paid_at,
                    payment_date, reference, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt_no, customer_id, sale_id, method_id, amount,
                    datetime.now().isoformat(timespec="seconds"), day,
                    optional_text(reference, max_length=120), optional_text(notes, max_length=300),
                    session_id,
                ),
            )
            if allocation > 0 and sale_id is not None:
                self.db.insert(
                    "INSERT INTO customer_payment_allocations (payment_id, sale_id, amount) VALUES (?,?,?)",
                    (payment_id, sale_id, allocation),
                )
            self.db.execute(
                "UPDATE customers SET current_due = current_due - ? WHERE id=?", (amount, customer_id)
            )
            if method["is_cash"] and session_id is not None:
                self.cash.record_movement(
                    session_id=session_id, movement_type="customer_payment", amount=amount,
                    payment_method_id=method_id, reference_type="customer_payment",
                    reference_id=payment_id, notes=receipt_no,
                )
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('customer_payment', ?, ?, 'customer', ?, ?, ?, ?, 0, ?, 'customer_payment', ?, ?)""",
                (
                    receipt_no, day, customer_id, customer["name"], amount, amount,
                    method["name"], payment_id, optional_text(notes, max_length=300),
                ),
            )
            self.audit.log(
                "customer_payment", payment_id, "create",
                f"কালেকশন {receipt_no} — {customer['name']} {amount}",
                after={"amount": amount, "allocated": allocation},
            )
        new_due = int(self.db.scalar("SELECT current_due FROM customers WHERE id=?", (customer_id,)))
        return {
            "id": payment_id, "receipt_no": receipt_no, "amount": amount,
            "allocated": allocation, "current_due": new_due,
            "advance": max(0, -new_due),
        }

    def history(
        self, *, customer_id: int | None = None, start: str | None = None,
        end: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if customer_id is not None:
            where.append("cp.customer_id=?")
            params.append(customer_id)
        if start:
            where.append("cp.payment_date >= ?")
            params.append(start)
        if end:
            where.append("cp.payment_date <= ?")
            params.append(end)
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM customer_payments cp WHERE {clause}", params))
        rows = self.db.query(
            f"""SELECT cp.*, c.name AS customer_name, pm.name AS method_name, s.invoice_no
                  FROM customer_payments cp
                  JOIN customers c ON c.id=cp.customer_id
                  JOIN payment_methods pm ON pm.id=cp.payment_method_id
                  LEFT JOIN sales s ON s.id=cp.sale_id
                 WHERE {clause} ORDER BY cp.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}


class SupplierPaymentService:
    def __init__(
        self, db: Database, *, settings: SettingsService | None = None,
        audit: AuditService | None = None, numbering: NumberingService | None = None,
        cash: CashService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.numbering = numbering or NumberingService(db, self.settings)
        self.cash = cash or CashService(db, self.settings, self.audit)

    def purchase_outstanding(self, purchase_id: int) -> int:
        row = self.db.query_one(
            "SELECT grand_total, paid_amount, status FROM purchases WHERE id=?", (purchase_id,)
        )
        if row is None:
            raise NotFoundError("পারচেজ খুঁজে পাওয়া যায়নি")
        if row["status"] == "cancelled":
            return 0
        allocated = int(self.db.scalar(
            "SELECT COALESCE(SUM(amount),0) FROM supplier_payment_allocations WHERE purchase_id=?",
            (purchase_id,),
        ))
        returned = int(self.db.scalar(
            "SELECT COALESCE(SUM(payable_adjusted),0) FROM purchase_returns WHERE purchase_id=?",
            (purchase_id,),
        ))
        return max(0, int(row["grand_total"]) - int(row["paid_amount"]) - allocated - returned)

    def due_purchases(self, supplier_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT id, invoice_no, purchase_date, grand_total, paid_amount
                 FROM purchases WHERE supplier_id=? AND status<>'cancelled'
                ORDER BY purchase_date, id""",
            (supplier_id,),
        )
        result = []
        for r in rows:
            outstanding = self.purchase_outstanding(int(r["id"]))
            if outstanding > 0:
                result.append({**dict(r), "outstanding": outstanding})
        return result

    def pay(
        self, *, supplier_id: int, amount: int, method_id: int,
        purchase_id: int | None = None, payment_date: str | date | None = None,
        reference: str = "", notes: str = "",
    ) -> dict[str, Any]:
        require_id(supplier_id, "সাপ্লায়ার")
        require_id(method_id, "পেমেন্ট মেথড")
        if amount <= 0:
            raise ValidationError("পেমেন্টের পরিমাণ ধনাত্মক হতে হবে")
        supplier = self.db.query_one("SELECT * FROM suppliers WHERE id=?", (supplier_id,))
        if supplier is None:
            raise NotFoundError("সাপ্লায়ার খুঁজে পাওয়া যায়নি")
        method = self.db.query_one(
            "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (method_id,)
        )
        if method is None:
            raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")
        day = validate_date(payment_date or date.today(), "পেমেন্টের তারিখ")
        outstanding = 0
        if purchase_id is not None:
            purchase = self.db.query_one(
                "SELECT id, supplier_id FROM purchases WHERE id=?", (purchase_id,)
            )
            if purchase is None:
                raise NotFoundError("পারচেজ খুঁজে পাওয়া যায়নি")
            if purchase["supplier_id"] != supplier_id:
                raise ValidationError("এই পারচেজ নির্বাচিত সাপ্লায়ারের নয়")
            outstanding = self.purchase_outstanding(purchase_id)
        allocation = min(amount, outstanding) if purchase_id is not None else 0

        with self.db.transaction():
            receipt_no = self.numbering.next_number("supplier_payment", on_date=day)
            session_id = self.cash.require_open_session() if method["is_cash"] else None
            payment_id = self.db.insert(
                """INSERT INTO supplier_payments
                   (receipt_no, supplier_id, purchase_id, payment_method_id, amount, paid_at,
                    payment_date, reference, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt_no, supplier_id, purchase_id, method_id, amount,
                    datetime.now().isoformat(timespec="seconds"), day,
                    optional_text(reference, max_length=120), optional_text(notes, max_length=300),
                    session_id,
                ),
            )
            if allocation > 0 and purchase_id is not None:
                self.db.insert(
                    "INSERT INTO supplier_payment_allocations (payment_id, purchase_id, amount) VALUES (?,?,?)",
                    (payment_id, purchase_id, allocation),
                )
            self.db.execute(
                "UPDATE suppliers SET current_payable = current_payable - ? WHERE id=?",
                (amount, supplier_id),
            )
            if method["is_cash"] and session_id is not None:
                self.cash.record_movement(
                    session_id=session_id, movement_type="supplier_payment", amount=-amount,
                    payment_method_id=method_id, reference_type="supplier_payment",
                    reference_id=payment_id, notes=receipt_no,
                )
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('supplier_payment', ?, ?, 'supplier', ?, ?, ?, ?, 0, ?, 'supplier_payment', ?, ?)""",
                (
                    receipt_no, day, supplier_id, supplier["name"], amount, amount,
                    method["name"], payment_id, optional_text(notes, max_length=300),
                ),
            )
            self.audit.log(
                "supplier_payment", payment_id, "create",
                f"সাপ্লায়ার পেমেন্ট {receipt_no} — {supplier['name']} {amount}",
            )
        new_payable = int(self.db.scalar("SELECT current_payable FROM suppliers WHERE id=?", (supplier_id,)))
        return {
            "id": payment_id, "receipt_no": receipt_no, "amount": amount,
            "allocated": allocation, "current_payable": new_payable,
        }

    def history(
        self, *, supplier_id: int | None = None, start: str | None = None,
        end: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if supplier_id is not None:
            where.append("sp.supplier_id=?")
            params.append(supplier_id)
        if start:
            where.append("sp.payment_date >= ?")
            params.append(start)
        if end:
            where.append("sp.payment_date <= ?")
            params.append(end)
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM supplier_payments sp WHERE {clause}", params))
        rows = self.db.query(
            f"""SELECT sp.*, s.name AS supplier_name, pm.name AS method_name, p.invoice_no
                  FROM supplier_payments sp
                  JOIN suppliers s ON s.id=sp.supplier_id
                  JOIN payment_methods pm ON pm.id=sp.payment_method_id
                  LEFT JOIN purchases p ON p.id=sp.purchase_id
                 WHERE {clause} ORDER BY sp.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}
