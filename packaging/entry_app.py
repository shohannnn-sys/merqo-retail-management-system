"""Frozen entry point for the Retvia desktop application."""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

# When frozen, make the bundled package importable regardless of the launcher's
# working directory (the installer may start the app from anywhere).
if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).parent))

from retvia.app import run  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run())
