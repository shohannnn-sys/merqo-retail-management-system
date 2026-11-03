"""Exact money arithmetic for Retvia.

All monetary values in this application are **integer poisha**
(1 Bangladeshi Taka = 100 poisha). Binary floating point is never used for money.

The single rounding policy for the whole product is *round half up, away from
zero*, implemented by :func:`round_div`. Every service must use these helpers so
that the same transaction produces identical numbers in every report.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

POISHA_PER_TAKA = 100
BASIS_POINTS_PER_PERCENT = 100
BASIS_POINTS_PER_WHOLE = 10_000

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text: str) -> str:
    """Convert Bangla/Arabic-Indic digits to ASCII digits.

    Business users in Bangladesh type amounts with either digit set; both must
    parse to the same value.
    """
    return text.translate(_BANGLA_DIGITS).translate(_ARABIC_DIGITS)


def round_div(numerator: int, denominator: int) -> int:
    """Divide two integers and round half up (away from zero on a tie).

    This is the only rounding boundary in the financial engine.

    >>> round_div(5, 2)
    3
    >>> round_div(-5, 2)
    -3
    >>> round_div(1, 3)
    0
    """
    if denominator == 0:
        raise ZeroDivisionError("division by zero in monetary calculation")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * -numerator + denominator) // (2 * denominator))


def parse_money(value: str | int | Decimal | None) -> int:
    """Parse a user-supplied amount into integer poisha.

    Accepts Bangla or English digits, thousands separators, a leading currency
    symbol and surrounding whitespace. Rejects anything that is not a finite
    number with at most two decimal places of *significance* after rounding.

    >>> parse_money("১২৩.৪৫")
    12345
    >>> parse_money("1,250.00")
    125000
    >>> parse_money("৳ 99.995")
    10000
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value * POISHA_PER_TAKA
    if isinstance(value, Decimal):
        dec = value
    else:
        cleaned = normalize_digits(str(value)).strip()
        cleaned = cleaned.replace(",", "").replace("৳", "").replace("\u00a0", "")
        cleaned = cleaned.replace(" ", "").replace("BDT", "").replace("Tk", "")
        if cleaned in ("", "-", "+"):
            return 0
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"টাকার পরিমাণ সঠিক নয়: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError("টাকার পরিমাণ সসীম সংখ্যা হতে হবে")
    with localcontext() as ctx:
        ctx.prec = 34
        return int((dec * POISHA_PER_TAKA).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_money(
    poisha: int,
    *,
    symbol: str = "",
    decimals: int = 2,
    grouping: bool = True,
    bangla_digits: bool = False,
) -> str:
    """Render integer poisha as a display string.

    Presentation-only: never feed the result back into a calculation.
    """
    if decimals not in (0, 1, 2):
        raise ValueError("দশমিক ঘর ০, ১ বা ২ হতে হবে")
    negative = poisha < 0
    magnitude = abs(poisha)
    # Round to the requested display precision using the single rounding policy.
    divisor = 10 ** (2 - decimals)
    scaled = round_div(magnitude, divisor)
    whole, frac = divmod(scaled, 10**decimals) if decimals else (scaled, 0)
    text = _group(whole) if grouping else str(whole)
    if decimals > 0:
        text = f"{text}.{frac:0{decimals}d}"
    if negative and scaled != 0:
        text = f"-{text}"
    if symbol:
        text = f"{symbol}{text}"
    if bangla_digits:
        text = text.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
    return text


def _group(whole: int) -> str:
    """Group thousands in the South Asian convention (1,23,45,678)."""
    digits = str(whole)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def percent_of(amount: int, basis_points: int) -> int:
    """Return ``amount × basis_points / 10000`` rounded half up.

    Percentages are stored as integer basis points (10% = 1000 bp) so that no
    fractional percentage ever becomes a float.
    """
    return round_div(amount * basis_points, BASIS_POINTS_PER_WHOLE)


def percent_to_basis_points(percent: str | int | Decimal) -> int:
    """Parse a percentage such as ``"7.5"`` into basis points (750)."""
    if isinstance(percent, int):
        return percent * BASIS_POINTS_PER_PERCENT
    dec = Decimal(normalize_digits(str(percent)).strip() or "0")
    if not dec.is_finite():
        raise ValueError("শতকরা হার সসীম সংখ্যা হতে হবে")
    with localcontext() as ctx:
        ctx.prec = 34
        return int((dec * BASIS_POINTS_PER_PERCENT).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def allocate(total: int, weights: Sequence[int]) -> list[int]:
    """Distribute ``total`` across ``weights`` using the largest-remainder method.

    Guarantees ``sum(result) == total`` exactly, which is what makes per-product
    profit reports reconcile with invoice totals after an invoice-level discount.

    >>> allocate(100, [1, 1, 1])
    [34, 33, 33]
    >>> allocate(0, [5, 5])
    [0, 0]
    """
    if not weights:
        if total != 0:
            raise ValueError("শূন্য ওজনের বিপরীতে টাকা বণ্টন করা যায় না")
        return []
    if any(w < 0 for w in weights):
        raise ValueError("ওজন ঋণাত্মক হতে পারে না")
    weight_sum = sum(weights)
    if weight_sum == 0:
        # Nothing to weight by: spread evenly, remainder to the first lines.
        base, extra = divmod(total, len(weights))
        return [base + (1 if i < extra else 0) for i in range(len(weights))]

    sign = -1 if total < 0 else 1
    magnitude = abs(total)
    raw = [magnitude * w for w in weights]
    floors = [r // weight_sum for r in raw]
    remainder = magnitude - sum(floors)
    order = sorted(
        range(len(weights)),
        key=lambda i: (-(raw[i] % weight_sum), -weights[i], i),
    )
    for i in order[:remainder]:
        floors[i] += 1
    return [sign * f for f in floors]


def sum_poisha(values: Iterable[int]) -> int:
    """Sum monetary integers (kept explicit for readability at call sites)."""
    return sum(values)
