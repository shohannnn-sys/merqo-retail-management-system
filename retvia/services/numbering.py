"""Atomic document numbering.

Numbers are allocated inside the caller's transaction using an UPSERT with
RETURNING, so two concurrent sales can never receive the same invoice number.
A UNIQUE index on the document number is the final backstop.
"""

from __future__ import annotations

from datetime import date

from ..core.errors import ValidationError
from ..data.db import Database
from .settings import SettingsService

_PREFIX_KEYS = {
    "sale": "prefix_sale",
    "purchase": "prefix_purchase",
    "sales_return": "prefix_sales_return",
    "purchase_return": "prefix_purchase_return",
    "customer_payment": "prefix_customer_payment",
    "supplier_payment": "prefix_supplier_payment",
    "expense": "prefix_expense",
    "adjustment": "prefix_adjustment",
}

_DEFAULT_PREFIXES = {
    "sale": "INV",
    "purchase": "PUR",
    "sales_return": "SRT",
    "purchase_return": "PRT",
    "customer_payment": "CRC",
    "supplier_payment": "SPY",
    "expense": "EXP",
    "adjustment": "ADJ",
}


class NumberingService:
    def __init__(self, db: Database, settings: SettingsService | None = None) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)

    def next_number(self, doc_type: str, *, on_date: str | date | None = None) -> str:
        if doc_type not in _PREFIX_KEYS:
            raise ValidationError(f"অজানা ডকুমেন্ট ধরন: {doc_type}")
        if isinstance(on_date, date):
            period = on_date.year
        elif isinstance(on_date, str) and len(on_date) >= 4:
            period = int(on_date[:4])
        else:
            period = date.today().year
        prefix = self.settings.get(_PREFIX_KEYS[doc_type], _DEFAULT_PREFIXES[doc_type])
        prefix = (prefix or _DEFAULT_PREFIXES[doc_type]).strip().upper()

        row = self.db.query_one(
            """INSERT INTO invoice_sequences (doc_type, period, prefix, next_number)
               VALUES (?, ?, ?, 2)
               ON CONFLICT(doc_type, period) DO UPDATE
                 SET next_number = next_number + 1
               RETURNING next_number - 1 AS allocated""",
            (doc_type, str(period), prefix),
        )
        if row is None:
            raise ValidationError("ডকুমেন্ট নম্বর তৈরি করা যায়নি")
        allocated = int(row["allocated"])
        return f"{prefix}-{period}-{allocated:05d}"

    def peek(self, doc_type: str, period: int | None = None) -> str:
        """Preview the next number without consuming it (for UI display only)."""
        period = period or date.today().year
        prefix = (
            self.settings.get(_PREFIX_KEYS.get(doc_type, ""), _DEFAULT_PREFIXES.get(doc_type, "DOC"))
            .strip()
            .upper()
        )
        row = self.db.query_one(
            "SELECT next_number FROM invoice_sequences WHERE doc_type=? AND period=?",
            (doc_type, str(period)),
        )
        nxt = int(row["next_number"]) if row else 1
        return f"{prefix}-{period}-{nxt:05d}"
