"""Sales returns and purchase returns with exact cumulative-quantity control.

Financial rules (docs/FINANCIAL_POLICY.md §5):
* Sales return reverses revenue; COGS is reversed only for restocked goods.
* Purchase return removes stock at the original purchase value and reduces
  supplier payable by the same amount.
* A refund settles the document's outstanding first; any excess becomes a cash
  refund or a party advance, never a silent balance change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..core.errors import BusinessRuleError, NotFoundError, ValidationError
from ..core.money import round_div
from ..core.quantity import MILLI_PER_UNIT
from ..core.validation import optional_text, require_id, require_text, validate_choice, validate_date
from ..data.db import Database
from .audit import AuditService
from .cash import CashService
from .inventory import InventoryService
from .numbering import NumberingService
from .payments import CustomerPaymentService, SupplierPaymentService
from .settings import SettingsService

RETURN_CONDITIONS = ("restock", "damaged", "no_restock")


@dataclass(slots=True)
class SalesReturnLine:
    sale_item_id: int
    quantity: int
    condition: str = "restock"
    reason: str = ""


@dataclass(slots=True)
class PurchaseReturnLine:
    purchase_item_id: int
    quantity: int
    reason: str = ""


class SalesReturnService:
    def __init__(
        self,
        db: Database,
        *,
        settings: SettingsService | None = None,
        audit: AuditService | None = None,
        inventory: InventoryService | None = None,
        numbering: NumberingService | None = None,
        cash: CashService | None = None,
        customer_payments: CustomerPaymentService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.inventory = inventory or InventoryService(db, self.settings, self.audit)
        self.numbering = numbering or NumberingService(db, self.settings)
        self.cash = cash or CashService(db, self.settings, self.audit)
        self.customer_payments = customer_payments or CustomerPaymentService(
            db, settings=self.settings, audit=self.audit, numbering=self.numbering, cash=self.cash
        )

    def returnable_items(self, sale_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT si.*, (si.quantity - si.returned_qty) AS returnable_qty
                 FROM sale_items si WHERE si.sale_id=? ORDER BY si.id""",
            (sale_id,),
        )
        return [dict(r) for r in rows if r["returnable_qty"] > 0]

    def create(
        self,
        *,
        sale_id: int,
        lines: list[SalesReturnLine],
        reason: str,
        refund_amount: int = 0,
        refund_method_id: int | None = None,
        return_date: str | date | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        require_id(sale_id, "ইনভয়েস")
        sale = self.db.query_one("SELECT * FROM sales WHERE id=?", (sale_id,))
        if sale is None:
            raise NotFoundError("ইনভয়েস খুঁজে পাওয়া যায়নি")
        if sale["status"] == "cancelled":
            raise BusinessRuleError("বাতিল ইনভয়েসে রিটার্ন করা যাবে না")
        if not lines:
            raise ValidationError("রিটার্নের জন্য অন্তত একটি প্রোডাক্ট নির্বাচন করুন")
        reason = require_text(reason, "রিটার্নের কারণ", max_length=300)
        day = validate_date(return_date or date.today(), "রিটার্নের তারিখ")
        if refund_amount < 0:
            raise ValidationError("রিফান্ড ঋণাত্মক হতে পারে না")

        prepared = []
        for line in lines:
            require_id(line.sale_item_id, "ইনভয়েস আইটেম")
            validate_choice(line.condition, RETURN_CONDITIONS, "রিটার্ন কন্ডিশন")
            item = self.db.query_one(
                "SELECT * FROM sale_items WHERE id=? AND sale_id=?", (line.sale_item_id, sale_id)
            )
            if item is None:
                raise NotFoundError("ইনভয়েস আইটেম খুঁজে পাওয়া যায়নি")
            if line.quantity <= 0:
                raise ValidationError("রিটার্ন পরিমাণ ধনাত্মক হতে হবে")
            already = int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(quantity),0) FROM sales_return_items WHERE sale_item_id=?",
                    (line.sale_item_id,),
                )
            )
            returnable = int(item["quantity"]) - already
            if line.quantity > returnable:
                raise ValidationError(f"'{item['product_name']}' — সর্বোচ্চ {returnable} পরিমাণ রিটার্ন করা যাবে")
            prev_amount = int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(amount),0) FROM sales_return_items WHERE sale_item_id=?",
                    (line.sale_item_id,),
                )
            )
            prev_cost = int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(cost_amount),0) FROM sales_return_items WHERE sale_item_id=?",
                    (line.sale_item_id,),
                )
            )
            line_value = int(item["net_amount"]) + int(item["tax_amount"])
            if line.quantity == returnable:
                amount = line_value - prev_amount
                cost_amount = int(item["total_cost"]) - prev_cost
            else:
                amount = round_div(line_value * line.quantity, int(item["quantity"]))
                cost_amount = round_div(int(item["total_cost"]) * line.quantity, int(item["quantity"]))
            prepared.append(
                {
                    "item": dict(item),
                    "quantity": line.quantity,
                    "condition": line.condition,
                    "reason": optional_text(line.reason, max_length=200) or reason,
                    "amount": amount,
                    "cost_amount": cost_amount,
                    "unit_revenue": (
                        round_div(amount * MILLI_PER_UNIT, line.quantity) if line.quantity else 0
                    ),
                }
            )

        total_amount = sum(p["amount"] for p in prepared)
        outstanding = self.customer_payments.invoice_outstanding(sale_id)
        due_adjusted = min(total_amount, outstanding)
        remaining = total_amount - due_adjusted
        if refund_amount > remaining:
            raise ValidationError("রিফান্ডের পরিমাণ সমন্বয়ের পর অবশিষ্ট টাকার চেয়ে বেশি হতে পারে না")
        advance_created = remaining - refund_amount
        if advance_created > 0 and sale["customer_id"] is None:
            raise ValidationError("কাস্টমার ছাড়া ইনভয়েসে অ্যাডভান্স রাখা যায় না — সম্পূর্ণ টাকা রিফান্ড করুন")
        method = None
        if refund_amount > 0:
            require_id(refund_method_id, "রিফান্ড পেমেন্ট মেথড")
            method = self.db.query_one(
                "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (refund_method_id,)
            )
            if method is None:
                raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")

        cost_reversed = sum(p["cost_amount"] for p in prepared if p["condition"] == "restock")
        write_off = sum(p["cost_amount"] for p in prepared if p["condition"] != "restock")

        with self.db.transaction():
            return_no = self.numbering.next_number("sales_return", on_date=day)
            session_id = None
            if refund_amount > 0 and method is not None and method["is_cash"]:
                session_id = self.cash.require_open_session()
            return_id = self.db.insert(
                """INSERT INTO sales_returns
                   (return_no, sale_id, customer_id, return_date, total_amount, refund_amount,
                    due_adjusted, advance_created, cost_reversed, write_off_cost,
                    refund_method_id, reason, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    return_no,
                    sale_id,
                    sale["customer_id"],
                    day,
                    total_amount,
                    refund_amount,
                    due_adjusted,
                    advance_created,
                    cost_reversed,
                    write_off,
                    refund_method_id,
                    reason,
                    optional_text(notes, max_length=500),
                    session_id,
                ),
            )
            for p in prepared:
                item = p["item"]
                self.db.insert(
                    """INSERT INTO sales_return_items
                       (return_id, sale_item_id, product_id, quantity, unit_revenue, amount,
                        unit_cost, cost_amount, condition, reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        return_id,
                        int(item["id"]),
                        int(item["product_id"]),
                        p["quantity"],
                        p["unit_revenue"],
                        p["amount"],
                        int(item["unit_cost"]),
                        p["cost_amount"],
                        p["condition"],
                        p["reason"],
                    ),
                )
                self.db.execute(
                    "UPDATE sale_items SET returned_qty = returned_qty + ? WHERE id=?",
                    (p["quantity"], int(item["id"])),
                )
                if p["condition"] == "restock":
                    self.inventory.apply_movement(
                        product_id=int(item["product_id"]),
                        qty_delta=p["quantity"],
                        movement_type="sales_return_restock",
                        movement_date=day,
                        unit_cost=int(item["unit_cost"]),
                        received_value=p["cost_amount"],
                        reference_type="sales_return",
                        reference_id=return_id,
                        notes=f"{return_no} — {reason}",
                        allow_negative=True,
                    )
            if sale["customer_id"] is not None:
                self.db.execute(
                    "UPDATE customers SET current_due = current_due - ? WHERE id=?",
                    (due_adjusted + advance_created, sale["customer_id"]),
                )
            if refund_amount > 0 and method is not None and method["is_cash"] and session_id is not None:
                self.cash.record_movement(
                    session_id=session_id,
                    movement_type="sales_return_refund",
                    amount=-refund_amount,
                    payment_method_id=refund_method_id,
                    reference_type="sales_return",
                    reference_id=return_id,
                    notes=return_no,
                )
            fully = self.db.query_one(
                """SELECT COUNT(*) AS remaining FROM sale_items
                    WHERE sale_id=? AND returned_qty < quantity""",
                (sale_id,),
            )
            new_status = "returned" if int(fully["remaining"]) == 0 else "partially_returned"
            self.db.execute("UPDATE sales SET status=? WHERE id=?", (new_status, sale_id))
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('sales_return', ?, ?, 'customer', ?, ?, ?, ?, 0, ?, 'sales_return', ?, ?)""",
                (
                    return_no,
                    day,
                    sale["customer_id"],
                    str(
                        self.db.scalar(
                            "SELECT COALESCE(name,'') FROM customers WHERE id=?",
                            (sale["customer_id"],),
                            default="",
                        )
                    ),
                    total_amount,
                    refund_amount,
                    method["name"] if method is not None else "",
                    return_id,
                    reason,
                ),
            )
            self.audit.log(
                "sales_return",
                return_id,
                "create",
                f"সেলস রিটার্ন {return_no} — {total_amount}, রিফান্ড {refund_amount}",
                after={"total": total_amount, "restocked_cost": cost_reversed, "write_off": write_off},
            )
        return {
            "id": return_id,
            "return_no": return_no,
            "total_amount": total_amount,
            "refund_amount": refund_amount,
            "due_adjusted": due_adjusted,
            "advance_created": advance_created,
            "cost_reversed": cost_reversed,
            "write_off_cost": write_off,
        }

    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        customer_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("r.return_date >= ?")
            params.append(start)
        if end:
            where.append("r.return_date <= ?")
            params.append(end)
        if customer_id is not None:
            where.append("r.customer_id = ?")
            params.append(customer_id)
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM sales_returns r WHERE {clause}", params))
        rows = self.db.query(
            f"""SELECT r.*, s.invoice_no, c.name AS customer_name
                  FROM sales_returns r JOIN sales s ON s.id=r.sale_id
                  LEFT JOIN customers c ON c.id=r.customer_id
                 WHERE {clause} ORDER BY r.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def get(self, return_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM sales_returns WHERE id=?", (return_id,))
        if row is None:
            raise NotFoundError("রিটার্ন খুঁজে পাওয়া যায়নি")
        data = dict(row)
        data["items"] = [
            dict(r)
            for r in self.db.query(
                """SELECT sri.*, si.product_name, si.unit_name FROM sales_return_items sri
                     JOIN sale_items si ON si.id=sri.sale_item_id
                    WHERE sri.return_id=? ORDER BY sri.id""",
                (return_id,),
            )
        ]
        return data


class PurchaseReturnService:
    def __init__(
        self,
        db: Database,
        *,
        settings: SettingsService | None = None,
        audit: AuditService | None = None,
        inventory: InventoryService | None = None,
        numbering: NumberingService | None = None,
        cash: CashService | None = None,
        supplier_payments: SupplierPaymentService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.inventory = inventory or InventoryService(db, self.settings, self.audit)
        self.numbering = numbering or NumberingService(db, self.settings)
        self.cash = cash or CashService(db, self.settings, self.audit)
        self.supplier_payments = supplier_payments or SupplierPaymentService(
            db, settings=self.settings, audit=self.audit, numbering=self.numbering, cash=self.cash
        )

    def returnable_items(self, purchase_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT pi.*, (pi.quantity - pi.returned_qty) AS returnable_qty
                 FROM purchase_items pi WHERE pi.purchase_id=? ORDER BY pi.id""",
            (purchase_id,),
        )
        return [dict(r) for r in rows if r["returnable_qty"] > 0]

    def create(
        self,
        *,
        purchase_id: int,
        lines: list[PurchaseReturnLine],
        reason: str,
        refund_amount: int = 0,
        refund_method_id: int | None = None,
        return_date: str | date | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        require_id(purchase_id, "পারচেজ")
        purchase = self.db.query_one("SELECT * FROM purchases WHERE id=?", (purchase_id,))
        if purchase is None:
            raise NotFoundError("পারচেজ খুঁজে পাওয়া যায়নি")
        if purchase["status"] == "cancelled":
            raise BusinessRuleError("বাতিল পারচেজে রিটার্ন করা যাবে না")
        if not lines:
            raise ValidationError("রিটার্নের জন্য অন্তত একটি প্রোডাক্ট নির্বাচন করুন")
        reason = require_text(reason, "রিটার্নের কারণ", max_length=300)
        day = validate_date(return_date or date.today(), "রিটার্নের তারিখ")
        if refund_amount < 0:
            raise ValidationError("রিফান্ড ঋণাত্মক হতে পারে না")

        prepared = []
        for line in lines:
            item = self.db.query_one(
                "SELECT * FROM purchase_items WHERE id=? AND purchase_id=?",
                (line.purchase_item_id, purchase_id),
            )
            if item is None:
                raise NotFoundError("পারচেজ আইটেম খুঁজে পাওয়া যায়নি")
            if line.quantity <= 0:
                raise ValidationError("রিটার্ন পরিমাণ ধনাত্মক হতে হবে")
            already = int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(quantity),0) FROM purchase_return_items WHERE purchase_item_id=?",
                    (line.purchase_item_id,),
                )
            )
            returnable = int(item["quantity"]) - already
            if line.quantity > returnable:
                raise ValidationError(f"'{item['product_name']}' — সর্বোচ্চ {returnable} পরিমাণ রিটার্ন করা যাবে")
            prev_amount = int(
                self.db.scalar(
                    "SELECT COALESCE(SUM(amount),0) FROM purchase_return_items WHERE purchase_item_id=?",
                    (line.purchase_item_id,),
                )
            )
            if line.quantity == returnable:
                amount = int(item["net_amount"]) - prev_amount
            else:
                amount = round_div(int(item["net_amount"]) * line.quantity, int(item["quantity"]))
            prepared.append(
                {
                    "item": dict(item),
                    "quantity": line.quantity,
                    "amount": amount,
                    "reason": optional_text(line.reason, max_length=200) or reason,
                }
            )

        total_amount = sum(p["amount"] for p in prepared)
        outstanding = self.supplier_payments.purchase_outstanding(purchase_id)
        payable_adjusted = min(total_amount, outstanding)
        remaining = total_amount - payable_adjusted
        if refund_amount > remaining:
            raise ValidationError("রিফান্ড সমন্বয়ের পর অবশিষ্ট টাকার চেয়ে বেশি হতে পারে না")
        advance_created = remaining - refund_amount
        method = None
        if refund_amount > 0:
            require_id(refund_method_id, "রিফান্ড পেমেন্ট মেথড")
            method = self.db.query_one(
                "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (refund_method_id,)
            )
            if method is None:
                raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")

        with self.db.transaction():
            return_no = self.numbering.next_number("purchase_return", on_date=day)
            session_id = None
            if refund_amount > 0 and method is not None and method["is_cash"]:
                session_id = self.cash.require_open_session()
            return_id = self.db.insert(
                """INSERT INTO purchase_returns
                   (return_no, purchase_id, supplier_id, return_date, total_amount, refund_amount,
                    payable_adjusted, advance_created, refund_method_id, reason, notes, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    return_no,
                    purchase_id,
                    purchase["supplier_id"],
                    day,
                    total_amount,
                    refund_amount,
                    payable_adjusted,
                    advance_created,
                    refund_method_id,
                    reason,
                    optional_text(notes, max_length=500),
                    session_id,
                ),
            )
            for p in prepared:
                item = p["item"]
                self.db.insert(
                    """INSERT INTO purchase_return_items
                       (return_id, purchase_item_id, product_id, quantity, unit_cost, amount, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        return_id,
                        int(item["id"]),
                        int(item["product_id"]),
                        p["quantity"],
                        int(item["effective_cost"]),
                        p["amount"],
                        p["reason"],
                    ),
                )
                self.db.execute(
                    "UPDATE purchase_items SET returned_qty = returned_qty + ? WHERE id=?",
                    (p["quantity"], int(item["id"])),
                )
                self.inventory.apply_movement(
                    product_id=int(item["product_id"]),
                    qty_delta=-p["quantity"],
                    movement_type="purchase_return",
                    movement_date=day,
                    unit_cost=int(item["effective_cost"]),
                    issued_value=p["amount"],
                    reference_type="purchase_return",
                    reference_id=return_id,
                    notes=f"{return_no} — {reason}",
                    allow_negative=True,
                )
            self.db.execute(
                "UPDATE suppliers SET current_payable = current_payable - ? WHERE id=?",
                (payable_adjusted + advance_created, purchase["supplier_id"]),
            )
            if refund_amount > 0 and method is not None and method["is_cash"] and session_id is not None:
                self.cash.record_movement(
                    session_id=session_id,
                    movement_type="purchase_return_refund",
                    amount=refund_amount,
                    payment_method_id=refund_method_id,
                    reference_type="purchase_return",
                    reference_id=return_id,
                    notes=return_no,
                )
            fully = self.db.query_one(
                "SELECT COUNT(*) AS remaining FROM purchase_items WHERE purchase_id=? AND returned_qty < quantity",
                (purchase_id,),
            )
            new_status = "returned" if int(fully["remaining"]) == 0 else "partially_returned"
            self.db.execute("UPDATE purchases SET status=? WHERE id=?", (new_status, purchase_id))
            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('purchase_return', ?, ?, 'supplier', ?, ?, ?, ?, 0, ?, 'purchase_return', ?, ?)""",
                (
                    return_no,
                    day,
                    purchase["supplier_id"],
                    str(
                        self.db.scalar(
                            "SELECT name FROM suppliers WHERE id=?", (purchase["supplier_id"],), default=""
                        )
                    ),
                    total_amount,
                    refund_amount,
                    method["name"] if method is not None else "",
                    return_id,
                    reason,
                ),
            )
            self.audit.log(
                "purchase_return",
                return_id,
                "create",
                f"পারচেজ রিটার্ন {return_no} — {total_amount}",
            )
        return {
            "id": return_id,
            "return_no": return_no,
            "total_amount": total_amount,
            "refund_amount": refund_amount,
            "payable_adjusted": payable_adjusted,
            "advance_created": advance_created,
        }

    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        supplier_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("r.return_date >= ?")
            params.append(start)
        if end:
            where.append("r.return_date <= ?")
            params.append(end)
        if supplier_id is not None:
            where.append("r.supplier_id = ?")
            params.append(supplier_id)
        clause = " AND ".join(where)
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM purchase_returns r WHERE {clause}", params))
        rows = self.db.query(
            f"""SELECT r.*, p.invoice_no, s.name AS supplier_name
                  FROM purchase_returns r JOIN purchases p ON p.id=r.purchase_id
                  JOIN suppliers s ON s.id=r.supplier_id
                 WHERE {clause} ORDER BY r.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}
