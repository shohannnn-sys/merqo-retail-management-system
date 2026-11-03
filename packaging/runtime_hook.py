"""PyInstaller runtime hook: make bundled resources resolvable when frozen.

PyInstaller unpacks data files next to the executable (one-folder) or into
``sys._MEIPASS`` (one-file). The application resolves assets relative to its own
package directory, so we point it at the unpacked location before any import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    os.environ.setdefault("RETVIA_BUNDLE_DIR", str(base))
    # Qt must find its own plugins inside the bundle.
    plugins = base / "PySide6" / "plugins"
    if plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
    # Never let Qt scale Bengali text differently between machines.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
