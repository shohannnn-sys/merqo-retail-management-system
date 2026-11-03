"""Frozen entry point for the owner-only License Generator."""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    base = Path(sys.executable).parent
    sys.path.insert(0, str(base))
    sys.path.insert(0, str(base / "_internal"))

from license_generator.app import run  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run())
