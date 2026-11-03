"""Exact quantity arithmetic for Retvia.

Quantities are stored as **integer milli-units** (1 unit = 1000 milli-units) so
that kilogram, gram, litre and millilitre quantities are exact. A unit's
``decimal_precision`` (0–3) controls how a quantity is displayed and validated.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .money import normalize_digits, round_div

MILLI_PER_UNIT = 1000
MAX_PRECISION = 3


def parse_quantity(value: str | int | Decimal | None, *, precision: int = MAX_PRECISION) -> int:
    """Parse a quantity into integer milli-units, rounded to ``precision`` decimals.

    >>> parse_quantity("1.5")
    1500
    >>> parse_quantity("০.২৫০")
    250
    >>> parse_quantity("2", precision=0)
    2000
    """
    if not 0 <= precision <= MAX_PRECISION:
        raise ValueError("ইউনিটের দশমিক নির্ভুলতা ০ থেকে ৩ এর মধ্যে হতে হবে")
    if value is None:
        return 0
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        dec = value
    else:
        cleaned = normalize_digits(str(value)).strip().replace(",", "").replace(" ", "")
        if cleaned in ("", "-", "+"):
            return 0
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"পরিমাণ সঠিক নয়: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError("পরিমাণ সসীম সংখ্যা হতে হবে")
    with localcontext() as ctx:
        ctx.prec = 34
        scaled = dec * MILLI_PER_UNIT
        quantum = Decimal(10) ** (MAX_PRECISION - precision)
        rounded = (scaled / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP) * quantum
        return int(rounded)


def format_quantity(milli: int, *, precision: int = MAX_PRECISION, trim: bool = True) -> str:
    """Render milli-units for display, trimming trailing zeros by default."""
    if not 0 <= precision <= MAX_PRECISION:
        raise ValueError("ইউনিটের দশমিক নির্ভুলতা ০ থেকে ৩ এর মধ্যে হতে হবে")
    negative = milli < 0
    magnitude = abs(milli)
    whole, frac = divmod(magnitude, MILLI_PER_UNIT)
    if precision == 0:
        text = str(round_div(magnitude, MILLI_PER_UNIT))
    else:
        frac_text = f"{frac:03d}"[:precision]
        if trim:
            frac_text = frac_text.rstrip("0")
        text = f"{whole}.{frac_text}" if frac_text else str(whole)
    return f"-{text}" if negative else text


def line_total(unit_price_poisha: int, quantity_milli: int) -> int:
    """Money for a line: price per whole unit × quantity, rounded half up.

    >>> line_total(1250, 1500)   # 12.50 × 1.5
    1875
    """
    return round_div(unit_price_poisha * quantity_milli, MILLI_PER_UNIT)


def unit_cost_from_total(total_poisha: int, quantity_milli: int) -> int:
    """Derive a per-unit price from a line total (used by imports and returns)."""
    if quantity_milli == 0:
        raise ZeroDivisionError("শূন্য পরিমাণ থেকে একক মূল্য নির্ণয় করা যায় না")
    return round_div(total_poisha * MILLI_PER_UNIT, quantity_milli)


def to_units(milli: int) -> Decimal:
    """Exact decimal representation of a quantity, for reporting only."""
    return Decimal(milli) / Decimal(MILLI_PER_UNIT)
