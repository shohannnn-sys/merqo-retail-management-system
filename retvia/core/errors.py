"""Typed domain errors for Retvia.

Every error carries a Bangla, user-facing message. Internal detail is kept
separate so logs can be sanitized before they reach the UI or a log file.
"""

from __future__ import annotations


class RetviaError(Exception):
    """Base class for all expected, user-facing domain errors."""

    code = "error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ValidationError(RetviaError):
    """Input failed validation."""

    code = "validation"


class NotFoundError(RetviaError):
    """A referenced record does not exist."""

    code = "not_found"


class DuplicateError(RetviaError):
    """A uniqueness constraint would be violated."""

    code = "duplicate"


class InsufficientStockError(RetviaError):
    """Stock policy forbids the requested movement."""

    code = "insufficient_stock"


class BusinessRuleError(RetviaError):
    """A business rule prevents the operation."""

    code = "business_rule"


class LicenseError(RetviaError):
    """License is missing, invalid, tampered with, or for another business."""

    code = "license"


class BackupError(RetviaError):
    """Backup or restore failed; data has been left intact."""

    code = "backup"


class DatabaseError(RetviaError):
    """Database-level failure surfaced safely to the user."""

    code = "database"
