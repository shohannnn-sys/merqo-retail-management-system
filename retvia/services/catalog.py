"""Catalog services: categories, units, products and barcodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..core.errors import BusinessRuleError, DuplicateError, NotFoundError, ValidationError
from ..core.textnorm import normalize_search
from ..core.validation import (
    optional_text,
    require_id,
    require_non_negative_int,
    require_non_negative_money,
    require_percent_bp,
    require_precision,
    require_text,
    validate_barcode,
    validate_choice,
    validate_sku,
)
from ..data.db import Database
from .audit import AuditService
from .inventory import InventoryService
from .settings import SettingsService


class CategoryService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def create(self, name: str, *, description: str = "", parent_id: int | None = None) -> int:
        name = require_text(name, "ক্যাটাগরির নাম", max_length=120)
        normalized = normalize_search(name)
        if self.db.query_one("SELECT id FROM categories WHERE name_normalized=?", (normalized,)):
            raise DuplicateError(f"'{name}' নামে ক্যাটাগরি আগে থেকেই রয়েছে")
        if parent_id is not None:
            require_id(parent_id, "প্যারেন্ট ক্যাটাগরি")
        with self.db.transaction():
            cid = self.db.insert(
                "INSERT INTO categories (name, name_normalized, description, parent_id) VALUES (?,?,?,?)",
                (name, normalized, optional_text(description, max_length=300), parent_id),
            )
            self.audit.log("category", cid, "create", f"ক্যাটাগরি তৈরি: {name}")
        return cid

    def update(self, category_id: int, name: str, *, description: str = "") -> None:
        require_id(category_id, "ক্যাটাগরি")
        name = require_text(name, "ক্যাটাগরির নাম", max_length=120)
        normalized = normalize_search(name)
        clash = self.db.query_one(
            "SELECT id FROM categories WHERE name_normalized=? AND id<>?", (normalized, category_id)
        )
        if clash:
            raise DuplicateError(f"'{name}' নামে ক্যাটাগরি আগে থেকেই রয়েছে")
        with self.db.transaction():
            self.db.execute(
                """UPDATE categories SET name=?, name_normalized=?, description=?,
                          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (name, normalized, optional_text(description, max_length=300), category_id),
            )
            self.audit.log("category", category_id, "update", f"ক্যাটাগরি হালনাগাদ: {name}")

    def delete(self, category_id: int) -> None:
        count = int(
            self.db.scalar("SELECT COUNT(*) FROM products WHERE category_id=?", (category_id,))
        )
        if count:
            raise BusinessRuleError(
                f"এই ক্যাটাগরিতে {count}টি প্রোডাক্ট রয়েছে — আগে সেগুলো সরান"
            )
        with self.db.transaction():
            self.db.execute("DELETE FROM categories WHERE id=?", (category_id,))
            self.audit.log("category", category_id, "delete", "ক্যাটাগরি মুছে ফেলা হয়েছে")

    def list(self, *, search: str = "", active_only: bool = False) -> list[dict[str, Any]]:
        sql = [
            """SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id) AS product_count
                 FROM categories c WHERE 1=1"""
        ]
        params: list[Any] = []
        if search:
            sql.append("AND c.name_normalized LIKE ? ESCAPE '\\'")
            params.append(f"%{normalize_search(search)}%")
        if active_only:
            sql.append("AND c.is_active=1")
        sql.append("ORDER BY c.name")
        return [dict(r) for r in self.db.query(" ".join(sql), params)]

    def get(self, category_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM categories WHERE id=?", (category_id,))
        if row is None:
            raise NotFoundError("ক্যাটাগরি খুঁজে পাওয়া যায়নি")
        return dict(row)


class UnitService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def create(self, name: str, *, symbol: str = "", precision: int = 0) -> int:
        name = require_text(name, "ইউনিটের নাম", max_length=60)
        precision = require_precision(precision)
        normalized = normalize_search(name)
        if self.db.query_one("SELECT id FROM units WHERE name_normalized=?", (normalized,)):
            raise DuplicateError(f"'{name}' নামে ইউনিট আগে থেকেই রয়েছে")
        with self.db.transaction():
            uid = self.db.insert(
                "INSERT INTO units (name, name_normalized, symbol, decimal_precision) VALUES (?,?,?,?)",
                (name, normalized, optional_text(symbol, max_length=12), precision),
            )
            self.audit.log("unit", uid, "create", f"ইউনিট তৈরি: {name}")
        return uid

    def update(self, unit_id: int, name: str, *, symbol: str = "", precision: int = 0) -> None:
        require_id(unit_id, "ইউনিট")
        name = require_text(name, "ইউনিটের নাম", max_length=60)
        precision = require_precision(precision)
        normalized = normalize_search(name)
        if self.db.query_one(
            "SELECT id FROM units WHERE name_normalized=? AND id<>?", (normalized, unit_id)
        ):
            raise DuplicateError(f"'{name}' নামে ইউনিট আগে থেকেই রয়েছে")
        used = int(self.db.scalar("SELECT COUNT(*) FROM products WHERE unit_id=?", (unit_id,)))
        if used and precision != self.get(unit_id)["decimal_precision"]:
            raise BusinessRuleError(
                "এই ইউনিটে প্রোডাক্ট রয়েছে — দশমিক নির্ভুলতা পরিবর্তন করা যাবে না"
            )
        with self.db.transaction():
            self.db.execute(
                """UPDATE units SET name=?, name_normalized=?, symbol=?, decimal_precision=?,
                          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (name, normalized, optional_text(symbol, max_length=12), precision, unit_id),
            )
            self.audit.log("unit", unit_id, "update", f"ইউনিট হালনাগাদ: {name}")

    def delete(self, unit_id: int) -> None:
        count = int(self.db.scalar("SELECT COUNT(*) FROM products WHERE unit_id=?", (unit_id,)))
        if count:
            raise BusinessRuleError(f"এই ইউনিটে {count}টি প্রোডাক্ট রয়েছে — মুছে ফেলা যাবে না")
        with self.db.transaction():
            self.db.execute("DELETE FROM units WHERE id=?", (unit_id,))
            self.audit.log("unit", unit_id, "delete", "ইউনিট মুছে ফেলা হয়েছে")

    def list(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM units"
        if active_only:
            sql += " WHERE is_active=1"
        return [dict(r) for r in self.db.query(sql + " ORDER BY name")]

    def get(self, unit_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM units WHERE id=?", (unit_id,))
        if row is None:
            raise NotFoundError("ইউনিট খুঁজে পাওয়া যায়নি")
        return dict(row)


@dataclass(slots=True)
class ProductInput:
    name: str
    sku: str
    unit_id: int
    category_id: int | None = None
    brand: str = ""
    purchase_price: int = 0
    selling_price: int = 0
    opening_qty: int = 0
    min_stock_qty: int = 0
    discount_bp: int = 0
    tax_bp: int = 0
    description: str = ""
    barcode: str = ""
    track_stock: bool = True
    extra_barcodes: list[str] = field(default_factory=list)


class ProductService:
    def __init__(
        self,
        db: Database,
        inventory: InventoryService | None = None,
        audit: AuditService | None = None,
        settings: SettingsService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.inventory = inventory or InventoryService(db, self.settings, self.audit)
        self.units = UnitService(db, self.audit)

    # ------------------------------------------------------------------ CRUD
    def create(self, data: ProductInput, *, opening_date: str | date | None = None) -> int:
        name = require_text(data.name, "প্রোডাক্টের নাম", max_length=200)
        sku = validate_sku(data.sku)
        require_id(data.unit_id, "ইউনিট")
        self.units.get(data.unit_id)
        if data.category_id is not None:
            require_id(data.category_id, "ক্যাটাগরি")
        purchase = require_non_negative_money(data.purchase_price, "পারচেজ মূল্য")
        selling = require_non_negative_money(data.selling_price, "সেলিং মূল্য")
        opening = require_non_negative_int(data.opening_qty, "ওপেনিং স্টক")
        minimum = require_non_negative_int(data.min_stock_qty, "মিনিমাম স্টক")
        discount = require_percent_bp(data.discount_bp, "প্রোডাক্ট ডিস্কাউন্ট")
        tax = require_percent_bp(data.tax_bp, "ট্যাক্স")
        barcode = validate_barcode(data.barcode) if data.barcode else ""

        if self.db.query_one("SELECT id FROM products WHERE sku=?", (sku,)):
            raise DuplicateError(f"'{sku}' এসকেইউ আগে থেকেই রয়েছে")
        if barcode and self.db.query_one("SELECT id FROM barcodes WHERE code=?", (barcode,)):
            raise DuplicateError(f"'{barcode}' বারকোড অন্য প্রোডাক্টে ব্যবহৃত হয়েছে")
        for extra in data.extra_barcodes:
            code = validate_barcode(extra)
            if self.db.query_one("SELECT id FROM barcodes WHERE code=?", (code,)):
                raise DuplicateError(f"'{code}' বারকোড অন্য প্রোডাক্টে ব্যবহৃত হয়েছে")

        day = str(opening_date or date.today().isoformat())
        with self.db.transaction():
            pid = self.db.insert(
                """INSERT INTO products
                   (name, name_normalized, sku, category_id, unit_id, brand, purchase_price,
                    selling_price, opening_qty, min_stock_qty, discount_bp, tax_bp,
                    description, track_stock)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, normalize_search(name), sku, data.category_id, data.unit_id,
                    optional_text(data.brand, max_length=120), purchase, selling, opening,
                    minimum, discount, tax, optional_text(data.description, max_length=1000),
                    1 if data.track_stock else 0,
                ),
            )
            if barcode:
                self.db.execute(
                    "INSERT INTO barcodes (product_id, code, is_primary) VALUES (?,?,1)",
                    (pid, barcode),
                )
            for extra in data.extra_barcodes:
                self.db.execute(
                    "INSERT INTO barcodes (product_id, code, is_primary) VALUES (?,?,0)",
                    (pid, validate_barcode(extra)),
                )
            if opening > 0 and data.track_stock:
                self.inventory.apply_movement(
                    product_id=pid,
                    qty_delta=opening,
                    movement_type="opening",
                    movement_date=day,
                    unit_cost=purchase,
                    reference_type="product_opening",
                    reference_id=pid,
                    notes="ওপেনিং স্টক",
                )
            self.audit.log(
                "product", pid, "create", f"প্রোডাক্ট তৈরি: {name} ({sku})",
                after={"sku": sku, "selling_price": selling, "opening_qty": opening},
            )
        return pid

    def update(self, product_id: int, data: ProductInput) -> None:
        require_id(product_id, "প্রোডাক্ট")
        before = self.get(product_id)
        name = require_text(data.name, "প্রোডাক্টের নাম", max_length=200)
        sku = validate_sku(data.sku)
        self.units.get(require_id(data.unit_id, "ইউনিট"))
        if self.db.query_one(
            "SELECT id FROM products WHERE sku=? AND id<>?", (sku, product_id)
        ):
            raise DuplicateError(f"'{sku}' এসকেইউ আগে থেকেই রয়েছে")
        purchase = require_non_negative_money(data.purchase_price, "পারচেজ মূল্য")
        selling = require_non_negative_money(data.selling_price, "সেলিং মূল্য")
        with self.db.transaction():
            self.db.execute(
                """UPDATE products
                      SET name=?, name_normalized=?, sku=?, category_id=?, unit_id=?, brand=?,
                          purchase_price=?, selling_price=?, min_stock_qty=?, discount_bp=?,
                          tax_bp=?, description=?, track_stock=?,
                          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id=?""",
                (
                    name, normalize_search(name), sku, data.category_id, data.unit_id,
                    optional_text(data.brand, max_length=120), purchase, selling,
                    require_non_negative_int(data.min_stock_qty, "মিনিমাম স্টক"),
                    require_percent_bp(data.discount_bp, "প্রোডাক্ট ডিস্কাউন্ট"),
                    require_percent_bp(data.tax_bp, "ট্যাক্স"),
                    optional_text(data.description, max_length=1000),
                    1 if data.track_stock else 0, product_id,
                ),
            )
            self.audit.log(
                "product", product_id, "update", f"প্রোডাক্ট হালনাগাদ: {name}",
                before={"sku": before["sku"], "selling_price": before["selling_price"]},
                after={"sku": sku, "selling_price": selling},
            )

    def set_status(self, product_id: int, status: str) -> None:
        validate_choice(status, ("active", "archived"), "প্রোডাক্ট স্ট্যাটাস")
        require_id(product_id, "প্রোডাক্ট")
        with self.db.transaction():
            self.db.execute(
                """UPDATE products SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id=?""",
                (status, product_id),
            )
            self.audit.log("product", product_id, "status", f"স্ট্যাটাস পরিবর্তন: {status}")

    def delete(self, product_id: int) -> None:
        """Hard-delete only untouched products; otherwise force archiving."""
        require_id(product_id, "প্রোডাক্ট")
        for table, label in (
            ("sale_items", "সেলস"),
            ("purchase_items", "পারচেজ"),
            ("sales_return_items", "সেলস রিটার্ন"),
            ("purchase_return_items", "পারচেজ রিটার্ন"),
        ):
            if int(self.db.scalar(f"SELECT COUNT(*) FROM {table} WHERE product_id=?", (product_id,))):
                raise BusinessRuleError(
                    f"এই প্রোডাক্টের {label} হিস্ট্রি রয়েছে — মুছে না ফেলে আর্কাইভ করুন"
                )
        with self.db.transaction():
            self.db.execute("DELETE FROM stock_movements WHERE product_id=?", (product_id,))
            self.db.execute("DELETE FROM stock_adjustments WHERE product_id=?", (product_id,))
            self.db.execute("DELETE FROM products WHERE id=?", (product_id,))
            self.audit.log("product", product_id, "delete", "প্রোডাক্ট মুছে ফেলা হয়েছে")

    # --------------------------------------------------------------- queries
    def get(self, product_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT p.*, u.name AS unit_name, u.symbol AS unit_symbol,
                      u.decimal_precision, c.name AS category_name,
                      (SELECT code FROM barcodes b WHERE b.product_id=p.id AND b.is_primary=1
                       LIMIT 1) AS barcode
                 FROM products p
                 JOIN units u ON u.id=p.unit_id
                 LEFT JOIN categories c ON c.id=p.category_id
                WHERE p.id=?""",
            (product_id,),
        )
        if row is None:
            raise NotFoundError("প্রোডাক্ট খুঁজে পাওয়া যায়নি")
        return dict(row)

    def search(
        self,
        *,
        query: str = "",
        category_id: int | None = None,
        status: str = "active",
        stock_filter: str = "all",
        min_price: int | None = None,
        max_price: int | None = None,
        sort: str = "name",
        descending: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []
        if query:
            term = normalize_search(query)
            where.append(
                """(p.name_normalized LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\'
                    OR EXISTS (SELECT 1 FROM barcodes b WHERE b.product_id=p.id
                               AND b.code LIKE ? ESCAPE '\\'))"""
            )
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        if status and status != "all":
            where.append("p.status=?")
            params.append(status)
        if category_id is not None:
            where.append("p.category_id=?")
            params.append(category_id)
        if stock_filter == "low":
            where.append("p.track_stock=1 AND p.stock_qty <= p.min_stock_qty AND p.stock_qty > 0")
        elif stock_filter == "out":
            where.append("p.track_stock=1 AND p.stock_qty <= 0")
        elif stock_filter == "in":
            where.append("p.track_stock=1 AND p.stock_qty > 0")
        if min_price is not None:
            where.append("p.selling_price >= ?")
            params.append(min_price)
        if max_price is not None:
            where.append("p.selling_price <= ?")
            params.append(max_price)

        sort_columns = {
            "name": "p.name_normalized",
            "sku": "p.sku",
            "price": "p.selling_price",
            "stock": "p.stock_qty",
            "value": "p.stock_value",
            "created": "p.id",
        }
        order_by = sort_columns.get(sort, "p.name_normalized")
        direction = "DESC" if descending else "ASC"
        clause = " AND ".join(where)
        total = int(
            self.db.scalar(f"SELECT COUNT(*) FROM products p WHERE {clause}", params)
        )
        rows = self.db.query(
            f"""SELECT p.*, u.name AS unit_name, u.symbol AS unit_symbol, u.decimal_precision,
                       c.name AS category_name,
                       (SELECT code FROM barcodes b WHERE b.product_id=p.id AND b.is_primary=1
                        LIMIT 1) AS barcode
                  FROM products p
                  JOIN units u ON u.id=p.unit_id
                  LEFT JOIN categories c ON c.id=p.category_id
                 WHERE {clause}
                 ORDER BY {order_by} {direction}, p.id
                 LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        return {"rows": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    def quick_search(self, term: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Fast POS lookup across name, SKU and barcode."""
        result = self.search(query=term, status="active", limit=limit)
        return result["rows"]

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM products"))


class BarcodeService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def lookup(self, code: str) -> dict[str, Any] | None:
        code = (code or "").strip()
        if not code:
            return None
        row = self.db.query_one(
            """SELECT p.*, u.name AS unit_name, u.symbol AS unit_symbol, u.decimal_precision
                 FROM barcodes b JOIN products p ON p.id=b.product_id
                 JOIN units u ON u.id=p.unit_id
                WHERE b.code=? AND p.status='active'""",
            (code,),
        )
        return dict(row) if row else None

    def add(self, product_id: int, code: str, *, primary: bool = False) -> int:
        require_id(product_id, "প্রোডাক্ট")
        code = validate_barcode(code)
        if self.db.query_one("SELECT id FROM barcodes WHERE code=?", (code,)):
            raise DuplicateError(f"'{code}' বারকোড অন্য প্রোডাক্টে ব্যবহৃত হয়েছে")
        with self.db.transaction():
            if primary:
                self.db.execute("UPDATE barcodes SET is_primary=0 WHERE product_id=?", (product_id,))
            bid = self.db.insert(
                "INSERT INTO barcodes (product_id, code, is_primary) VALUES (?,?,?)",
                (product_id, code, 1 if primary else 0),
            )
            self.audit.log("barcode", bid, "create", f"বারকোড যুক্ত: {code}")
        return bid

    def remove(self, barcode_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM barcodes WHERE id=?", (barcode_id,))
            self.audit.log("barcode", barcode_id, "delete", "বারকোড মুছে ফেলা হয়েছে")

    def for_product(self, product_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                "SELECT * FROM barcodes WHERE product_id=? ORDER BY is_primary DESC, id",
                (product_id,),
            )
        ]

    def generate(self, product_id: int) -> str:
        """Generate a unique in-store Code128-safe numeric barcode."""
        require_id(product_id, "প্রোডাক্ট")
        with self.db.transaction():
            for _ in range(1000):
                candidate = f"20{product_id:05d}{self._next_suffix():05d}"
                if not self.db.query_one("SELECT id FROM barcodes WHERE code=?", (candidate,)):
                    self.add(product_id, candidate, primary=True)
                    return candidate
        raise BusinessRuleError("নতুন বারকোড তৈরি করা যায়নি")

    def _next_suffix(self) -> int:
        return int(self.db.scalar("SELECT COALESCE(MAX(id),0)+1 FROM barcodes"))
