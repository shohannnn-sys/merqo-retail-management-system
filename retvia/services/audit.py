"""Append-only audit trail. Never logs secrets or full customer PII dumps."""

from __future__ import annotations

import json
from typing import Any

from ..data.db import Database

_SENSITIVE_KEYS = {
    "password",
    "private_key",
    "signing_key",
    "secret",
    "token",
    "signature",
    "payload_json",
    "license_key",
}


def _sanitize(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            k: ("[redacted]" if k.lower() in _SENSITIVE_KEYS else _sanitize(v)) for k, v in payload.items()
        }
    if isinstance(payload, list | tuple):
        return [_sanitize(v) for v in payload]
    return payload


class AuditService:
    def __init__(self, db: Database, actor: str = "") -> None:
        self.db = db
        self.actor = actor

    def log(
        self,
        entity_type: str,
        entity_id: int | None,
        action: str,
        summary: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> int:
        return self.db.insert(
            """INSERT INTO audit_logs
               (entity_type, entity_id, action, actor, summary, before_json, after_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_type,
                entity_id,
                action,
                self.actor,
                summary,
                json.dumps(_sanitize(before), ensure_ascii=False) if before else "",
                json.dumps(_sanitize(after), ensure_ascii=False) if after else "",
            ),
        )

    def recent(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return [dict(r) for r in rows]

    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        actor: str = "",
        action: str = "",
        entity_type: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filter the audit trail by date, actor, action or entity."""
        where = ["1=1"]
        params: list[Any] = []
        if start:
            where.append("substr(created_at,1,10) >= ?")
            params.append(start)
        if end:
            where.append("substr(created_at,1,10) <= ?")
            params.append(end)
        if actor:
            where.append("actor = ?")
            params.append(actor)
        if action:
            where.append("action = ?")
            params.append(action)
        if entity_type:
            where.append("entity_type = ?")
            params.append(entity_type)
        clause = " AND ".join(where)
        rows = self.db.query(
            f"SELECT * FROM audit_logs WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return [dict(r) for r in rows]

    def for_entity(self, entity_type: str, entity_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM audit_logs WHERE entity_type=? AND entity_id=? ORDER BY id DESC",
            (entity_type, entity_id),
        )
        return [dict(r) for r in rows]
