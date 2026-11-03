"""Expense categories and expense vouchers."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core.errors import BusinessRuleError, DuplicateError, NotFoundError, ValidationError
from ..core.textnorm import normalize_search
from ..core.validation import optional_text, require_id, require_text, validate_date
from ..data.db import Database
from .audit import AuditService
from .cash import CashService
from .numbering import NumberingService
from .settings import SettingsService


class ExpenseService:
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

    # ------------------------------------------------------------- categories
    def categories(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM expense_categories"
        if active_only:
            sql += " WHERE is_active=1"
        return [dict(r) for r in self.db.query(sql + " ORDER BY name")]

    def create_category(self, name: str) -> int:
        name = require_text(name, "এক্সপেন্স ক্যাটাগরি", max_length=120)
        normalized = normalize_search(name)
        if self.db.query_one("SELECT id FROM expense_categories WHERE name_normalized=?", (normalized,)):
            raise DuplicateError(f"'{name}' ক্যাটাগরি আগে থেকেই রয়েছে")
        with self.db.transaction():
            cid = self.db.insert(
                "INSERT INTO expense_categories (name, name_normalized) VALUES (?,?)",
                (name, normalized),
            )
            self.audit.log("expense_category", cid, "create", f"এক্সপেন্স ক্যাটাগরি: {name}")
        return cid

    def delete_category(self, category_id: int) -> None:
        if int(self.db.scalar("SELECT COUNT(*) FROM expenses WHERE category_id=?", (category_id,))):
            raise BusinessRuleError("এই ক্যাটাগরিতে এক্সপেন্স রয়েছে — মুছে ফেলা যাবে না")
        with self.db.transaction():
            self.db.execute("DELETE FROM expense_categories WHERE id=?", (category_id,))

    # ---------------------------------------------------------------- vouchers
    def create(
        self, *, category_id: int, amount: int, method_id: int,
        expense_date: str | date | None = None, description: str = "",
        reference: str = "", notes: str = "",
    ) -> dict[str, Any]:
        require_id(category_id, "এক্সপেন্স ক্যাটাগরি")
        require_id(method_id, "পেমেন্ট মেথড")
        if amount <= 0:
            raise ValidationError("এক্সপেন্সের পরিমাণ ধনাত্মক হতে হবে")
        category = self.db.query_one("SELECT * FROM expense_categories WHERE id=?", (category_id,))
        if category is None:
            raise NotFoundError("ক্যাটাগরি খুঁজে পাওয়া যায়নি")
        method = self.db.query_one(
            "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (method_id,)
        )
        if method is None:
            raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")
        day = validate_date(expense_date or date.today(), "এক্সপেন্সের তারিখ")

        with self.db.transaction():
            voucher_no = self.numbering.next_number("expense", on_date=day)
            session_id = self.cash.require_open_session() if method["is_cash"] else None
            expense_id = self.db.insert(
                """INSERT INTO expenses
                   (voucher_no, category_id, amount, expense_date, payment_method_id,
                    description, reference, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    voucher_no, category_id, amount, day, method_id,
                    optional_text(description, max_length=500),
                    optional_text(reference, max_length=120),
                    optional_text(notes, max_length=500), session_id,
                ),
            )
            if method["is_cash"] and session_id is not None:
                self.cash.record_movement(
                    session_id=session_id, movement_type="expense", amount=-amount,
                    payment_method_id=method_id, reference_type="expense",
                    reference_id=expense_id, notes=voucher_no,
                )
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('expense', ?, ?, 'expense', ?, ?, ?, ?, 0, ?, 'expense', ?, ?)""",
                (
                    voucher_no, day, category_id, category["name"], amount, amount,
                    method["name"], expense_id, optional_text(description, max_length=300),
                ),
            )
            self.audit.log(
                "expense", expense_id, "create",
                f"এক্সপেন্স {voucher_no} — {category['name']} {amount}",
            )
        return {"id": expense_id, "voucher_no": voucher_no, "amount": amount}

    def delete(self, expense_id: int, *, reason: str) -> None:
        """Reverse an expense with an audit entry rather than erasing history."""
        expense = self.db.query_one("SELECT * FROM expenses WHERE id=?", (expense_id,))
        if expense is None:
            raise NotFoundError("এক্সপেন্স খুঁজে পাওয়া যায়নি")
        reason = require_text(reason, "বাতিলের কারণ", max_length=300)
        with self.db.transaction():
            method = self.db.query_one(
                "SELECT is_cash FROM payment_methods WHERE id=?", (expense["payment_method_id"],)
            )
            if method is not None and method["is_cash"]:
                session_id = self.cash.require_open_session()
                self.cash.record_movement(
                    session_id=session_id, movement_type="cash_in", amount=int(expense["amount"]),
                    reference_type="expense_cancel", reference_id=expense_id,
                    notes=f"এক্সপেন্স বাতিল: {expense['voucher_no']} — {reason}",
                )
            self.db.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
            self.db.execute(
                "UPDATE transactions SET status='cancelled' WHERE txn_type='expense' AND reference_id=?",
                (expense_id,),
            )
            self.audit.log(
                "expense", expense_id, "cancel",
                f"এক্সপেন্স বাতিল {expense['voucher_no']} — {reason}",
                before={"amount": int(expense["amount"])},
            )

    def search(
        self, *, start: str | None = None, end: str | None = None,
        category_id: int | None = None, method_id: int | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("e.expense_date >= ?")
            params.append(start)
        if end:
            where.append("e.expense_date <= ?")
            params.append(end)
        if category_id is not None:
            where.append("e.category_id = ?")
            params.append(category_id)
        if method_id is not None:
            where.append("e.payment_method_id = ?")
            params.append(method_id)
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM expenses e WHERE {clause}", params))
        total_amount = int(self.db.scalar(
            f"SELECT COALESCE(SUM(e.amount),0) FROM expenses e WHERE {clause}", params
        ))
        rows = self.db.query(
            f"""SELECT e.*, ec.name AS category_name, pm.name AS method_name
                  FROM expenses e
                  JOIN expense_categories ec ON ec.id=e.category_id
                  JOIN payment_methods pm ON pm.id=e.payment_method_id
                 WHERE {clause} ORDER BY e.expense_date DESC, e.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total, "total_amount": total_amount}

    def by_category(self, start: str, end: str) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                """SELECT ec.id, ec.name, COALESCE(SUM(e.amount),0) AS total, COUNT(e.id) AS count
                     FROM expense_categories ec
                     LEFT JOIN expenses e ON e.category_id=ec.id AND e.expense_date BETWEEN ? AND ?
                    GROUP BY ec.id HAVING count > 0 ORDER BY total DESC""",
                (start, end),
            )
        ]

    def total(self, start: str, end: str) -> int:
        return int(self.db.scalar(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
            (start, end),
        ))
