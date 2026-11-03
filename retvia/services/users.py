"""Local user accounts, password hashing and role-based permissions.

Passwords are hashed with scrypt (stdlib ``hashlib``) using a per-user random
salt. Nothing is ever sent off the machine.
"""

from __future__ import annotations

import builtins
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.errors import BusinessRuleError, DuplicateError, NotFoundError, ValidationError
from ..core.validation import require_text, validate_choice
from .audit import AuditService

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
HASH_PARAMS = f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 10

ROLES = ("owner", "manager", "cashier")
ROLE_LABELS = {"owner": "মালিক", "manager": "ম্যানেজার", "cashier": "ক্যাশিয়ার"}

# Permissions are additive per role; owner has everything.
PERMISSIONS: dict[str, set[str]] = {
    "cashier": {
        "dashboard.view",
        "pos.sell",
        "product.view",
        "customer.view",
        "customer.create",
        "sale.view",
        "sale.return",
        "payment.collect",
        "cash.operate",
        "report.view",
    },
    "manager": {
        "product.create",
        "product.edit",
        "product.archive",
        "inventory.adjust",
        "purchase.create",
        "purchase.cancel",
        "purchase.return",
        "supplier.view",
        "supplier.create",
        "supplier.edit",
        "payment.pay",
        "expense.create",
        "expense.cancel",
        "sale.cancel",
        "catalog.manage",
        "backup.create",
        "settings.edit",
        "transaction.view",
    },
    "owner": {
        "product.delete",
        "customer.delete",
        "supplier.delete",
        "user.manage",
        "backup.restore",
        "audit.view",
        "license.manage",
        "report.export",
        "system.health",
    },
}
PERMISSIONS["manager"] |= PERMISSIONS["cashier"]
PERMISSIONS["owner"] |= PERMISSIONS["manager"]


def hash_password(password: str, *, salt: str | None = None) -> tuple[str, str]:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"পাসওয়ার্ড কমপক্ষে {MIN_PASSWORD_LENGTH} অক্ষরের হতে হবে")
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt_bytes,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_LENGTH,
        maxmem=64 * 1024 * 1024,
    )
    return derived.hex(), salt_bytes.hex()


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    try:
        salt_bytes = bytes.fromhex(salt)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt_bytes,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=KEY_LENGTH,
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived.hex(), password_hash)


class UserService:
    """Account lifecycle and authentication with lockout protection."""

    def __init__(self, db: Any, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------------ query
    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM users"))

    def has_owner(self) -> bool:
        return int(self.db.scalar("SELECT COUNT(*) FROM users WHERE role='owner' AND is_active=1")) > 0

    def list(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        clause = "WHERE is_active=1" if active_only else ""
        return [
            dict(r)
            for r in self.db.query(
                f"""SELECT id, username, display_name, role, is_active, must_change,
                           last_login_at, notes, created_at
                      FROM users {clause} ORDER BY role, username"""
            )
        ]

    def get(self, user_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT id, username, display_name, role, is_active, must_change,
                      last_login_at, notes, created_at FROM users WHERE id=?""",
            (user_id,),
        )
        if row is None:
            raise NotFoundError("ব্যবহারকারী খুঁজে পাওয়া যায়নি")
        return dict(row)

    def by_username(self, username: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM users WHERE username=?", (username.strip(),))
        return dict(row) if row else None

    # ----------------------------------------------------------------- mutate
    def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str = "cashier",
        notes: str = "",
        must_change: bool = False,
    ) -> int:
        username = require_text(username, "ইউজারনেম", max_length=40).strip().lower()
        if any(ch.isspace() for ch in username):
            raise ValidationError("ইউজারনেমে স্পেস রাখা যাবে না")
        display_name = require_text(display_name, "নাম", max_length=120)
        validate_choice(role, ROLES, "ভূমিকা")
        if self.by_username(username):
            raise DuplicateError("এই ইউজারনেম আগে থেকেই আছে")
        password_hash, salt = hash_password(password)
        with self.db.transaction():
            user_id = self.db.insert(
                """INSERT INTO users
                   (username, display_name, role, password_hash, password_salt, hash_params,
                    is_active, must_change, notes)
                   VALUES (?,?,?,?,?,?,1,?,?)""",
                (username, display_name, role, password_hash, salt, HASH_PARAMS, int(must_change), notes),
            )
            if self.audit:
                self.audit.log("user", user_id, "create", f"ব্যবহারকারী তৈরি: {username} ({role})")
        return user_id

    def set_password(self, user_id: int, password: str, *, must_change: bool = False) -> None:
        self.get(user_id)
        password_hash, salt = hash_password(password)
        with self.db.transaction():
            self.db.execute(
                """UPDATE users SET password_hash=?, password_salt=?, hash_params=?, must_change=?,
                          failed_attempts=0, locked_until='',
                          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (password_hash, salt, HASH_PARAMS, int(must_change), user_id),
            )
            if self.audit:
                self.audit.log("user", user_id, "password_change", "পাসওয়ার্ড পরিবর্তন")

    def set_role(self, user_id: int, role: str) -> None:
        validate_choice(role, ROLES, "ভূমিকা")
        user = self.get(user_id)
        if user["role"] == "owner" and role != "owner" and self.has_owner():
            remaining = int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM users WHERE role='owner' AND is_active=1 AND id<>?", (user_id,)
                )
            )
            if remaining == 0:
                raise BusinessRuleError("শেষ মালিক অ্যাকাউন্টের ভূমিকা পরিবর্তন করা যাবে না")
        with self.db.transaction():
            self.db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            if self.audit:
                self.audit.log("user", user_id, "role_change", f"ভূমিকা পরিবর্তন: {role}")

    def set_active(self, user_id: int, active: bool) -> None:
        user = self.get(user_id)
        if not active and user["role"] == "owner":
            remaining = int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM users WHERE role='owner' AND is_active=1 AND id<>?", (user_id,)
                )
            )
            if remaining == 0:
                raise BusinessRuleError("শেষ সক্রিয় মালিক অ্যাকাউন্ট নিষ্ক্রিয় করা যাবে না")
        with self.db.transaction():
            self.db.execute("UPDATE users SET is_active=? WHERE id=?", (int(active), user_id))
            if self.audit:
                self.audit.log("user", user_id, "status", "সক্রিয়" if active else "নিষ্ক্রিয়")

    def update_profile(self, user_id: int, *, display_name: str, notes: str = "") -> None:
        self.get(user_id)
        display_name = require_text(display_name, "নাম", max_length=120)
        self.db.execute("UPDATE users SET display_name=?, notes=? WHERE id=?", (display_name, notes, user_id))

    # ------------------------------------------------------------------- auth
    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        username = (username or "").strip().lower()
        user = self.by_username(username)
        now = datetime.now(UTC)
        if user is None:
            self._record_attempt(username, False, "unknown user")
            raise BusinessRuleError("ইউজারনেম বা পাসওয়ার্ড সঠিক নয়")
        if user["locked_until"]:
            try:
                locked = datetime.fromisoformat(user["locked_until"])
            except ValueError:
                locked = now
            if locked > now:
                remaining = max(1, int((locked - now).total_seconds() // 60) + 1)
                raise BusinessRuleError(f"অ্যাকাউন্ট সাময়িকভাবে বন্ধ — {remaining} মিনিট পরে চেষ্টা করুন")
        if not user["is_active"]:
            self._record_attempt(username, False, "inactive")
            raise BusinessRuleError("এই অ্যাকাউন্ট নিষ্ক্রিয় করা হয়েছে")
        if not verify_password(password, user["password_hash"], user["password_salt"]):
            attempts = int(user["failed_attempts"]) + 1
            lock = ""
            if attempts >= MAX_FAILED_ATTEMPTS:
                lock = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
                attempts = 0
            self.db.execute(
                "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (attempts, lock, user["id"])
            )
            self._record_attempt(username, False, "bad password")
            raise BusinessRuleError("ইউজারনেম বা পাসওয়ার্ড সঠিক নয়")
        stamp = now.isoformat(timespec="seconds")
        with self.db.transaction():
            self.db.execute(
                "UPDATE users SET failed_attempts=0, locked_until='', last_login_at=? WHERE id=?",
                (stamp, user["id"]),
            )
            self._record_attempt(username, True, "")
            if self.audit:
                self.audit.log("user", user["id"], "login", f"লগইন: {username}")
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "must_change": bool(user["must_change"]),
        }

    def _record_attempt(self, username: str, succeeded: bool, reason: str) -> None:
        self.db.execute(
            "INSERT INTO login_attempts (username, succeeded, reason) VALUES (?,?,?)",
            (username[:40], int(succeeded), reason),
        )

    def login_history(self, *, limit: int = 200) -> builtins.list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query("SELECT * FROM login_attempts ORDER BY id DESC LIMIT ?", (limit,))
        ]

    @staticmethod
    def can(role: str, permission: str) -> bool:
        return permission in PERMISSIONS.get(role, set())

    def ensure_owner(self, *, username: str, password: str, display_name: str) -> int | None:
        """First-run bootstrap: create the owner account only when none exists."""
        if self.has_owner():
            return None
        return self.create(username=username, password=password, display_name=display_name, role="owner")
