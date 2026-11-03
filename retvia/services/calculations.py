"""The single centralized cart/invoice calculation engine.

Both the POS preview and the persisted sale use this module, so what the cashier
sees is exactly what is stored and what every report later reproduces.

Order of operations (normative — see docs/FINANCIAL_POLICY.md):
    gross → item discount → net → invoice-discount allocation → tax → totals
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.errors import ValidationError
from ..core.money import allocate, percent_of, round_div
from ..core.quantity import MILLI_PER_UNIT


@dataclass(slots=True)
class CartItem:
    product_id: int
    quantity: int  # milli-units
    unit_price: int  # poisha per whole unit
    discount_type: str = "none"  # none | percent | fixed
    discount_value: int = 0  # basis points for percent, poisha for fixed
    tax_bp: int = 0
    name: str = ""
    unit_name: str = ""


@dataclass(slots=True)
class CalculatedLine:
    product_id: int
    name: str
    unit_name: str
    quantity: int
    unit_price: int
    gross_amount: int
    discount_type: str
    discount_value: int
    discount_amount: int
    net_before_invoice_discount: int
    invoice_discount_allocated: int
    net_amount: int
    tax_bp: int
    tax_amount: int

    @property
    def total_discount(self) -> int:
        return self.discount_amount + self.invoice_discount_allocated


@dataclass(slots=True)
class CartTotals:
    lines: list[CalculatedLine] = field(default_factory=list)
    subtotal: int = 0
    item_discount: int = 0
    invoice_discount: int = 0
    total_discount: int = 0
    net_sales: int = 0
    tax_amount: int = 0
    grand_total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "subtotal": self.subtotal,
            "item_discount": self.item_discount,
            "invoice_discount": self.invoice_discount,
            "total_discount": self.total_discount,
            "net_sales": self.net_sales,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
        }


def _line_discount(gross: int, discount_type: str, value: int, *, max_bp: int = 10_000) -> int:
    if discount_type == "none" or value == 0:
        return 0
    if value < 0:
        raise ValidationError("ডিস্কাউন্ট ঋণাত্মক হতে পারে না")
    if discount_type == "percent":
        if value > max_bp:
            raise ValidationError("ডিস্কাউন্ট ১০০% এর বেশি হতে পারে না")
        return percent_of(gross, value)
    if discount_type == "fixed":
        if value > gross:
            raise ValidationError("ডিস্কাউন্ট লাইনের মোট মূল্যের বেশি হতে পারে না")
        return value
    raise ValidationError("ডিস্কাউন্টের ধরন সঠিক নয়")


def calculate_cart(
    items: list[CartItem],
    *,
    invoice_discount_type: str = "none",
    invoice_discount_value: int = 0,
    tax_enabled: bool = False,
    max_item_discount_bp: int = 10_000,
    max_invoice_discount_bp: int = 10_000,
) -> CartTotals:
    """Compute all invoice totals exactly, with no floating point anywhere."""
    if not items:
        raise ValidationError("কার্ট খালি — অন্তত একটি প্রোডাক্ট যোগ করুন")

    lines: list[CalculatedLine] = []
    for item in items:
        if item.quantity <= 0:
            raise ValidationError("প্রোডাক্টের পরিমাণ ধনাত্মক হতে হবে")
        if item.unit_price < 0:
            raise ValidationError("প্রোডাক্টের মূল্য ঋণাত্মক হতে পারে না")
        gross = round_div(item.unit_price * item.quantity, MILLI_PER_UNIT)
        discount = _line_discount(gross, item.discount_type, item.discount_value, max_bp=max_item_discount_bp)
        lines.append(
            CalculatedLine(
                product_id=item.product_id,
                name=item.name,
                unit_name=item.unit_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                gross_amount=gross,
                discount_type=item.discount_type,
                discount_value=item.discount_value,
                discount_amount=discount,
                net_before_invoice_discount=gross - discount,
                invoice_discount_allocated=0,
                net_amount=gross - discount,
                tax_bp=item.tax_bp if tax_enabled else 0,
                tax_amount=0,
            )
        )

    subtotal = sum(line.gross_amount for line in lines)
    item_discount = sum(line.discount_amount for line in lines)
    net_before = sum(line.net_before_invoice_discount for line in lines)

    invoice_discount = _line_discount(
        net_before,
        invoice_discount_type,
        invoice_discount_value,
        max_bp=max_invoice_discount_bp,
    )
    if invoice_discount:
        allocations = allocate(invoice_discount, [line.net_before_invoice_discount for line in lines])
        for line, share in zip(lines, allocations, strict=True):
            line.invoice_discount_allocated = share
            line.net_amount = line.net_before_invoice_discount - share

    if tax_enabled:
        for line in lines:
            line.tax_amount = percent_of(line.net_amount, line.tax_bp)

    net_sales = sum(line.net_amount for line in lines)
    tax_amount = sum(line.tax_amount for line in lines)

    totals = CartTotals(
        lines=lines,
        subtotal=subtotal,
        item_discount=item_discount,
        invoice_discount=invoice_discount,
        total_discount=item_discount + invoice_discount,
        net_sales=net_sales,
        tax_amount=tax_amount,
        grand_total=net_sales + tax_amount,
    )
    # Structural guarantees — a violation here is a programming error, not user error.
    assert sum(line.invoice_discount_allocated for line in lines) == invoice_discount
    assert subtotal - totals.total_discount == net_sales
    return totals
