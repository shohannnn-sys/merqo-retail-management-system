"""Service-layer input validation. Every mutation validates before touching SQL."""

from __future__ import annotations

import re
from datetime import date, datetime

from .errors import ValidationError
from .money import BASIS_POINTS_PER_WHOLE
from .quantity import MAX_PRECISION
from .textnorm import clean_text, normalize_phone

_SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,63}$")
_BARCODE_RE = re.compile(r"^[A-Za-z0-9\-]{1,64}$")


def require_text(
    value: str | None,
    field: str = "তথ্য",
    *,
    max_length: int = 255,
    min_length: int = 1,
) -> str:
    cleaned = clean_text(value, max_length=max_length)
    if len(cleaned) < min_length:
        raise ValidationError(f"{field} আবশ্যক")
    return cleaned


def optional_text(value: str | None, *, max_length: int = 1000) -> str:
    return clean_text(value, max_length=max_length)


def require_positive_int(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{field} ধনাত্মক পূর্ণসংখ্যা হতে হবে")
    return value


def require_non_negative_int(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationError(f"{field} ঋণাত্মক হতে পারে না")
    return value


def require_non_negative_money(poisha: int, field: str) -> int:
    if not isinstance(poisha, int) or isinstance(poisha, bool):
        raise ValidationError(f"{field} পূর্ণসংখ্যা পয়শায় হতে হবে")
    if poisha < 0:
        raise ValidationError(f"{field} ঋণাত্মক হতে পারে না")
    return poisha


def require_percent_bp(basis_points: int, field: str, *, max_bp: int = BASIS_POINTS_PER_WHOLE) -> int:
    if not isinstance(basis_points, int) or isinstance(basis_points, bool):
        raise ValidationError(f"{field} শতকরা হার সঠিক নয়")
    if basis_points < 0 or basis_points > max_bp:
        raise ValidationError(f"{field} ০% থেকে {max_bp // 100}% এর মধ্যে হতে হবে")
    return basis_points


def require_precision(precision: int) -> int:
    if not isinstance(precision, int) or not 0 <= precision <= MAX_PRECISION:
        raise ValidationError("ইউনিটের দশমিক নির্ভুলতা ০ থেকে ৩ এর মধ্যে হতে হবে")
    return precision


def validate_sku(sku: str | None) -> str:
    cleaned = require_text(sku, "এসকেইউ (SKU)", max_length=64)
    if not _SKU_RE.match(cleaned):
        raise ValidationError("এসকেইউ-তে অক্ষর, সংখ্যা, ড্যাশ, ডট, আন্ডারস্কোর বা স্ল্যাশ ব্যবহার করুন")
    return cleaned


def validate_barcode(code: str | None) -> str:
    cleaned = require_text(code, "বারকোড", max_length=64)
    if not _BARCODE_RE.match(cleaned):
        raise ValidationError("বারকোডে শুধু অক্ষর, সংখ্যা ও ড্যাশ ব্যবহার করা যাবে")
    return cleaned


def validate_phone(phone: str | None, *, required: bool = False) -> str:
    normalized = normalize_phone(phone)
    if not normalized:
        if required:
            raise ValidationError("মোবাইল নম্বর আবশ্যক")
        return ""
    if not normalized.isdigit() or not 6 <= len(normalized) <= 15:
        raise ValidationError("মোবাইল নম্বর সঠিক নয়")
    return normalized


def validate_email(email: str | None) -> str:
    cleaned = clean_text(email, max_length=255)
    if not cleaned:
        return ""
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
        raise ValidationError("ইমেইল ঠিকানা সঠিক নয়")
    return cleaned


def validate_date(value: str | date | datetime | None, field: str = "তারিখ") -> str:
    """Return an ISO ``YYYY-MM-DD`` string; accepts Bangla digits."""
    from .money import normalize_digits

    if value is None:
        raise ValidationError(f"{field} আবশ্যক")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = normalize_digits(str(value)).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field} সঠিক নয় (YYYY-MM-DD)") from exc


def validate_date_range(start: str | date, end: str | date) -> tuple[str, str]:
    start_iso = validate_date(start, "শুরুর তারিখ")
    end_iso = validate_date(end, "শেষ তারিখ")
    if start_iso > end_iso:
        raise ValidationError("শুরুর তারিখ শেষ তারিখের পরে হতে পারে না")
    return start_iso, end_iso


def validate_choice(value: str, allowed: tuple[str, ...] | set[str], field: str) -> str:
    if value not in allowed:
        raise ValidationError(f"{field} মান সঠিক নয়")
    return value


def require_id(value: int | None, field: str) -> int:
    if value is None:
        raise ValidationError(f"{field} নির্বাচন করা আবশ্যক")
    return require_positive_int(value, field)
