"""Customer and supplier services, including ledgers and statements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import BusinessRuleError, NotFoundError, ValidationError
from ..core.textnorm import normalize_search
from ..core.validation import (
    optional_text,
    require_id,
    require_text,
    validate_choice,
    validate_email,
    validate_phone,
)
from ..data.db import Database
from .audit import AuditService


@dataclass(slots=True)
class CustomerInput:
    name: str
    phone: str = ""
    address: str = ""
    email: str = ""
    opening_due: int = 0
    notes: str = ""


@dataclass(slots=True)
class SupplierInput:
    name: str
    business_name: str = ""
    contact_person: str = ""
    phone: str = ""
    address: str = ""
    email: str = ""
    opening_payable: int = 0
    notes: str = ""


class CustomerService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def create(self, data: CustomerInput) -> int:
        name = require_text(data.name, "কাস্টমারের নাম", max_length=200)
        phone = validate_phone(data.phone)
        if phone and self.db.query_one("SELECT id FROM customers WHERE phone=?", (phone,)):
            raise BusinessRuleError(f"'{phone}' নম্বরে ইতিমধ্যে একজন কাস্টমার রয়েছেন")
        with self.db.transaction():
            cid = self.db.insert(
                """INSERT INTO customers
                   (name, name_normalized, phone, address, email, opening_due, current_due, notes)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    name,
                    normalize_search(name),
                    phone,
                    optional_text(data.address, max_length=500),
                    validate_email(data.email),
                    data.opening_due,
                    data.opening_due,
                    optional_text(data.notes, max_length=1000),
                ),
            )
            self.audit.log(
                "customer",
                cid,
                "create",
                f"কাস্টমার তৈরি: {name}",
                after={"opening_due": data.opening_due},
            )
        return cid

    def update(self, customer_id: int, data: CustomerInput) -> None:
        require_id(customer_id, "কাস্টমার")
        self.get(customer_id)
        name = require_text(data.name, "কাস্টমারের নাম", max_length=200)
        phone = validate_phone(data.phone)
        if phone and self.db.query_one(
            "SELECT id FROM customers WHERE phone=? AND id<>?", (phone, customer_id)
        ):
            raise BusinessRuleError(f"'{phone}' নম্বরে ইতিমধ্যে একজন কাস্টমার রয়েছেন")
        with self.db.transaction():
            self.db.execute(
                """UPDATE customers SET name=?, name_normalized=?, phone=?, address=?, email=?,
                          notes=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (
                    name,
                    normalize_search(name),
                    phone,
                    optional_text(data.address, max_length=500),
                    validate_email(data.email),
                    optional_text(data.notes, max_length=1000),
                    customer_id,
                ),
            )
            self.audit.log("customer", customer_id, "update", f"কাস্টমার হালনাগাদ: {name}")

    def set_status(self, customer_id: int, status: str) -> None:
        validate_choice(status, ("active", "archived"), "স্ট্যাটাস")
        with self.db.transaction():
            self.db.execute("UPDATE customers SET status=? WHERE id=?", (status, customer_id))
            self.audit.log("customer", customer_id, "status", f"স্ট্যাটাস: {status}")

    def delete(self, customer_id: int) -> None:
        require_id(customer_id, "কাস্টমার")
        sales = int(self.db.scalar("SELECT COUNT(*) FROM sales WHERE customer_id=?", (customer_id,)))
        payments = int(
            self.db.scalar("SELECT COUNT(*) FROM customer_payments WHERE customer_id=?", (customer_id,))
        )
        if sales or payments:
            raise BusinessRuleError("এই কাস্টমারের লেনদেন হিস্ট্রি রয়েছে — মুছে না ফেলে আর্কাইভ করুন")
        with self.db.transaction():
            self.db.execute("DELETE FROM customers WHERE id=?", (customer_id,))
            self.audit.log("customer", customer_id, "delete", "কাস্টমার মুছে ফেলা হয়েছে")

    def get(self, customer_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM customers WHERE id=?", (customer_id,))
        if row is None:
            raise NotFoundError("কাস্টমার খুঁজে পাওয়া যায়নি")
        return dict(row)

    def search(
        self,
        *,
        query: str = "",
        status: str = "active",
        due_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if status and status != "all":
            where.append("status=?")
            params.append(status)
        if query:
            term = f"%{normalize_search(query)}%"
            where.append("(name_normalized LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')")
            params.extend([term, term])
        if due_only:
            where.append("current_due > 0")
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM customers WHERE {clause}", params))
        rows = self.db.query(
            f"SELECT * FROM customers WHERE {clause} ORDER BY name_normalized LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def totals(self, customer_id: int) -> dict[str, int]:
        purchased = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(grand_total),0) FROM sales WHERE customer_id=? AND status<>'cancelled'",
                (customer_id,),
            )
        )
        paid_at_sale = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(paid_amount),0) FROM sales WHERE customer_id=? AND status<>'cancelled'",
                (customer_id,),
            )
        )
        collected = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=?",
                (customer_id,),
            )
        )
        returned = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(total_amount),0) FROM sales_returns WHERE customer_id=?",
                (customer_id,),
            )
        )
        customer = self.get(customer_id)
        return {
            "total_purchase": purchased,
            "total_paid": paid_at_sale + collected,
            "total_returned": returned,
            "current_due": int(customer["current_due"]),
            "opening_due": int(customer["opening_due"]),
        }

    def ledger(self, customer_id: int, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        """Opening balance + debits/credits with a running balance."""
        customer = self.get(customer_id)
        entries: list[dict[str, Any]] = []
        opening = int(customer["opening_due"])
        entries.append(
            {
                "date": customer["created_at"][:10],
                "particulars": "ওপেনিং ব্যালেন্স",
                "reference": "",
                "debit": max(opening, 0),
                "credit": max(-opening, 0),
                "kind": "opening",
                "reference_id": None,
            }
        )
        sales = self.db.query(
            """SELECT id, invoice_no, sale_date, grand_total, paid_amount, status
                 FROM sales WHERE customer_id=? ORDER BY sale_date, id""",
            (customer_id,),
        )
        for s in sales:
            if s["status"] == "cancelled":
                continue
            entries.append(
                {
                    "date": s["sale_date"],
                    "particulars": f"সেলস — {s['invoice_no']}",
                    "reference": s["invoice_no"],
                    "debit": int(s["grand_total"]),
                    "credit": int(s["paid_amount"]),
                    "kind": "sale",
                    "reference_id": int(s["id"]),
                }
            )
        for p in self.db.query(
            """SELECT cp.id, cp.receipt_no, cp.payment_date, cp.amount, pm.name AS method
                 FROM customer_payments cp JOIN payment_methods pm ON pm.id=cp.payment_method_id
                WHERE cp.customer_id=? ORDER BY cp.payment_date, cp.id""",
            (customer_id,),
        ):
            entries.append(
                {
                    "date": p["payment_date"],
                    "particulars": f"পেমেন্ট গ্রহণ — {p['receipt_no']} ({p['method']})",
                    "reference": p["receipt_no"],
                    "debit": 0,
                    "credit": int(p["amount"]),
                    "kind": "payment",
                    "reference_id": int(p["id"]),
                }
            )
        for r in self.db.query(
            """SELECT id, return_no, return_date, due_adjusted, advance_created
                 FROM sales_returns WHERE customer_id=? ORDER BY return_date, id""",
            (customer_id,),
        ):
            credit = int(r["due_adjusted"]) + int(r["advance_created"])
            if credit:
                entries.append(
                    {
                        "date": r["return_date"],
                        "particulars": f"সেলস রিটার্ন — {r['return_no']}",
                        "reference": r["return_no"],
                        "debit": 0,
                        "credit": credit,
                        "kind": "return",
                        "reference_id": int(r["id"]),
                    }
                )
        entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "opening" else 1))
        if start:
            opening_balance = opening + sum(
                e["debit"] - e["credit"] for e in entries[1:] if e["date"] < start
            )
            entries = [entries[0], *[e for e in entries[1:] if e["date"] >= start]]
        else:
            opening_balance = opening
        if end:
            entries = [entries[0], *[e for e in entries[1:] if e["date"] <= end]]

        running = 0
        for entry in entries:
            running += entry["debit"] - entry["credit"]
            entry["balance"] = running
        return {
            "customer": customer,
            "entries": entries,
            "opening_balance": opening_balance,
            "closing_balance": running,
            "total_debit": sum(e["debit"] for e in entries),
            "total_credit": sum(e["credit"] for e in entries),
        }

    def reconcile(self) -> list[dict[str, Any]]:
        """Verify cached due equals the ledger-derived balance for every customer."""
        rows = self.db.query(
            """SELECT c.id, c.name, c.current_due, c.opening_due,
                      COALESCE((SELECT SUM(s.due_amount) FROM sales s
                                 WHERE s.customer_id=c.id AND s.status<>'cancelled'),0) AS sale_due,
                      COALESCE((SELECT SUM(p.amount) FROM customer_payments p
                                 WHERE p.customer_id=c.id),0) AS collected,
                      COALESCE((SELECT SUM(r.due_adjusted + r.advance_created) FROM sales_returns r
                                 WHERE r.customer_id=c.id),0) AS returned
                 FROM customers c"""
        )
        problems = []
        for r in rows:
            expected = r["opening_due"] + r["sale_due"] - r["collected"] - r["returned"]
            if expected != r["current_due"]:
                problems.append(
                    {
                        "customer_id": r["id"],
                        "name": r["name"],
                        "current_due": r["current_due"],
                        "ledger_due": expected,
                    }
                )
        return problems


class SupplierService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def create(self, data: SupplierInput) -> int:
        name = require_text(data.name, "সাপ্লায়ারের নাম", max_length=200)
        phone = validate_phone(data.phone)
        with self.db.transaction():
            sid = self.db.insert(
                """INSERT INTO suppliers
                   (name, name_normalized, business_name, contact_person, phone, address, email,
                    opening_payable, current_payable, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    name,
                    normalize_search(name),
                    optional_text(data.business_name, max_length=200),
                    optional_text(data.contact_person, max_length=120),
                    phone,
                    optional_text(data.address, max_length=500),
                    validate_email(data.email),
                    data.opening_payable,
                    data.opening_payable,
                    optional_text(data.notes, max_length=1000),
                ),
            )
            self.audit.log("supplier", sid, "create", f"সাপ্লায়ার তৈরি: {name}")
        return sid

    def update(self, supplier_id: int, data: SupplierInput) -> None:
        require_id(supplier_id, "সাপ্লায়ার")
        self.get(supplier_id)
        name = require_text(data.name, "সাপ্লায়ারের নাম", max_length=200)
        with self.db.transaction():
            self.db.execute(
                """UPDATE suppliers SET name=?, name_normalized=?, business_name=?, contact_person=?,
                          phone=?, address=?, email=?, notes=?,
                          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (
                    name,
                    normalize_search(name),
                    optional_text(data.business_name, max_length=200),
                    optional_text(data.contact_person, max_length=120),
                    validate_phone(data.phone),
                    optional_text(data.address, max_length=500),
                    validate_email(data.email),
                    optional_text(data.notes, max_length=1000),
                    supplier_id,
                ),
            )
            self.audit.log("supplier", supplier_id, "update", f"সাপ্লায়ার হালনাগাদ: {name}")

    def set_status(self, supplier_id: int, status: str) -> None:
        validate_choice(status, ("active", "archived"), "স্ট্যাটাস")
        with self.db.transaction():
            self.db.execute("UPDATE suppliers SET status=? WHERE id=?", (status, supplier_id))
            self.audit.log("supplier", supplier_id, "status", f"স্ট্যাটাস: {status}")

    def delete(self, supplier_id: int) -> None:
        require_id(supplier_id, "সাপ্লায়ার")
        if int(self.db.scalar("SELECT COUNT(*) FROM purchases WHERE supplier_id=?", (supplier_id,))):
            raise BusinessRuleError("এই সাপ্লায়ারের পারচেজ হিস্ট্রি রয়েছে — আর্কাইভ করুন")
        with self.db.transaction():
            self.db.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,))
            self.audit.log("supplier", supplier_id, "delete", "সাপ্লায়ার মুছে ফেলা হয়েছে")

    def get(self, supplier_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM suppliers WHERE id=?", (supplier_id,))
        if row is None:
            raise NotFoundError("সাপ্লায়ার খুঁজে পাওয়া যায়নি")
        return dict(row)

    def search(
        self,
        *,
        query: str = "",
        status: str = "active",
        payable_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if status and status != "all":
            where.append("status=?")
            params.append(status)
        if query:
            term = f"%{normalize_search(query)}%"
            where.append(
                "(name_normalized LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' "
                "OR business_name LIKE ? ESCAPE '\\')"
            )
            params.extend([term, term, term])
        if payable_only:
            where.append("current_payable > 0")
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM suppliers WHERE {clause}", params))
        rows = self.db.query(
            f"SELECT * FROM suppliers WHERE {clause} ORDER BY name_normalized LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def totals(self, supplier_id: int) -> dict[str, int]:
        purchased = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(grand_total),0) FROM purchases WHERE supplier_id=? AND status<>'cancelled'",
                (supplier_id,),
            )
        )
        paid_at_purchase = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(paid_amount),0) FROM purchases WHERE supplier_id=? AND status<>'cancelled'",
                (supplier_id,),
            )
        )
        paid = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_id=?",
                (supplier_id,),
            )
        )
        returned = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(total_amount),0) FROM purchase_returns WHERE supplier_id=?",
                (supplier_id,),
            )
        )
        supplier = self.get(supplier_id)
        return {
            "total_purchase": purchased,
            "total_paid": paid_at_purchase + paid,
            "total_returned": returned,
            "current_payable": int(supplier["current_payable"]),
            "opening_payable": int(supplier["opening_payable"]),
        }

    def ledger(self, supplier_id: int, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        supplier = self.get(supplier_id)
        opening = int(supplier["opening_payable"])
        entries: list[dict[str, Any]] = [
            {
                "date": supplier["created_at"][:10],
                "particulars": "ওপেনিং ব্যালেন্স",
                "reference": "",
                "debit": max(-opening, 0),
                "credit": max(opening, 0),
                "kind": "opening",
                "reference_id": None,
            }
        ]
        for p in self.db.query(
            """SELECT id, invoice_no, purchase_date, grand_total, paid_amount, status
                 FROM purchases WHERE supplier_id=? ORDER BY purchase_date, id""",
            (supplier_id,),
        ):
            if p["status"] == "cancelled":
                continue
            entries.append(
                {
                    "date": p["purchase_date"],
                    "particulars": f"পারচেজ — {p['invoice_no']}",
                    "reference": p["invoice_no"],
                    "debit": int(p["paid_amount"]),
                    "credit": int(p["grand_total"]),
                    "kind": "purchase",
                    "reference_id": int(p["id"]),
                }
            )
        for p in self.db.query(
            """SELECT sp.id, sp.receipt_no, sp.payment_date, sp.amount, pm.name AS method
                 FROM supplier_payments sp JOIN payment_methods pm ON pm.id=sp.payment_method_id
                WHERE sp.supplier_id=? ORDER BY sp.payment_date, sp.id""",
            (supplier_id,),
        ):
            entries.append(
                {
                    "date": p["payment_date"],
                    "particulars": f"পেমেন্ট প্রদান — {p['receipt_no']} ({p['method']})",
                    "reference": p["receipt_no"],
                    "debit": int(p["amount"]),
                    "credit": 0,
                    "kind": "payment",
                    "reference_id": int(p["id"]),
                }
            )
        for r in self.db.query(
            """SELECT id, return_no, return_date, payable_adjusted, advance_created
                 FROM purchase_returns WHERE supplier_id=? ORDER BY return_date, id""",
            (supplier_id,),
        ):
            debit = int(r["payable_adjusted"]) + int(r["advance_created"])
            if debit:
                entries.append(
                    {
                        "date": r["return_date"],
                        "particulars": f"পারচেজ রিটার্ন — {r['return_no']}",
                        "reference": r["return_no"],
                        "debit": debit,
                        "credit": 0,
                        "kind": "return",
                        "reference_id": int(r["id"]),
                    }
                )
        entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "opening" else 1))
        if start:
            entries = [entries[0], *[e for e in entries[1:] if e["date"] >= start]]
        if end:
            entries = [entries[0], *[e for e in entries[1:] if e["date"] <= end]]
        running = 0
        for entry in entries:
            running += entry["credit"] - entry["debit"]
            entry["balance"] = running
        return {
            "supplier": supplier,
            "entries": entries,
            "opening_balance": opening,
            "closing_balance": running,
            "total_debit": sum(e["debit"] for e in entries),
            "total_credit": sum(e["credit"] for e in entries),
        }

    def reconcile(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT s.id, s.name, s.current_payable, s.opening_payable,
                      COALESCE((SELECT SUM(p.due_amount) FROM purchases p
                                 WHERE p.supplier_id=s.id AND p.status<>'cancelled'),0) AS purchase_due,
                      COALESCE((SELECT SUM(p.amount) FROM supplier_payments p
                                 WHERE p.supplier_id=s.id),0) AS paid,
                      COALESCE((SELECT SUM(r.payable_adjusted + r.advance_created) FROM purchase_returns r
                                 WHERE r.supplier_id=s.id),0) AS returned
                 FROM suppliers s"""
        )
        problems = []
        for r in rows:
            expected = r["opening_payable"] + r["purchase_due"] - r["paid"] - r["returned"]
            if expected != r["current_payable"]:
                problems.append(
                    {
                        "supplier_id": r["id"],
                        "name": r["name"],
                        "current_payable": r["current_payable"],
                        "ledger_payable": expected,
                    }
                )
        return problems


class PaymentMethodService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def list(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM payment_methods"
        if active_only:
            sql += " WHERE is_active=1"
        return [dict(r) for r in self.db.query(sql + " ORDER BY sort_order, id")]

    def create(self, name: str, *, is_cash: bool = False) -> int:
        from ..core.errors import DuplicateError

        name = require_text(name, "পেমেন্ট মেথডের নাম", max_length=80)
        normalized = normalize_search(name)
        if self.db.query_one("SELECT id FROM payment_methods WHERE name_normalized=?", (normalized,)):
            raise DuplicateError(f"'{name}' পেমেন্ট মেথড আগে থেকেই রয়েছে")
        order = int(self.db.scalar("SELECT COALESCE(MAX(sort_order),0)+1 FROM payment_methods"))
        with self.db.transaction():
            mid = self.db.insert(
                "INSERT INTO payment_methods (name, name_normalized, is_cash, sort_order) VALUES (?,?,?,?)",
                (name, normalized, 1 if is_cash else 0, order),
            )
            self.audit.log("payment_method", mid, "create", f"পেমেন্ট মেথড: {name}")
        return mid

    def set_active(self, method_id: int, active: bool) -> None:
        if (
            not active
            and self.db.query_one(
                "SELECT id FROM payment_methods WHERE is_cash=1 AND is_active=1 AND id<>?", (method_id,)
            )
            is None
            and self.db.query_one("SELECT is_cash FROM payment_methods WHERE id=?", (method_id,))["is_cash"]
        ):
            raise ValidationError("অন্তত একটি ক্যাশ পেমেন্ট মেথড সক্রিয় থাকতে হবে")
        with self.db.transaction():
            self.db.execute(
                "UPDATE payment_methods SET is_active=? WHERE id=?", (1 if active else 0, method_id)
            )
