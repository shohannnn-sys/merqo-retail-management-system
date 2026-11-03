"""Cash register, shift sessions and drawer movements."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..core.errors import BusinessRuleError, NotFoundError, ValidationError
from ..core.validation import optional_text, require_id, require_non_negative_money, require_text
from ..data.db import Database
from .audit import AuditService
from .settings import SettingsService

MOVEMENT_LABELS = {
    "sale": "ক্যাশ সেলস",
    "sale_cancel_refund": "সেলস বাতিল রিফান্ড",
    "customer_payment": "কাস্টমার কালেকশন",
    "supplier_payment": "সাপ্লায়ার পেমেন্ট",
    "expense": "এক্সপেন্স",
    "sales_return_refund": "সেলস রিটার্ন রিফান্ড",
    "purchase_return_refund": "পারচেজ রিটার্ন রিফান্ড",
    "purchase": "ক্যাশ পারচেজ",
    "cash_in": "ক্যাশ ইন",
    "cash_out": "ক্যাশ আউট",
    "opening": "ওপেনিং ক্যাশ",
}


class CashService:
    def __init__(
        self, db: Database, settings: SettingsService | None = None, audit: AuditService | None = None
    ) -> None:
        self.db = db
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)

    # ------------------------------------------------------------- registers
    def registers(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM cash_registers ORDER BY id")]

    def create_register(self, name: str, *, location: str = "") -> int:
        name = require_text(name, "ক্যাশ রেজিস্টারের নাম", max_length=120)
        with self.db.transaction():
            rid = self.db.insert(
                "INSERT INTO cash_registers (name, location) VALUES (?,?)",
                (name, optional_text(location, max_length=200)),
            )
            self.audit.log("cash_register", rid, "create", f"রেজিস্টার তৈরি: {name}")
        return rid

    def _default_register_id(self) -> int:
        row = self.db.query_one("SELECT id FROM cash_registers WHERE is_active=1 ORDER BY id LIMIT 1")
        if row is None:
            return self.create_register("প্রধান ক্যাশ ড্রয়ার")
        return int(row["id"])

    # -------------------------------------------------------------- sessions
    def current_session(self, register_id: int | None = None) -> dict[str, Any] | None:
        if register_id is None:
            row = self.db.query_one("SELECT * FROM cash_sessions WHERE status='open' ORDER BY id DESC LIMIT 1")
        else:
            row = self.db.query_one(
                "SELECT * FROM cash_sessions WHERE status='open' AND register_id=? ORDER BY id DESC LIMIT 1",
                (register_id,),
            )
        return dict(row) if row else None

    def open_session(
        self, *, opening_cash: int, register_id: int | None = None, actor: str = "", notes: str = ""
    ) -> dict[str, Any]:
        require_non_negative_money(opening_cash, "ওপেনিং ক্যাশ")
        register_id = register_id or self._default_register_id()
        if self.current_session(register_id):
            raise BusinessRuleError("এই রেজিস্টারে একটি শিফট ইতিমধ্যে খোলা রয়েছে")
        with self.db.transaction():
            sid = self.db.insert(
                """INSERT INTO cash_sessions (register_id, opened_at, opening_cash, status, opened_by, notes)
                   VALUES (?,?,?, 'open', ?, ?)""",
                (
                    register_id, datetime.now().isoformat(timespec="seconds"), opening_cash,
                    actor, optional_text(notes, max_length=300),
                ),
            )
            if opening_cash:
                self.record_movement(
                    session_id=sid, movement_type="opening", amount=opening_cash,
                    reference_type="cash_session", reference_id=sid, notes="ওপেনিং ক্যাশ",
                )
            self.audit.log("cash_session", sid, "open", f"শিফট শুরু — ওপেনিং ক্যাশ {opening_cash}")
        return self.session(sid)

    def require_open_session(self) -> int:
        """Return the open session id, enforcing the register policy."""
        session = self.current_session()
        if session is not None:
            return int(session["id"])
        if self.settings.get_bool("require_open_register_for_cash", True):
            raise BusinessRuleError(
                "ক্যাশ লেনদেনের জন্য আগে ক্যাশ ড্রয়ার শিফট খুলুন (ক্যাশ রেজিস্টার মডিউল)"
            )
        # Policy allows implicit sessions: open one with zero opening cash.
        created = self.open_session(opening_cash=0, actor="system", notes="স্বয়ংক্রিয় শিফট")
        return int(created["id"])

    def record_movement(
        self,
        *,
        session_id: int,
        movement_type: str,
        amount: int,
        payment_method_id: int | None = None,
        reference_type: str = "",
        reference_id: int | None = None,
        notes: str = "",
    ) -> int:
        """Append a signed drawer movement. Must run inside the caller's transaction."""
        if amount == 0:
            raise ValidationError("ক্যাশ মুভমেন্টের পরিমাণ শূন্য হতে পারে না")
        session = self.db.query_one("SELECT status FROM cash_sessions WHERE id=?", (session_id,))
        if session is None:
            raise NotFoundError("ক্যাশ শিফট খুঁজে পাওয়া যায়নি")
        if session["status"] != "open":
            raise BusinessRuleError("বন্ধ শিফটে ক্যাশ লেনদেন যোগ করা যাবে না")
        return self.db.insert(
            """INSERT INTO cash_movements
               (session_id, movement_type, amount, payment_method_id, reference_type,
                reference_id, movement_at, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                session_id, movement_type, amount, payment_method_id, reference_type,
                reference_id, datetime.now().isoformat(timespec="seconds"),
                optional_text(notes, max_length=300),
            ),
        )

    def manual_movement(
        self, *, movement_type: str, amount: int, reason: str, actor: str = ""
    ) -> dict[str, Any]:
        if movement_type not in ("cash_in", "cash_out"):
            raise ValidationError("ক্যাশ ইন বা ক্যাশ আউট নির্বাচন করুন")
        require_non_negative_money(amount, "পরিমাণ")
        if amount == 0:
            raise ValidationError("পরিমাণ ধনাত্মক হতে হবে")
        reason = require_text(reason, "কারণ", max_length=300)
        session_id = self.require_open_session()
        signed = amount if movement_type == "cash_in" else -amount
        with self.db.transaction():
            mid = self.record_movement(
                session_id=session_id, movement_type=movement_type, amount=signed,
                reference_type="manual", notes=reason,
            )
            self.audit.log("cash_movement", mid, movement_type, f"{reason} — {amount}")
        return {"id": mid, "session_id": session_id, "amount": signed}

    def expected_cash(self, session_id: int) -> int:
        """Opening cash + all drawer movements (the opening row is included once)."""
        row = self.db.query_one("SELECT opening_cash FROM cash_sessions WHERE id=?", (session_id,))
        if row is None:
            raise NotFoundError("ক্যাশ শিফট খুঁজে পাওয়া যায়নি")
        movements = int(
            self.db.scalar(
                "SELECT COALESCE(SUM(amount),0) FROM cash_movements WHERE session_id=? AND movement_type<>'opening'",
                (session_id,),
            )
        )
        return int(row["opening_cash"]) + movements

    def close_session(
        self, *, session_id: int, actual_cash: int, actor: str = "", notes: str = ""
    ) -> dict[str, Any]:
        require_non_negative_money(actual_cash, "প্রকৃত ক্লোজিং ক্যাশ")
        session = self.db.query_one("SELECT * FROM cash_sessions WHERE id=?", (session_id,))
        if session is None:
            raise NotFoundError("ক্যাশ শিফট খুঁজে পাওয়া যায়নি")
        if session["status"] != "open":
            raise BusinessRuleError("এই শিফট আগেই বন্ধ করা হয়েছে")
        expected = self.expected_cash(session_id)
        difference = actual_cash - expected
        with self.db.transaction():
            self.db.execute(
                """UPDATE cash_sessions
                      SET status='closed', closed_at=?, expected_cash=?, actual_cash=?,
                          difference=?, closed_by=?, notes=notes || ?
                    WHERE id=?""",
                (
                    datetime.now().isoformat(timespec="seconds"), expected, actual_cash,
                    difference, actor, f"\n[ক্লোজিং: {optional_text(notes, max_length=300)}]",
                    session_id,
                ),
            )
            self.audit.log(
                "cash_session", session_id, "close",
                f"শিফট বন্ধ — প্রত্যাশিত {expected}, প্রকৃত {actual_cash}, পার্থক্য {difference}",
                after={"expected": expected, "actual": actual_cash, "difference": difference},
            )
        return self.session(session_id)

    # --------------------------------------------------------------- queries
    def session(self, session_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT cs.*, cr.name AS register_name FROM cash_sessions cs
                 JOIN cash_registers cr ON cr.id=cs.register_id WHERE cs.id=?""",
            (session_id,),
        )
        if row is None:
            raise NotFoundError("ক্যাশ শিফট খুঁজে পাওয়া যায়নি")
        data = dict(row)
        data["expected_cash_now"] = self.expected_cash(session_id)
        data["movements"] = self.movements(session_id)
        return data

    def movements(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT cm.*, pm.name AS method_name FROM cash_movements cm
                 LEFT JOIN payment_methods pm ON pm.id=cm.payment_method_id
                WHERE cm.session_id=? ORDER BY cm.id""",
            (session_id,),
        )
        return [dict(r) for r in rows]

    def summary_by_type(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT movement_type, COALESCE(SUM(amount),0) AS total, COUNT(*) AS count
                 FROM cash_movements WHERE session_id=? GROUP BY movement_type ORDER BY movement_type""",
            (session_id,),
        )
        return [
            {**dict(r), "label": MOVEMENT_LABELS.get(r["movement_type"], r["movement_type"])}
            for r in rows
        ]

    def sessions(
        self, *, start: str | None = None, end: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("date(cs.opened_at) >= ?")
            params.append(start)
        if end:
            where.append("date(cs.opened_at) <= ?")
            params.append(end)
        rows = self.db.query(
            f"""SELECT cs.*, cr.name AS register_name FROM cash_sessions cs
                  JOIN cash_registers cr ON cr.id=cs.register_id
                 WHERE {' AND '.join(where)} ORDER BY cs.id DESC LIMIT ?""",
            [*params, limit],
        )
        return [dict(r) for r in rows]

    def daily_summary(self, day: str | date) -> dict[str, Any]:
        day = str(day)
        rows = self.db.query(
            """SELECT movement_type, COALESCE(SUM(amount),0) AS total
                 FROM cash_movements WHERE date(movement_at)=? GROUP BY movement_type""",
            (day,),
        )
        breakdown = {
            r["movement_type"]: int(r["total"]) for r in rows
        }
        return {
            "date": day,
            "breakdown": [
                {"type": k, "label": MOVEMENT_LABELS.get(k, k), "total": v}
                for k, v in sorted(breakdown.items())
            ],
            "net_change": sum(v for k, v in breakdown.items() if k != "opening"),
            "opening_total": breakdown.get("opening", 0),
        }
