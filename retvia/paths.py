"""Resource resolution that works both from source and from a frozen bundle."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Root of the unpacked resources when running from a PyInstaller build."""
    override = os.environ.get("RETVIA_BUNDLE_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return PACKAGE_DIR.parent


def resource_path(*parts: str) -> Path:
    """Locate a bundled read-only resource (fonts, migrations, keys, docs).

    Tries the package-relative location first, then the bundle root, so the same
    call works from a source checkout, a one-folder build and a one-file build.
    """
    relative = Path(*parts)
    candidates = [
        PACKAGE_DIR / relative,
        bundle_dir() / "retvia" / relative,
        bundle_dir() / relative,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def docs_dir() -> Path:
    """User documentation shipped alongside the executable."""
    for candidate in (
        resource_path("assets", "docs"),
        bundle_dir() / "docs",
        PACKAGE_DIR.parent / "docs",
    ):
        if candidate.is_dir():
            return candidate
    return PACKAGE_DIR.parent / "docs"
