"""Main application shell: sidebar navigation, top bar and page stack."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __brand__, __product_name__, __version__
from ..core.errors import LicenseError, RetviaError
from .theme import SPACE
from .views.catalog import CatalogView
from .views.dashboard import DashboardView
from .views.documents import PurchasesView, ReturnsView, SalesView
from .views.finance_views import CashView, ExpensesView
from .views.inventory import InventoryView
from .views.labels import LabelsView
from .views.parties import PartiesView
from .views.pos import PosView
from .views.products import ProductsView
from .views.reports import ReportsView, TransactionsView
from .views.system import AboutView, ActivationView, BackupView, SettingsView
from .widgets import confirm, guarded, show_error, show_info

NAV_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "প্রধান",
        [
            ("dashboard", "ড্যাশবোর্ড", "dashboard.view"),
            ("pos", "পিওএস / সেলস", "pos.sell"),
        ],
    ),
    (
        "ইনভেন্টরি",
        [
            ("products", "প্রোডাক্ট", "product.view"),
            ("inventory", "ইনভেন্টরি", "product.view"),
            ("catalog", "ক্যাটাগরি ও ইউনিট", "product.view"),
            ("labels", "বারকোড ও লেবেল", "product.view"),
        ],
    ),
    (
        "লেনদেন",
        [
            ("sales", "সেলস ও ইনভয়েস", "sale.view"),
            ("purchases", "পারচেজ", "purchase.create"),
            ("returns", "রিটার্ন", "sale.view"),
            ("transactions", "লেনদেন হিস্ট্রি", "sale.view"),
        ],
    ),
    (
        "হিসাব",
        [
            ("parties", "কাস্টমার ও সাপ্লায়ার", "customer.view"),
            ("expenses", "এক্সপেন্স", "expense.create"),
            ("cash", "ক্যাশ রেজিস্টার", "cash.operate"),
            ("reports", "রিপোর্ট সেন্টার", "report.view"),
        ],
    ),
    (
        "সিস্টেম",
        [
            ("settings", "সেটিংস", "settings.edit"),
            ("backup", "ব্যাকআপ ও রিস্টোর", "backup.create"),
            ("activation", "লাইসেন্স", "dashboard.view"),
            ("about", "পরিচিতি", "dashboard.view"),
        ],
    ),
]


class MainWindow(QMainWindow):
    def __init__(self, services: Any) -> None:
        super().__init__()
        self.services = services
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle(f"{__brand__} {__product_name__} — রিটেইল ম্যানেজমেন্ট সিস্টেম")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 700)
        self._build()
        self._build_menu()
        self._shortcuts()
        self._start_timers()
        self.navigate("dashboard")

    # ------------------------------------------------------------------ shell
    def _build(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(SPACE["md"], SPACE["lg"], SPACE["md"], SPACE["md"])
        side.setSpacing(2)
        brand = QLabel(__brand__)
        brand.setObjectName("SidebarBrand")
        side.addWidget(brand)
        product = QLabel(f"{__product_name__} {__version__}")
        product.setObjectName("SidebarProduct")
        side.addWidget(product)
        side.addSpacing(SPACE["md"])

        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)
        for group, items in NAV_GROUPS:
            label = QLabel(group)
            label.setObjectName("NavGroup")
            nav_layout.addWidget(label)
            for key, title, permission in items:
                button = QPushButton(title)
                button.setObjectName("NavButton")
                button.setCheckable(True)
                button.setProperty("permission", permission)
                button.clicked.connect(lambda _=False, k=key: self.navigate(k))
                nav_layout.addWidget(button)
                self.nav_buttons[key] = button
        nav_layout.addStretch(1)
        nav_scroll.setWidget(nav_container)
        side.addWidget(nav_scroll, 1)

        self.user_label = QLabel("")
        self.user_label.setObjectName("SidebarUser")
        self.user_label.setWordWrap(True)
        side.addWidget(self.user_label)
        logout = QPushButton("লগআউট")
        logout.setObjectName("Ghost")
        logout.clicked.connect(self._logout)
        side.addWidget(logout)
        root.addWidget(sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("Topbar")
        topbar.setFixedHeight(56)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(SPACE["xl"], 0, SPACE["xl"], 0)
        self.business_label = QLabel("")
        self.business_label.setObjectName("TopbarBusiness")
        top_layout.addWidget(self.business_label)
        top_layout.addStretch(1)
        self.license_chip = QLabel("")
        self.license_chip.setObjectName("StatusChip")
        top_layout.addWidget(self.license_chip)
        self.shift_chip = QLabel("")
        self.shift_chip.setObjectName("StatusChip")
        top_layout.addWidget(self.shift_chip)
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("Muted")
        top_layout.addWidget(self.clock_label)
        right_layout.addWidget(topbar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        self.status = self.statusBar()
        self.status.showMessage("প্রস্তুত")
        self._refresh_topbar()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("ফাইল")
        for text, shortcut, handler in (
            ("নতুন সেলস", "F1", lambda: self.navigate("pos")),
            ("ব্যাকআপ নিন", "Ctrl+B", self._quick_backup),
            ("রিপোর্ট সেন্টার", "Ctrl+R", lambda: self.navigate("reports")),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            file_menu.addAction(action)
        file_menu.addSeparator()
        exit_action = QAction("প্রস্থান", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = bar.addMenu("দেখুন")
        for key, title in (
            ("dashboard", "ড্যাশবোর্ড"),
            ("products", "প্রোডাক্ট"),
            ("inventory", "ইনভেন্টরি"),
            ("sales", "সেলস"),
            ("reports", "রিপোর্ট"),
        ):
            action = QAction(title, self)
            action.triggered.connect(lambda _=False, k=key: self.navigate(k))
            view_menu.addAction(action)
        refresh = QAction("রিফ্রেশ", self)
        refresh.setShortcut(QKeySequence("F5"))
        refresh.triggered.connect(self.refresh_current)
        view_menu.addAction(refresh)

        help_menu = bar.addMenu("সহায়তা")
        about = QAction("পরিচিতি", self)
        about.triggered.connect(lambda: self.navigate("about"))
        help_menu.addAction(about)
        guide = QAction("ব্যবহার নির্দেশিকা", self)
        guide.triggered.connect(self._open_guide)
        help_menu.addAction(guide)

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.navigate("pos"))
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_current)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._quick_backup)

    def _start_timers(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(30_000)
        self._tick()
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._auto_backup)
        self.backup_timer.start(5 * 60_000)

    # -------------------------------------------------------------- navigation
    def _create_page(self, key: str) -> QWidget:
        builders: dict[str, Callable[[], QWidget]] = {
            "dashboard": lambda: DashboardView(self.services),
            "pos": lambda: PosView(self.services),
            "products": lambda: ProductsView(self.services),
            "inventory": lambda: InventoryView(self.services),
            "catalog": lambda: CatalogView(self.services),
            "labels": lambda: LabelsView(self.services),
            "sales": lambda: SalesView(self.services),
            "purchases": lambda: PurchasesView(self.services),
            "returns": lambda: ReturnsView(self.services),
            "transactions": lambda: TransactionsView(self.services),
            "parties": lambda: PartiesView(self.services),
            "expenses": lambda: ExpensesView(self.services),
            "cash": lambda: CashView(self.services),
            "reports": lambda: ReportsView(self.services),
            "settings": lambda: SettingsView(self.services),
            "backup": lambda: BackupView(self.services),
            "activation": lambda: ActivationView(self.services),
            "about": lambda: AboutView(self.services),
        }
        page = builders[key]()
        if key == "pos":
            page.sale_completed.connect(self._on_sale_completed)
        return page

    def navigate(self, key: str) -> None:
        button = self.nav_buttons.get(key)
        permission = button.property("permission") if button else ""
        if permission and not self.services.can(permission):
            show_error(self, "এই অংশে প্রবেশের অনুমতি আপনার নেই")
            return
        if key not in self.pages:
            try:
                self.pages[key] = self._create_page(key)
            except (RetviaError, RuntimeError) as exc:
                show_error(self, exc)
                return
            self.stack.addWidget(self.pages[key])
        self.stack.setCurrentWidget(self.pages[key])
        for name, nav in self.nav_buttons.items():
            nav.setChecked(name == key)
        self.refresh_current()
        self.status.showMessage(f"{button.text() if button else key} — প্রস্তুত")

    def refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, "refresh"):
            try:
                page.refresh()
            except RetviaError as exc:
                show_error(self, exc)
        self._refresh_topbar()

    def apply_permissions(self) -> None:
        for button in self.nav_buttons.values():
            permission = button.property("permission")
            button.setVisible(not permission or self.services.can(permission))

    # ----------------------------------------------------------------- topbar
    def _refresh_topbar(self) -> None:
        profile = self.services.profile.get()
        self.business_label.setText(profile.name or "ব্যবসার নাম সেট করা হয়নি")
        try:
            self.services.activation.verify()
            self.license_chip.setText("লাইসেন্স সক্রিয় ✓")
            self.license_chip.setObjectName("StatusChip")
        except LicenseError:
            self.license_chip.setText("লাইসেন্স সক্রিয় নয়")
            self.license_chip.setObjectName("StatusChipWarn")
        self.license_chip.style().unpolish(self.license_chip)
        self.license_chip.style().polish(self.license_chip)
        session = self.services.cash.current_session()
        self.shift_chip.setText("শিফট খোলা" if session else "শিফট বন্ধ")
        self.shift_chip.setObjectName("StatusChip" if session else "StatusChipWarn")
        self.shift_chip.style().unpolish(self.shift_chip)
        self.shift_chip.style().polish(self.shift_chip)
        user = self.services.current_user
        if user:
            from ..services.users import ROLE_LABELS

            role = ROLE_LABELS.get(user["role"], user["role"])
            self.user_label.setText(f"{user['display_name']}\n{role}")

    def _tick(self) -> None:
        from datetime import datetime

        self.clock_label.setText(datetime.now().strftime("%d/%m/%Y  %I:%M %p"))

    # ------------------------------------------------------------------ events
    def _on_sale_completed(self, _result: dict[str, Any]) -> None:
        for key in ("dashboard", "sales", "inventory", "products"):
            page = self.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                with contextlib.suppress(RetviaError):
                    page.refresh()
        self._refresh_topbar()

    def _quick_backup(self) -> None:
        result = guarded(self, lambda: self.services.backup.create())
        if result:
            show_info(self, f"ব্যাকআপ সম্পন্ন\n{result['file_name']}")
        backup_page = self.pages.get("backup")
        if backup_page is not None:
            backup_page.refresh()

    def _auto_backup(self) -> None:
        # Never interrupt the operator with a background failure.
        with contextlib.suppress(RetviaError):
            self.services.maybe_auto_backup()

    def _open_guide(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ..paths import docs_dir, resource_path

        candidates = [
            resource_path("assets", "docs", "USER_GUIDE_BN.html"),
            docs_dir() / "USER_GUIDE_BN.html",
            docs_dir() / "USER_GUIDE_BN.md",
        ]
        for candidate in candidates:
            if candidate.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                return
        show_info(self, "নির্দেশিকা ফাইলটি ইনস্টলেশন ফোল্ডারের docs অংশে পাওয়া যাবে।")

    def _logout(self) -> None:
        if confirm(self, "লগআউট করবেন?"):
            self.services.logout()
            self.close()
            self.logout_requested = True

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if self.services.settings.get_bool("backup_on_exit", True):
            try:
                self.services.backup.create(backup_type="automatic", notes="অ্যাপ বন্ধের সময়")
                self.services.backup.prune()
            except RetviaError as exc:
                if not confirm(self, f"বন্ধের সময় ব্যাকআপ নেওয়া যায়নি:\n{exc}\n\nতবুও বন্ধ করবেন?"):
                    event.ignore()
                    return
        event.accept()
