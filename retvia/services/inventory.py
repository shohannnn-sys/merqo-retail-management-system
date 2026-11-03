"""Inventory engine: moving-average costing and an append-only stock ledger.

Invariants maintained on every movement:

* ``products.stock_qty`` == Σ ``stock_movements.qty_delta`` for the product.
* ``products.stock_value`` == Σ ``stock_movements.value_delta`` for the product.
* Cost of goods issued == the negative of the issue movement's ``value_delta``,
  so COGS in profit reports always reconciles with the inventory ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..core.errors import InsufficientStockError, NotFoundError, ValidationError
from ..core.money import round_div
from ..core.quantity import MILLI_PER_UNIT, format_quantity
from ..core.validation import require_id, require_text, validate_choice, validate_date
from ..data.db import Database
from .audit import AuditService
from .numbering import NumberingService
from .settings import SettingsService

RECEIPT_TYPES = {"purchase", "sales_return_restock", "opening", "adjustment_in"}
ISSUE_TYPES = {"sale", "purchase_return", "adjustment_out"}
ADJUSTMENT_TYPES = ("damage", "loss", "expiry", "count_increase", "count_decrease", "opening")
_WRITE_OFF_TYPES = {"damage", "loss", "expiry"}


@dataclass(slots=True)
class MovementResult:
    movement_id: int
    qty_before: int
    qty_after: int
    unit_cost: int
    value_delta: int
    avg_cost_after: int
    stock_value_after: int


class InventoryService:
    def __init__(
        self,
        db: Database,
        settings: SettingsService | None = None,
        audit: AuditService | None = None,
        numbering: NumberingService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.numbering = numbering or NumberingService(db, self.settings)

    # ------------------------------------------------------------------ core
    def _product(self, product_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))
        if row is None:
            raise NotFoundError("প্রোডাক্ট খুঁজে পাওয়া যায়নি")
        return dict(row)

    def apply_movement(
        self,
        *,
        product_id: int,
        qty_delta: int,
        movement_type: str,
        movement_date: str,
        unit_cost: int | None = None,
        received_value: int | None = None,
        issued_value: int | None = None,
        reference_type: str = "",
        reference_id: int | None = None,
        notes: str = "",
        allow_negative: bool | None = None,
    ) -> MovementResult:
        """Apply one stock movement and update quantity, MAC and book value.

        Must be called inside the caller's transaction.

        ``received_value`` is the authoritative money value of a receipt (the
        purchase line's net amount); when omitted it is derived from
        ``unit_cost × qty``.
        """
        if qty_delta == 0:
            raise ValidationError("পরিমাণ শূন্য হতে পারে না")
        product = self._product(product_id)
        if not product["track_stock"]:
            # Non-stock items (services) still get a ledger row for traceability
            # but do not change quantity or value.
            mid = self.db.insert(
                """INSERT INTO stock_movements
                   (product_id, movement_type, qty_delta, qty_before, qty_after,
                    unit_cost, value_delta, avg_cost_after, reference_type,
                    reference_id, movement_date, notes)
                   VALUES (?,?,0,0,0,?,0,0,?,?,?,?)""",
                (
                    product_id, movement_type, unit_cost or 0,
                    reference_type, reference_id, movement_date, notes,
                ),
            )
            return MovementResult(mid, 0, 0, 0, 0, 0, 0)

        qty_before = int(product["stock_qty"])
        avg_before = int(product["avg_cost"])
        value_before = int(product["stock_value"])
        qty_after = qty_before + qty_delta

        if allow_negative is None:
            allow_negative = self.settings.get_bool("allow_negative_stock", False)
        if qty_after < 0 and not allow_negative:
            raise InsufficientStockError(
                f"পর্যাপ্ত স্টক নেই — {product['name']}: "
                f"মজুদ {format_quantity(qty_before)}, "
                f"প্রয়োজন {format_quantity(abs(qty_delta))}"
            )

        if qty_delta > 0:
            # ---- receipt: recompute moving average cost
            cost = int(unit_cost if unit_cost is not None else avg_before)
            incoming = (
                int(received_value)
                if received_value is not None
                else round_div(cost * qty_delta, MILLI_PER_UNIT)
            )
            # Negative on-hand stock is already costed; value it at zero so a
            # receipt does not inherit a phantom negative value.
            base_qty = max(qty_before, 0)
            base_value = value_before if qty_before >= 0 else 0
            if qty_after > 0:
                avg_after = round_div((base_value + incoming) * MILLI_PER_UNIT, qty_after)
            else:
                avg_after = cost or avg_before
            value_after = round_div(avg_after * qty_after, MILLI_PER_UNIT)
            if base_qty == 0 and qty_after > 0:
                # First receipt: book value is exactly what was paid.
                value_after = incoming
                avg_after = round_div(incoming * MILLI_PER_UNIT, qty_after)
            value_delta = value_after - value_before
            issue_cost = 0
        else:
            # ---- issue: cost at the prevailing MAC (snapshotted for the caller)
            cost = int(unit_cost if unit_cost is not None else avg_before)
            issued = (
                int(issued_value) if issued_value is not None
                else round_div(cost * (-qty_delta), MILLI_PER_UNIT)
            )
            if qty_after == 0 and issued_value is None:
                # Clear any residual rounding so an empty shelf has zero value.
                issued = value_before
            value_after = value_before - issued
            avg_after = avg_before if qty_after != 0 else 0
            value_delta = -issued
            issue_cost = issued

        mid = self.db.insert(
            """INSERT INTO stock_movements
               (product_id, movement_type, qty_delta, qty_before, qty_after, unit_cost,
                value_delta, avg_cost_after, reference_type, reference_id, movement_date, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                product_id, movement_type, qty_delta, qty_before, qty_after, cost,
                value_delta, avg_after, reference_type, reference_id, movement_date, notes,
            ),
        )
        self.db.execute(
            """UPDATE products
                  SET stock_qty=?, avg_cost=?, stock_value=?,
                      updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?""",
            (qty_after, avg_after, value_after, product_id),
        )
        return MovementResult(mid, qty_before, qty_after, cost, value_delta, avg_after, value_after)

    # ------------------------------------------------------------ adjustments
    def adjust(
        self,
        *,
        product_id: int,
        adjustment_type: str,
        quantity: int,
        reason: str,
        adjustment_date: str | date,
        counted_qty: int | None = None,
        actor: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Record damage/loss/expiry or a physical count correction.

        For ``count_increase``/``count_decrease`` pass ``counted_qty`` (the
        physically counted quantity); the delta is derived so the ledger shows
        exactly how the book figure was corrected.
        """
        require_id(product_id, "প্রোডাক্ট")
        validate_choice(adjustment_type, ADJUSTMENT_TYPES, "স্টক সমন্বয়ের ধরন")
        reason = require_text(reason, "সমন্বয়ের কারণ", max_length=300)
        day = validate_date(adjustment_date, "সমন্বয়ের তারিখ")
        product = self._product(product_id)

        if adjustment_type in ("count_increase", "count_decrease"):
            if counted_qty is None:
                raise ValidationError("গণনাকৃত পরিমাণ আবশ্যক")
            delta = int(counted_qty) - int(product["stock_qty"])
            if delta == 0:
                raise ValidationError("গণনাকৃত পরিমাণ বর্তমান মজুদের সমান — সমন্বয় প্রয়োজন নেই")
            if adjustment_type == "count_increase" and delta < 0:
                raise ValidationError("গণনাকৃত পরিমাণ মজুদের চেয়ে কম — 'গণনা ঘাটতি' নির্বাচন করুন")
            if adjustment_type == "count_decrease" and delta > 0:
                raise ValidationError("গণনাকৃত পরিমাণ মজুদের চেয়ে বেশি — 'গণনা বৃদ্ধি' নির্বাচন করুন")
        else:
            if quantity <= 0:
                raise ValidationError("পরিমাণ ধনাত্মক হতে হবে")
            delta = -int(quantity)

        movement_type = "adjustment_in" if delta > 0 else "adjustment_out"
        with self.db.transaction():
            number = self.numbering.next_number("adjustment", on_date=day)
            result = self.apply_movement(
                product_id=product_id,
                qty_delta=delta,
                movement_type=movement_type,
                movement_date=day,
                unit_cost=int(product["avg_cost"]),
                reference_type="stock_adjustment",
                notes=reason,
                allow_negative=True,
            )
            adj_id = self.db.insert(
                """INSERT INTO stock_adjustments
                   (adjustment_no, product_id, adjustment_type, qty_delta, unit_cost,
                    value_delta, reason, adjusted_by, adjustment_date, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    number, product_id, adjustment_type, delta, result.unit_cost,
                    result.value_delta, reason, actor, day, notes,
                ),
            )
            self.db.execute(
                "UPDATE stock_movements SET reference_id=? WHERE id=?", (adj_id, result.movement_id)
            )
            self.audit.log(
                "stock_adjustment", adj_id, "create",
                f"{product['name']} — {adjustment_type} {format_quantity(delta)} ({reason})",
                after={"qty_delta": delta, "value_delta": result.value_delta},
            )
        return {
            "id": adj_id,
            "adjustment_no": number,
            "qty_delta": delta,
            "value_delta": result.value_delta,
            "qty_after": result.qty_after,
        }

    # ---------------------------------------------------------------- queries
    def ledger(
        self,
        product_id: int,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = ["SELECT * FROM stock_movements WHERE product_id = ?"]
        params: list[Any] = [product_id]
        if start:
            sql.append("AND movement_date >= ?")
            params.append(start)
        if end:
            sql.append("AND movement_date <= ?")
            params.append(end)
        sql.append("ORDER BY id DESC LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        return [dict(r) for r in self.db.query(" ".join(sql), params)]

    def valuation(self) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT COALESCE(SUM(stock_value),0) AS total_value,
                      COALESCE(SUM(stock_qty),0) AS total_qty,
                      COUNT(*) AS product_count
                 FROM products WHERE status='active' AND track_stock=1"""
        )
        return dict(row) if row else {"total_value": 0, "total_qty": 0, "product_count": 0}

    def valuation_rows(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT p.id, p.name, p.sku, p.stock_qty, p.avg_cost, p.stock_value,
                          u.symbol AS unit_symbol, u.decimal_precision
                     FROM products p JOIN units u ON u.id = p.unit_id
                    WHERE p.status='active' AND p.track_stock=1
                    ORDER BY p.stock_value DESC, p.name"""
            )
        ]

    def low_stock(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT p.*, u.symbol AS unit_symbol, u.decimal_precision
                     FROM products p JOIN units u ON u.id=p.unit_id
                    WHERE p.status='active' AND p.track_stock=1
                      AND p.stock_qty <= p.min_stock_qty AND p.stock_qty > 0
                    ORDER BY (p.stock_qty - p.min_stock_qty), p.name LIMIT ?""",
                (limit,),
            )
        ]

    def out_of_stock(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                """SELECT p.*, u.symbol AS unit_symbol, u.decimal_precision
                     FROM products p JOIN units u ON u.id=p.unit_id
                    WHERE p.status='active' AND p.track_stock=1 AND p.stock_qty <= 0
                    ORDER BY p.name LIMIT ?""",
                (limit,),
            )
        ]

    def write_off_value(self, start: str, end: str) -> int:
        placeholders = ",".join("?" for _ in _WRITE_OFF_TYPES)
        return int(
            self.db.scalar(
                f"""SELECT COALESCE(SUM(-value_delta),0) FROM stock_adjustments
                     WHERE adjustment_type IN ({placeholders})
                       AND adjustment_date BETWEEN ? AND ?""",
                (*sorted(_WRITE_OFF_TYPES), start, end),
            )
        )

    # --------------------------------------------------------- reconciliation
    def reconcile(self) -> list[dict[str, Any]]:
        """Return every product whose ledger disagrees with its cached balances."""
        rows = self.db.query(
            """SELECT p.id, p.name, p.sku, p.stock_qty, p.stock_value,
                      COALESCE(SUM(m.qty_delta),0) AS ledger_qty,
                      COALESCE(SUM(m.value_delta),0) AS ledger_value
                 FROM products p
                 LEFT JOIN stock_movements m ON m.product_id = p.id
                WHERE p.track_stock = 1
                GROUP BY p.id"""
        )
        problems = []
        for r in rows:
            if r["stock_qty"] != r["ledger_qty"] or r["stock_value"] != r["ledger_value"]:
                problems.append(
                    {
                        "product_id": r["id"],
                        "name": r["name"],
                        "sku": r["sku"],
                        "stock_qty": r["stock_qty"],
                        "ledger_qty": r["ledger_qty"],
                        "stock_value": r["stock_value"],
                        "ledger_value": r["ledger_value"],
                    }
                )
        return problems
