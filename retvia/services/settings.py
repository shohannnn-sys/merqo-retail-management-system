"""Application settings, business profile and first-run configuration seeding.

Seeding creates *configuration* (units, payment methods, expense categories,
default register). It never creates demo products, customers or transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import ValidationError
from ..core.textnorm import clean_text, normalize_search
from ..core.validation import optional_text, require_text, validate_email, validate_phone
from ..data.db import Database

DEFAULT_SETTINGS: dict[str, str] = {
    # currency & format
    "currency_symbol": "৳",
    "currency_code": "BDT",
    "money_decimals": "2",
    "bangla_digits": "0",
    "date_format": "%d/%m/%Y",
    "time_format": "%I:%M %p",
    # tax
    "tax_enabled": "0",
    "default_tax_bp": "0",
    "tax_label": "ভ্যাট",
    # inventory policy
    "allow_negative_stock": "0",
    "low_stock_only_tracked": "1",
    # discount policy
    "max_invoice_discount_bp": "10000",
    "max_item_discount_bp": "10000",
    # numbering prefixes
    "prefix_sale": "INV",
    "prefix_purchase": "PUR",
    "prefix_sales_return": "SRT",
    "prefix_purchase_return": "PRT",
    "prefix_customer_payment": "CRC",
    "prefix_supplier_payment": "SPY",
    "prefix_expense": "EXP",
    "prefix_adjustment": "ADJ",
    # receipt / printer
    "printer_name": "",
    "paper_width_mm": "80",
    "receipt_margin_mm": "3",
    "receipt_font_size": "9",
    "receipt_line_spacing": "1.15",
    "receipt_show_logo": "1",
    "receipt_auto_cut": "1",
    "receipt_copies": "1",
    "receipt_raster_mode": "0",
    # backup
    "backup_dir": "",
    "backup_auto_enabled": "1",
    "backup_interval_minutes": "120",
    "backup_retention": "20",
    "backup_on_exit": "1",
    # misc
    "business_identity": "",
    "cashier_name": "",
    "require_open_register_for_cash": "1",
}

DEFAULT_UNITS = [
    ("পিস", "pcs", 0),
    ("কেজি", "kg", 3),
    ("গ্রাম", "g", 0),
    ("লিটার", "L", 3),
    ("মিলিলিটার", "ml", 0),
    ("বক্স", "box", 0),
    ("প্যাকেট", "pkt", 0),
    ("ডজন", "dz", 0),
    ("হালি", "hali", 0),
]

DEFAULT_PAYMENT_METHODS = [
    ("ক্যাশ", 1, 1),
    ("বিকাশ", 0, 2),
    ("নগদ", 0, 3),
    ("রকেট", 0, 4),
    ("ব্যাংক", 0, 5),
    ("কার্ড", 0, 6),
]

DEFAULT_EXPENSE_CATEGORIES = [
    "দোকান ভাড়া",
    "বিদ্যুৎ বিল",
    "কর্মচারী বেতন",
    "পরিবহন খরচ",
    "প্যাকেজিং",
    "রক্ষণাবেক্ষণ",
    "ইন্টারনেট বিল",
    "অন্যান্য খরচ",
]


class SettingsService:
    """Typed access to persisted application settings."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> dict[str, str]:
        merged = dict(DEFAULT_SETTINGS)
        for row in self.db.query("SELECT key, value FROM app_settings"):
            merged[row["key"]] = row["value"]
        return merged

    def get(self, key: str, default: str | None = None) -> str:
        row = self.db.query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        if row is not None:
            return str(row["value"])
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key, "")

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key, "1" if default else "0")
        return raw in ("1", "true", "True", "yes")

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS and not key.startswith("ui."):
            raise ValidationError(f"অজানা সেটিং: {key}")
        self.db.execute(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (key, str(value)),
        )

    def update(self, values: dict[str, Any]) -> None:
        with self.db.transaction():
            for key, value in values.items():
                self.set(key, value)


@dataclass(slots=True)
class BusinessProfile:
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    tax_number: str = ""
    logo_path: str = ""
    receipt_footer: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.name.strip())


class BusinessProfileService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self) -> BusinessProfile:
        row = self.db.query_one("SELECT * FROM business_profile WHERE id = 1")
        if row is None:
            return BusinessProfile()
        return BusinessProfile(
            name=row["name"],
            address=row["address"],
            phone=row["phone"],
            email=row["email"],
            tax_number=row["tax_number"],
            logo_path=row["logo_path"],
            receipt_footer=row["receipt_footer"],
        )

    def update(self, profile: BusinessProfile) -> BusinessProfile:
        name = require_text(profile.name, "ব্যবসার নাম", max_length=200)
        phone = validate_phone(profile.phone)
        email = validate_email(profile.email)
        address = optional_text(profile.address, max_length=500)
        tax_number = clean_text(profile.tax_number, max_length=64)
        footer = optional_text(profile.receipt_footer, max_length=300)
        logo = clean_text(profile.logo_path, max_length=1000)
        with self.db.transaction():
            self.db.execute(
                """UPDATE business_profile
                      SET name=?, address=?, phone=?, email=?, tax_number=?,
                          logo_path=?, receipt_footer=?,
                          updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id = 1""",
                (name, address, phone, email, tax_number, logo, footer),
            )
        return self.get()


def seed_defaults(db: Database) -> None:
    """Insert standard configuration on a brand-new database (idempotent)."""
    with db.transaction():
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (key, value)
            )
        for name, symbol, precision in DEFAULT_UNITS:
            db.execute(
                """INSERT OR IGNORE INTO units (name, name_normalized, symbol, decimal_precision)
                   VALUES (?, ?, ?, ?)""",
                (name, normalize_search(name), symbol, precision),
            )
        for name, is_cash, order in DEFAULT_PAYMENT_METHODS:
            db.execute(
                """INSERT OR IGNORE INTO payment_methods (name, name_normalized, is_cash, sort_order)
                   VALUES (?, ?, ?, ?)""",
                (name, normalize_search(name), is_cash, order),
            )
        for name in DEFAULT_EXPENSE_CATEGORIES:
            db.execute(
                "INSERT OR IGNORE INTO expense_categories (name, name_normalized) VALUES (?, ?)",
                (name, normalize_search(name)),
            )
        db.execute(
            "INSERT OR IGNORE INTO cash_registers (name, location) VALUES (?, ?)",
            ("প্রধান ক্যাশ ড্রয়ার", ""),
        )
