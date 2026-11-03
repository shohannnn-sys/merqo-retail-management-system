"""Sales / POS service.

A sale is persisted as ONE atomic transaction covering: validation, invoice
numbering, sale + items, payments, stock movements, customer due, cash drawer,
the centralized transaction index and the audit trail. Any failure rolls back
everything — stock can never drift from money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..core.errors import BusinessRuleError, NotFoundError, ValidationError
from ..core.validation import (
    optional_text,
    require_id,
    require_non_negative_money,
    require_percent_bp,
    validate_choice,
    validate_date,
)
from ..data.db import Database
from .audit import AuditService
from .calculations import CartItem, CartTotals, calculate_cart
from .cash import CashService
from .inventory import InventoryService
from .numbering import NumberingService
from .settings import SettingsService


@dataclass(slots=True)
class PaymentInput:
    method_id: int
    amount: int
    reference: str = ""
    notes: str = ""


@dataclass(slots=True)
class SaleLineInput:
    product_id: int
    quantity: int
    unit_price: int | None = None  # defaults to the product's selling price
    discount_type: str = "none"
    discount_value: int = 0


@dataclass(slots=True)
class SaleInput:
    lines: list[SaleLineInput]
    payments: list[PaymentInput] = field(default_factory=list)
    customer_id: int | None = None
    sale_date: str | date | None = None
    invoice_discount_type: str = "none"
    invoice_discount_value: int = 0
    notes: str = ""
    cashier: str = ""


class SalesService:
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

    # ------------------------------------------------------------- preview
    def preview(self, data: SaleInput) -> CartTotals:
        """Same math as saving, without touching the database state."""
        items = self._build_items(data.lines)
        return calculate_cart(
            items,
            invoice_discount_type=data.invoice_discount_type,
            invoice_discount_value=data.invoice_discount_value,
            tax_enabled=self.settings.get_bool("tax_enabled", False),
            max_item_discount_bp=self.settings.get_int("max_item_discount_bp", 10_000),
            max_invoice_discount_bp=self.settings.get_int("max_invoice_discount_bp", 10_000),
        )

    def _build_items(self, lines: list[SaleLineInput]) -> list[CartItem]:
        if not lines:
            raise ValidationError("কার্ট খালি — অন্তত একটি প্রোডাক্ট যোগ করুন")
        tax_enabled = self.settings.get_bool("tax_enabled", False)
        default_tax = self.settings.get_int("default_tax_bp", 0)
        items: list[CartItem] = []
        for line in lines:
            require_id(line.product_id, "প্রোডাক্ট")
            row = self.db.query_one(
                """SELECT p.*, u.name AS unit_name FROM products p
                     JOIN units u ON u.id=p.unit_id WHERE p.id=?""",
                (line.product_id,),
            )
            if row is None:
                raise NotFoundError(f"প্রোডাক্ট খুঁজে পাওয়া যায়নি (আইডি {line.product_id})")
            if row["status"] != "active":
                raise BusinessRuleError(f"'{row['name']}' প্রোডাক্টটি নিষ্ক্রিয়")
            if line.quantity <= 0:
                raise ValidationError("প্রোডাক্টের পরিমাণ ধনাত্মক হতে হবে")
            price = line.unit_price if line.unit_price is not None else int(row["selling_price"])
            require_non_negative_money(price, "বিক্রয় মূল্য")
            validate_choice(line.discount_type, ("none", "percent", "fixed"), "ডিস্কাউন্টের ধরন")
            if line.discount_type == "percent":
                require_percent_bp(line.discount_value, "ডিস্কাউন্ট")
            else:
                require_non_negative_money(line.discount_value, "ডিস্কাউন্ট")
            tax_bp = int(row["tax_bp"]) or default_tax if tax_enabled else 0
            items.append(
                CartItem(
                    product_id=int(row["id"]),
                    quantity=line.quantity,
                    unit_price=price,
                    discount_type=line.discount_type,
                    discount_value=line.discount_value,
                    tax_bp=tax_bp,
                    name=row["name"],
                    unit_name=row["unit_name"],
                )
            )
        return items

    # ---------------------------------------------------------------- create
    def create(self, data: SaleInput) -> dict[str, Any]:
        totals = self.preview(data)
        day = validate_date(data.sale_date or date.today(), "সেলসের তারিখ")
        now = datetime.now()
        paid = sum(p.amount for p in data.payments)
        require_non_negative_money(paid, "পেমেন্ট")
        if paid > totals.grand_total:
            raise ValidationError("পরিশোধিত টাকা ইনভয়েস মোটের চেয়ে বেশি হতে পারে না — অতিরিক্ত টাকা ফেরত দিন")
        due = totals.grand_total - paid
        if due > 0 and data.customer_id is None:
            raise ValidationError("বাকি বিক্রির জন্য কাস্টমার নির্বাচন করা আবশ্যক")
        if data.customer_id is not None:
            require_id(data.customer_id, "কাস্টমার")
            if not self.db.query_one("SELECT id FROM customers WHERE id=?", (data.customer_id,)):
                raise NotFoundError("কাস্টমার খুঁজে পাওয়া যায়নি")

        methods = self._validate_payments(data.payments)
        cash_total = sum(p.amount for p in data.payments if methods[p.method_id]["is_cash"])
        notes = optional_text(data.notes, max_length=500)

        with self.db.transaction():
            session_id = None
            if cash_total > 0:
                session_id = self.cash.require_open_session()

            invoice_no = self.numbering.next_number("sale", on_date=day)
            sale_id = self.db.insert(
                """INSERT INTO sales
                   (invoice_no, customer_id, sale_date, sale_time, subtotal, item_discount,
                    invoice_discount_type, invoice_discount_value, invoice_discount,
                    tax_amount, grand_total, paid_amount, due_amount, total_cost,
                    status, notes, cashier, cash_session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'completed', ?, ?, ?)""",
                (
                    invoice_no,
                    data.customer_id,
                    day,
                    now.strftime("%H:%M:%S"),
                    totals.subtotal,
                    totals.item_discount,
                    data.invoice_discount_type,
                    data.invoice_discount_value,
                    totals.invoice_discount,
                    totals.tax_amount,
                    totals.grand_total,
                    paid,
                    due,
                    0,
                    notes,
                    data.cashier,
                    session_id,
                ),
            )

            total_cost = 0
            for line in totals.lines:
                movement = self.inventory.apply_movement(
                    product_id=line.product_id,
                    qty_delta=-line.quantity,
                    movement_type="sale",
                    movement_date=day,
                    reference_type="sale",
                    reference_id=sale_id,
                    notes=invoice_no,
                )
                line_cost = max(0, -movement.value_delta)
                total_cost += line_cost
                self.db.insert(
                    """INSERT INTO sale_items
                       (sale_id, product_id, product_name, unit_name, quantity, unit_price,
                        gross_amount, discount_type, discount_value, discount_amount,
                        invoice_discount_allocated, net_amount, tax_bp, tax_amount,
                        unit_cost, total_cost)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sale_id,
                        line.product_id,
                        line.name,
                        line.unit_name,
                        line.quantity,
                        line.unit_price,
                        line.gross_amount,
                        line.discount_type,
                        line.discount_value,
                        line.discount_amount,
                        line.invoice_discount_allocated,
                        line.net_amount,
                        line.tax_bp,
                        line.tax_amount,
                        movement.unit_cost,
                        line_cost,
                    ),
                )
            self.db.execute("UPDATE sales SET total_cost=? WHERE id=?", (total_cost, sale_id))

            payment_summary = []
            for payment in data.payments:
                self.db.insert(
                    """INSERT INTO sale_payments
                       (sale_id, payment_method_id, amount, paid_at, reference, notes)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        sale_id,
                        payment.method_id,
                        payment.amount,
                        now.isoformat(timespec="seconds"),
                        optional_text(payment.reference, max_length=120),
                        optional_text(payment.notes, max_length=300),
                    ),
                )
                payment_summary.append(methods[payment.method_id]["name"])
                if methods[payment.method_id]["is_cash"] and session_id is not None:
                    self.cash.record_movement(
                        session_id=session_id,
                        movement_type="sale",
                        amount=payment.amount,
                        payment_method_id=payment.method_id,
                        reference_type="sale",
                        reference_id=sale_id,
                        notes=invoice_no,
                    )

            customer_name = ""
            if data.customer_id is not None:
                self.db.execute(
                    """UPDATE customers SET current_due = current_due + ?,
                              updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (due, data.customer_id),
                )
                customer_name = str(
                    self.db.scalar("SELECT name FROM customers WHERE id=?", (data.customer_id,), default="")
                )

            self.db.execute(
                """INSERT INTO transactions
                   (txn_type, txn_no, txn_date, party_type, party_id, party_name, amount,
                    paid_amount, due_amount, payment_summary, reference_type, reference_id, notes)
                   VALUES ('sale', ?, ?, 'customer', ?, ?, ?, ?, ?, ?, 'sale', ?, ?)""",
                (
                    invoice_no,
                    day,
                    data.customer_id,
                    customer_name,
                    totals.grand_total,
                    paid,
                    due,
                    ", ".join(dict.fromkeys(payment_summary)),
                    sale_id,
                    notes,
                ),
            )
            self.audit.log(
                "sale",
                sale_id,
                "create",
                f"সেলস {invoice_no} — মোট {totals.grand_total} পয়সা, বাকি {due}",
                after={
                    "invoice_no": invoice_no,
                    "grand_total": totals.grand_total,
                    "paid": paid,
                    "due": due,
                    "cost": total_cost,
                },
            )

        return {
            "id": sale_id,
            "invoice_no": invoice_no,
            "grand_total": totals.grand_total,
            "paid_amount": paid,
            "due_amount": due,
            "total_cost": total_cost,
            "totals": totals.as_dict(),
        }

    def _validate_payments(self, payments: list[PaymentInput]) -> dict[int, dict[str, Any]]:
        methods: dict[int, dict[str, Any]] = {}
        for payment in payments:
            require_id(payment.method_id, "পেমেন্ট মেথড")
            if payment.amount <= 0:
                raise ValidationError("পেমেন্টের পরিমাণ ধনাত্মক হতে হবে")
            row = self.db.query_one(
                "SELECT * FROM payment_methods WHERE id=? AND is_active=1", (payment.method_id,)
            )
            if row is None:
                raise NotFoundError("পেমেন্ট মেথড খুঁজে পাওয়া যায়নি")
            methods[payment.method_id] = dict(row)
        return methods

    # --------------------------------------------------------------- cancel
    def cancel(self, sale_id: int, *, reason: str, actor: str = "") -> dict[str, Any]:
        """Cancel a sale by reversing stock, due and cash — never by deleting rows."""
        require_id(sale_id, "ইনভয়েস")
        reason = optional_text(reason, max_length=300) or "বাতিল"
        sale = self.get(sale_id)
        if sale["status"] == "cancelled":
            raise BusinessRuleError("এই ইনভয়েস আগেই বাতিল করা হয়েছে")
        returned = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(quantity),0) FROM sales_return_items WHERE sale_item_id IN "
                "(SELECT id FROM sale_items WHERE sale_id=?)",
                (sale_id,),
            )
        )
        if returned:
            raise BusinessRuleError("এই ইনভয়েসে রিটার্ন হয়েছে — বাতিলের বদলে রিটার্ন ব্যবহার করুন")

        day = date.today().isoformat()
        now = datetime.now().isoformat(timespec="seconds")
        with self.db.transaction():
            items = self.db.query("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,))
            for item in items:
                self.inventory.apply_movement(
                    product_id=int(item["product_id"]),
                    qty_delta=int(item["quantity"]),
                    movement_type="sales_return_restock",
                    movement_date=day,
                    unit_cost=int(item["unit_cost"]),
                    received_value=int(item["total_cost"]),
                    reference_type="sale_cancel",
                    reference_id=sale_id,
                    notes=f"বাতিল: {sale['invoice_no']} — {reason}",
                    allow_negative=True,
                )
            if sale["customer_id"] is not None:
                self.db.execute(
                    "UPDATE customers SET current_due = current_due - ? WHERE id=?",
                    (int(sale["due_amount"]), sale["customer_id"]),
                )
            cash_rows = self.db.query(
                """SELECT sp.amount, sp.payment_method_id, pm.is_cash
                     FROM sale_payments sp JOIN payment_methods pm ON pm.id=sp.payment_method_id
                    WHERE sp.sale_id=?""",
                (sale_id,),
            )
            session_id = None
            cash_refund = sum(int(r["amount"]) for r in cash_rows if r["is_cash"])
            if cash_refund > 0:
                session_id = self.cash.require_open_session()
                self.cash.record_movement(
                    session_id=session_id,
                    movement_type="sale_cancel_refund",
                    amount=-cash_refund,
                    payment_method_id=int(cash_rows[0]["payment_method_id"]),
                    reference_type="sale_cancel",
                    reference_id=sale_id,
                    notes=f"বাতিল: {sale['invoice_no']}",
                )
            self.db.execute(
                "UPDATE sales SET status='cancelled', cancelled_at=?, notes=notes || ? WHERE id=?",
                (now, f"\n[বাতিল: {reason}]", sale_id),
            )
            self.db.execute(
                "UPDATE transactions SET status='cancelled', notes=notes || ? "
                "WHERE txn_type='sale' AND reference_id=?",
                (f" [বাতিল: {reason}]", sale_id),
            )
            self.audit.log(
                "sale",
                sale_id,
                "cancel",
                f"সেলস বাতিল {sale['invoice_no']} — {reason}",
                before={"status": sale["status"]},
                after={"status": "cancelled"},
            )
        return {"id": sale_id, "status": "cancelled", "restocked_items": len(items)}

    # -------------------------------------------------------------- queries
    def get(self, sale_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT s.*, c.name AS customer_name, c.phone AS customer_phone,
                      c.address AS customer_address
                 FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                WHERE s.id=?""",
            (sale_id,),
        )
        if row is None:
            raise NotFoundError("ইনভয়েস খুঁজে পাওয়া যায়নি")
        sale = dict(row)
        sale["items"] = [
            dict(r) for r in self.db.query("SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,))
        ]
        sale["payments"] = [
            dict(r)
            for r in self.db.query(
                """SELECT sp.*, pm.name AS method_name, pm.is_cash
                     FROM sale_payments sp JOIN payment_methods pm ON pm.id=sp.payment_method_id
                    WHERE sp.sale_id=? ORDER BY sp.id""",
                (sale_id,),
            )
        ]
        return sale

    def find_by_invoice(self, invoice_no: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT id FROM sales WHERE invoice_no=?", (invoice_no.strip(),))
        return self.get(int(row["id"])) if row else None

    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        query: str = "",
        customer_id: int | None = None,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("s.sale_date >= ?")
            params.append(start)
        if end:
            where.append("s.sale_date <= ?")
            params.append(end)
        if customer_id is not None:
            where.append("s.customer_id = ?")
            params.append(customer_id)
        if status:
            where.append("s.status = ?")
            params.append(status)
        if query:
            where.append("(s.invoice_no LIKE ? OR c.name_normalized LIKE ? OR c.phone LIKE ?)")
            term = f"%{query.strip().lower()}%"
            params.extend([term, term, term])
        clause = " AND ".join(where)
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE {clause}",
                params,
            )
        )
        rows = self.db.query(
            f"""SELECT s.*, c.name AS customer_name
                  FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                 WHERE {clause} ORDER BY s.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total}
