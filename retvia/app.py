"""Application bootstrap: fonts, theme, first run, login and the main window."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import __brand__, __product_name__, __version__
from .core.errors import LicenseError
from .services.container import ServiceContainer

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(data_dir: Path) -> logging.Logger:
    """Rotating local log file. Never logs customer rows or credentials."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("retvia")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "retvia.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    if not getattr(sys, "frozen", False):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(stream)
    return logger


def install_exception_hook(logger: logging.Logger) -> None:
    def hook(exc_type, exc_value, exc_tb):  # noqa: ANN001 - sys hook signature
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("অসংগৃহীত ত্রুটি:\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox()
                box.setIcon(QMessageBox.Critical)
                box.setWindowTitle("অপ্রত্যাশিত সমস্যা")
                box.setText(f"একটি অপ্রত্যাশিত সমস্যা হয়েছে। বিস্তারিত লগ ফাইলে সংরক্ষিত হয়েছে।\n\n{exc_value}")
                box.exec()
        except Exception:  # noqa: BLE001 - the hook must never raise
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    """Start the desktop application. Returns a process exit code."""
    arguments = list(sys.argv if argv is None else argv)
    smoke = "--smoke-test" in arguments
    screenshot_dir = None
    if "--screenshot-dir" in arguments:
        index = arguments.index("--screenshot-dir")
        if index + 1 < len(arguments):
            screenshot_dir = Path(arguments[index + 1])
    if "--no-login" in arguments:
        os.environ["RETVIA_SKIP_LOGIN"] = "1"

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app = QApplication(arguments)
    app.setApplicationName(__product_name__)
    app.setApplicationDisplayName(f"{__brand__} {__product_name__}")
    app.setOrganizationName(__brand__)
    app.setApplicationVersion(__version__)

    services = ServiceContainer()
    logger = configure_logging(services.data_dir)
    install_exception_hook(logger)
    logger.info("%s %s শুরু হচ্ছে (ডেটা: %s)", __product_name__, __version__, services.data_dir)

    from .ui.theme import load_fonts, stylesheet

    load_fonts()
    app.setStyleSheet(stylesheet())
    from .paths import resource_path

    icon_path = resource_path("assets", "icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    from .ui.login import FirstRunDialog, LoginDialog
    from .ui.main_window import MainWindow

    if not services.users.has_owner() and not smoke:
        setup = FirstRunDialog(services)
        if setup.exec() != QDialog.Accepted:
            services.close()
            return 0

    if smoke or os.environ.get("RETVIA_SKIP_LOGIN") == "1":
        owner = services.users.list(active_only=True)
        if owner:
            services.current_user = {
                "id": owner[0]["id"],
                "username": owner[0]["username"],
                "display_name": owner[0]["display_name"],
                "role": owner[0]["role"],
            }
            services.set_actor(owner[0]["display_name"])
        else:
            services.current_user = {
                "id": 0,
                "username": "smoke",
                "display_name": "Smoke Test",
                "role": "owner",
            }
            services.set_actor("Smoke Test")
    else:
        login = LoginDialog(services)
        if login.exec() != QDialog.Accepted:
            services.close()
            return 0

    try:
        services.activation.verify()
    except LicenseError as exc:
        logger.warning("লাইসেন্স যাচাই: %s", exc)
        if not smoke:
            box = QMessageBox()
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("লাইসেন্স সক্রিয়করণ প্রয়োজন")
            box.setText(f"{exc}\n\nআপনি সীমিত মোডে অ্যাপটি খুলতে পারেন এবং 'লাইসেন্স' পাতা থেকে সক্রিয় করতে পারবেন।")
            box.setStandardButtons(QMessageBox.Ok)
            box.button(QMessageBox.Ok).setText("ঠিক আছে")
            box.exec()

    window = MainWindow(services)
    window.apply_permissions()
    window.show()

    if smoke:
        return _smoke_test(app, services, window, screenshot_dir, logger)

    code = app.exec()
    services.close()
    logger.info("অ্যাপ্লিকেশন বন্ধ হয়েছে (কোড %s)", code)
    return code


def _smoke_test(
    app: Any, services: Any, window: Any, screenshot_dir: Path | None, logger: logging.Logger
) -> int:
    """Visit every page offscreen and capture screenshots (CI verification)."""
    from PySide6.QtCore import QTimer

    from .ui.main_window import NAV_GROUPS

    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
    keys = [key for _, items in NAV_GROUPS for key, _title, _permission in items]
    failures: list[str] = []
    index = {"value": 0}

    def step() -> None:
        i = index["value"]
        if i >= len(keys):
            logger.info("স্মোক টেস্ট সম্পন্ন — %d পাতা, %d ব্যর্থ", len(keys), len(failures))
            if screenshot_dir:
                (screenshot_dir / "smoke-result.txt").write_text(
                    f"pages={len(keys)}\nfailures={len(failures)}\n" + "\n".join(failures),
                    encoding="utf-8",
                )
            app.exit(1 if failures else 0)
            return
        key = keys[i]
        try:
            window.navigate(key)
            app.processEvents()
            if screenshot_dir:
                window.grab().save(str(screenshot_dir / f"{i:02d}-{key}.png"))
            logger.info("পাতা যাচাই সম্পন্ন: %s", key)
        except Exception as exc:  # noqa: BLE001 - report every page failure
            failures.append(f"{key}: {exc}")
            logger.error("পাতা ব্যর্থ %s: %s", key, exc, exc_info=True)
        index["value"] = i + 1
        QTimer.singleShot(120, step)

    QTimer.singleShot(400, step)
    return app.exec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
