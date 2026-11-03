"""Purchase service: stock receipt with moving-average cost and supplier payable."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..core.errors import BusinessRuleError, NotFoundError, ValidationError
from ..core.money import allocate, round_div
from ..core.quantity import MILLI_PER_UNIT
from ..core.validation import (
    optional_text,
    require_id,
    require_non_negative_money,
    validate_date,
)
from ..data.db import Database
from .audit import AuditService
from .cash import CashService
from .inventory import InventoryService
from .numbering import NumberingService
from .sales import PaymentInput
from .settings import SettingsService


@dataclass(slots=True)
class PurchaseLineInput:
    product_id: int
    quantity: int
    unit_cost: int
    discount_amount: int = 0


@dataclass(slots=True)
class PurchaseInput:
    supplier_id: int
    lines: list[PurchaseLineInput]
    payments: list[PaymentInput] = field(default_factory=list)
    purchase_date: str | date | None = None
    supplier_invoice_no: str = ""
    discount_amount: int = 0
    notes: str = ""


class PurchaseService:
    def __init__(
        self,
        db: Database,
        *,
        settings: SettingsService | None = None,
        audit: AuditService | None = None,
        inventory: InventoryService | None = None,
        numbering: NumberingService | None = None,
        cash: CashService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.inventory = inventory or InventoryService(db, self.settings, self.audit)
        self.numbering = numbering or NumberingService(db, self.settings)
        self.cash = cash or CashService(db, self.settings, self.audit)

    def create(self, data: PurchaseInput) -> dict[str, Any]:
        require_id(data.supplier_id, "সাপ্লায়ার")
        supplier = self.db.query_one("SELECT * FROM suppliers WHERE id=?", (data.supplier_id,))
        if supplier is None:
            raise NotFoundError("সাপ্লায়ার খুঁজে পাওয়া যায়নি")
        if not data.lines:
            raise ValidationError("পারচেজে অন্তত একটি প্রোডাক্ট যোগ করুন")
        day = validate_date(data.purchase_date or date.today(), "পারচেজের তারিখ")
        now = datetime.now()

        prepared = []
        for line in data.lines:
            require_id(line.product_id, "প্রোডাক্ট")
            row = self.db.query_one(
                """SELECT p.*, u.name AS unit_name FROM products p
                     JOIN units u ON u.id=p.unit_id WHERE p.id=?""",
                (line.product_id,),
            )
            if row is None:
                raise NotFoundError("প্রোডাক্ট খুঁজে পাওয়া যায়নি")
            if line.quantity <= 0:
                raise ValidationError("পরিমাণ ধনাত্মক হতে হবে")
            require_non_negative_money(line.unit_cost, "পারচেজ মূল্য")
            gross = round_div(line.unit_cost * line.quantity, MILLI_PER_UNIT)
            require_non_negative_money(line.discount_amount, "লাইন ডিস্কাউন্ট")
            if line.discount_amount > gross:
                raise ValidationError("লাইন ডিস্কাউন্ট মোট মূল্যের বেশি হতে পারে না")
            prepared.append(
                {
                    "product": dict(row),
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "gross": gross,
                    "discount": line.discount_amount,
                    "net_before": gross - line.discount_amount,
                }
            )

        subtotal = sum(p["gross"] for p in prepared)
        line_discounts = sum(p["discount"] for p in prepared)
        net_before = sum(p["net_before"] for p in prepared)
        require_non_negative_money(data.discount_amount, "ইনভয়েস ডিস্কাউন্ট")
        if data.discount_amount > net_before:
            raise ValidationError("ইনভয়েস ডিস্কাউন্ট মোট মূল্যের বেশি হতে পারে না")
        shares = (
            allocate(data.discount_amount, [p["net_before"] for p in prepared])
            if data.discount_amount
            else [0] * len(prepared)
        )
        for p, share in zip(prepared, shares, strict=True):
            p["net"] = p["net_before"] - share
            p["effective_cost"] = round_div(p["net"] * MILLI_PER_UNIT, p["quantity"]) if p["quantity"] else 0
        grand_total = sum(p["net"] for p in prepared)

        paid = sum(p.amount for p in data.payments)
        if paid > grand_total:
            raise ValidationError("পরিশোধিত টাকা পারচেজ মোটের চেয়ে বেশি হতে পারে না")
        due = grand_total - paid
        methods = {}
        for payment in data.payments:
            if payment.amount <= 0:
                raise ValidationError("পেমেন্টের পরিমাণ ধনাত্মক হতে হবে")
            row = self.db.query_one(
                "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (payment.method_id,)
            )
            if row is None:
                raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")
            methods[payment.method_id] = dict(row)
        cash_total = sum(p.amount for p in data.payments if methods[p.method_id]["is_cash"])
        notes = optional_text(data.notes, max_length=500)

        with self.db.transaction():
            session_id = self.cash.require_open_session() if cash_total > 0 else None
            invoice_no = self.numbering.next_number("purchase", on_date=day)
            purchase_id = self.db.insert(
                """INSERT INTO purchases
                   (invoice_no, supplier_invoice_no, supplier_id, purchase_date, subtotal,
                    discount_amount, grand_total, paid_amount, due_amount, status, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?, 'completed', ?, ?)""",
                (
                    invoice_no,
                    optional_text(data.supplier_invoice_no, max_length=120),
                    data.supplier_id,
                    day,
                    subtotal,
                    line_discounts + data.discount_amount,
                    grand_total,
                    paid,
                    due,
                    notes,
                    session_id,
                ),
            )
            for p in prepared:
                product = p["product"]
                self.inventory.apply_movement(
                    product_id=int(product["id"]),
                    qty_delta=p["quantity"],
                    movement_type="purchase",
                    movement_date=day,
                    unit_cost=p["effective_cost"],
                    received_value=p["net"],
                    reference_type="purchase",
                    reference_id=purchase_id,
                    notes=invoice_no,
                    allow_negative=True,
                )
                self.db.insert(
                    """INSERT INTO purchase_items
                       (purchase_id, product_id, product_name, unit_name, quantity, unit_cost,
                        gross_amount, discount_amount, net_amount, effective_cost)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        purchase_id,
                        int(product["id"]),
                        product["name"],
                        product["unit_name"],
                        p["quantity"],
                        p["unit_cost"],
                        p["gross"],
                        p["discount"] + (p["net_before"] - p["net"]),
                        p["net"],
                        p["effective_cost"],
                    ),
                )
                # Keep the product's reference purchase price current for future entries.
                self.db.execute(
                    "UPDATE products SET purchase_price=? WHERE id=?",
                    (p["unit_cost"], int(product["id"])),
                )

            summary = []
            for payment in data.payments:
                self.db.insert(
                    """INSERT INTO purchase_payments
                       (purchase_id, payment_method_id, amount, paid_at, reference, notes)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        purchase_id,
                        payment.method_id,
                        payment.amount,
                        now.isoformat(timespec="seconds"),
                        optional_text(payment.reference, max_length=120),
                        optional_text(payment.notes, max_length=300),
                    ),
                )
                summary.append(methods[payment.method_id]["name"])
                if methods[payment.method_id]["is_cash"] and session_id is not None:
                    self.cash.record_movement(
                        session_id=session_id,
                        movement_type="purchase",
                        amount=-payment.amount,
                        payment_method_id=payment.method_id,
                        reference_type="purchase",
                        reference_id=purchase_id,
                        notes=invoice_no,
                    )

            self.db.execute(
                "UPDATE suppliers SET current_payable = current_payable + ? WHERE id=?",
                (due, data.supplier_id),
            )
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('purchase', ?, ?, 'supplier', ?, ?, ?, ?, ?, ?, 'purchase', ?, ?)""",
                (
                    invoice_no,
                    day,
                    data.supplier_id,
                    supplier["name"],
                    grand_total,
                    paid,
                    due,
                    ", ".join(dict.fromkeys(summary)),
                    purchase_id,
                    notes,
                ),
            )
            self.audit.log(
                "purchase",
                purchase_id,
                "create",
                f"পারচেজ {invoice_no} — মোট {grand_total}, বাকি {due}",
                after={"invoice_no": invoice_no, "grand_total": grand_total, "due": due},
            )
        return {
            "id": purchase_id,
            "invoice_no": invoice_no,
            "grand_total": grand_total,
            "paid_amount": paid,
            "due_amount": due,
        }

    def get(self, purchase_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT p.*, s.name AS supplier_name, s.phone AS supplier_phone
                 FROM purchases p JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=?""",
            (purchase_id,),
        )
        if row is None:
            raise NotFoundError("পারচেজ খুঁজে পাওয়া যায়নি")
        data = dict(row)
        data["items"] = [
            dict(r)
            for r in self.db.query(
                "SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id", (purchase_id,)
            )
        ]
        data["payments"] = [
            dict(r)
            for r in self.db.query(
                """SELECT pp.*, pm.name AS method_name FROM purchase_payments pp
                     JOIN payment_methods pm ON pm.id=pp.payment_method_id
                    WHERE pp.purchase_id=? ORDER BY pp.id""",
                (purchase_id,),
            )
        ]
        return data

    def outstanding(self, purchase_id: int) -> int:
        row = self.db.query_one(
            "SELECT grand_total, paid_amount, status FROM purchases WHERE id=?", (purchase_id,)
        )
        if row is None:
            raise NotFoundError("পারচেজ খুঁজে পাওয়া যায়নি")
        if row["status"] == "cancelled":
            return 0
        allocated = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM supplier_payment_allocations WHERE purchase_id=?",
                (purchase_id,),
            )
        )
        returned = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(payable_adjusted),0) FROM purchase_returns WHERE purchase_id=?",
                (purchase_id,),
            )
        )
        return max(0, int(row["grand_total"]) - int(row["paid_amount"]) - allocated - returned)

    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        supplier_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("p.purchase_date >= ?")
            params.append(start)
        if end:
            where.append("p.purchase_date <= ?")
            params.append(end)
        if supplier_id is not None:
            where.append("p.supplier_id = ?")
            params.append(supplier_id)
        if query:
            where.append("(p.invoice_no LIKE ? OR p.supplier_invoice_no LIKE ? OR s.name_normalized LIKE ?)")
            term = f"%{query.strip().lower()}%"
            params.extend([term, term, term])
        clause = " AND ".join(where)
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) FROM purchases p JOIN suppliers s ON s.id=p.supplier_id WHERE {clause}",
                params,
            )
        )
        rows = self.db.query(
            f"""SELECT p.*, s.name AS supplier_name FROM purchases p
                  JOIN suppliers s ON s.id=p.supplier_id
                 WHERE {clause} ORDER BY p.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def cancel(self, purchase_id: int, *, reason: str) -> dict[str, Any]:
        require_id(purchase_id, "পারচেজ")
        purchase = self.get(purchase_id)
        if purchase["status"] == "cancelled":
            raise BusinessRuleError("এই পারচেজ আগেই বাতিল করা হয়েছে")
        if int(
            self.db.scalar(
                "SELECT COALESCE(SUM(returned_qty),0) FROM purchase_items WHERE purchase_id=?",
                (purchase_id,),
            )
        ):
            raise BusinessRuleError("এই পারচেজে রিটার্ন হয়েছে — বাতিল করা যাবে না")
        day = date.today().isoformat()
        with self.db.transaction():
            for item in purchase["items"]:
                self.inventory.apply_movement(
                    product_id=int(item["product_id"]),
                    qty_delta=-int(item["quantity"]),
                    movement_type="purchase_return",
                    movement_date=day,
                    unit_cost=int(item["effective_cost"]),
                    reference_type="purchase_cancel",
                    reference_id=purchase_id,
                    notes=f"বাতিল: {purchase['invoice_no']} — {reason}",
                    allow_negative=True,
                )
            self.db.execute(
                "UPDATE suppliers SET current_payable = current_payable - ? WHERE id=?",
                (int(purchase["due_amount"]), purchase["supplier_id"]),
            )
            cash_paid = int(
                self.db.scalar(
                    """SELECT COALESCE(SUM(pp.amount),0) FROM purchase_payments pp
                         JOIN payment_methods pm ON pm.id=pp.payment_method_id
                        WHERE pp.purchase_id=? AND pm.is_cash=1""",
                    (purchase_id,),
                )
            )
            if cash_paid:
                session_id = self.cash.require_open_session()
                self.cash.record_movement(
                    session_id=session_id,
                    movement_type="purchase_return_refund",
                    amount=cash_paid,
                    reference_type="purchase_cancel",
                    reference_id=purchase_id,
                    notes=f"বাতিল: {purchase['invoice_no']}",
                )
            self.db.execute(
                "UPDATE purchases SET status='cancelled', cancelled_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), purchase_id),
            )
            self.db.execute(
                "UPDATE transactions SET status='cancelled' WHERE txn_type='purchase' AND reference_id=?",
                (purchase_id,),
            )
            self.audit.log("purchase", purchase_id, "cancel", f"পারচেজ বাতিল — {reason}")
        return {"id": purchase_id, "status": "cancelled"}
