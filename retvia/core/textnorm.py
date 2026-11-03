"""Unicode-aware text helpers: search normalization and safe display."""

from __future__ import annotations

import re
import unicodedata

from .money import normalize_digits

_WHITESPACE = re.compile(r"\s+")


def normalize_search(text: str | None) -> str:
    """Normalize text for case-insensitive, mixed-language searching.

    Applies Unicode NFKC, converts Bangla/Arabic digits to ASCII, casefolds and
    collapses whitespace so that "চিনি ১ কেজি" and "চিনি 1 কেজি" match.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalize_digits(normalized)
    normalized = normalized.casefold()
    return _WHITESPACE.sub(" ", normalized).strip()


def like_pattern(text: str | None) -> str:
    """Build a safe SQL LIKE pattern (escaping is done by the caller via ESCAPE)."""
    normalized = normalize_search(text)
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def clean_text(text: str | None, *, max_length: int | None = None) -> str:
    """Trim user text, strip control characters, and optionally cap its length."""
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\n" or ch == "\t" or unicodedata.category(ch)[0] != "C")
    cleaned = cleaned.strip()
    if max_length is not None and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned


def normalize_phone(phone: str | None) -> str:
    """Normalize a Bangladeshi phone number to a canonical local form.

    ``+8801712345678``, ``8801712345678`` and ``01712345678`` all become
    ``01712345678`` so duplicate customers can be detected reliably.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", normalize_digits(phone))
    if digits.startswith("880") and len(digits) >= 13:
        digits = "0" + digits[3:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits
    return digits


def ellipsize(text: str, limit: int) -> str:
    """Shorten text for table cells without cutting a Bengali grapheme cluster."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
