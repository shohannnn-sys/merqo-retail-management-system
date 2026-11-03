"""First-run setup and local sign-in."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __brand__, __product_name__, __version__
from ..core.errors import RetviaError
from ..services.settings import BusinessProfile
from .theme import SPACE
from .widgets import FieldSpec, FormDialog, show_error, show_info


class FirstRunDialog(QDialog):
    """Creates the owner account and captures the business profile once."""

    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.setWindowTitle(f"{__product_name__} — প্রথমবার সেটআপ")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])
        title = QLabel(f"{__brand__} {__product_name__}-এ স্বাগতম")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel(
            "শুরু করার আগে মালিক অ্যাকাউন্ট এবং আপনার ব্যবসার তথ্য দিন। "
            "এই তথ্য শুধু আপনার কম্পিউটারে সংরক্ষিত হবে — কোথাও পাঠানো হবে না।\n\n"
            "ব্যবসার নাম ও ঠিকানা ইনভয়েস এবং রিসিটে ব্যবহৃত হবে।"
        )
        intro.setWordWrap(True)
        intro.setObjectName("PageSubtitle")
        layout.addWidget(intro)

        self.fields: dict[str, QLineEdit] = {}
        for key, label, secret in (
            ("business_name", "ব্যবসার নাম *", False),
            ("address", "ঠিকানা", False),
            ("phone", "মোবাইল নম্বর", False),
            ("display_name", "মালিকের নাম *", False),
            ("username", "ইউজারনেম *", False),
            ("password", "পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর) *", True),
            ("confirm", "পাসওয়ার্ড নিশ্চিত করুন *", True),
        ):
            row = QVBoxLayout()
            row.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            edit = QLineEdit()
            if secret:
                edit.setEchoMode(QLineEdit.Password)
            if key == "username":
                edit.setText("admin")
            row.addWidget(caption)
            row.addWidget(edit)
            layout.addLayout(row)
            self.fields[key] = edit

        self.error = QLabel("")
        self.error.setObjectName("FieldError")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        skip = QPushButton("পরে করব")
        skip.clicked.connect(self.reject)
        save = QPushButton("সেটআপ সম্পন্ন করুন")
        save.setObjectName("Primary")
        save.clicked.connect(self._submit)
        buttons.addWidget(skip)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _submit(self) -> None:
        values = {key: edit.text().strip() for key, edit in self.fields.items()}
        for key, label in (
            ("business_name", "ব্যবসার নাম"),
            ("display_name", "মালিকের নাম"),
            ("username", "ইউজারনেম"),
            ("password", "পাসওয়ার্ড"),
        ):
            if not values[key]:
                self._fail(f"{label} আবশ্যক")
                return
        if values["password"] != values["confirm"]:
            self._fail("দুটি পাসওয়ার্ড মিলছে না")
            return
        try:
            self.services.users.ensure_owner(
                username=values["username"],
                password=values["password"],
                display_name=values["display_name"],
            )
            self.services.profile.update(
                BusinessProfile(
                    name=values["business_name"],
                    address=values["address"],
                    phone=values["phone"],
                )
            )
        except RetviaError as exc:
            self._fail(exc.message)
            return
        self.result_values = values
        self.accept()

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)


class LoginDialog(QDialog):
    """Local authentication — no network, no cloud account."""

    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.user: dict[str, Any] | None = None
        self.setWindowTitle(f"{__product_name__} — লগইন")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])
        brand = QLabel(__brand__)
        brand.setObjectName("SidebarBrand")
        brand.setAlignment(Qt.AlignCenter)
        layout.addWidget(brand)
        product = QLabel(f"{__product_name__} {__version__}")
        product.setAlignment(Qt.AlignCenter)
        product.setObjectName("PageSubtitle")
        layout.addWidget(product)

        self.username = QLineEdit()
        self.username.setPlaceholderText("ইউজারনেম")
        self.password = QLineEdit()
        self.password.setPlaceholderText("পাসওয়ার্ড")
        self.password.setEchoMode(QLineEdit.Password)
        for widget, label in ((self.username, "ইউজারনেম"), (self.password, "পাসওয়ার্ড")):
            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            layout.addWidget(caption)
            layout.addWidget(widget)

        self.error = QLabel("")
        self.error.setObjectName("FieldError")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        buttons = QHBoxLayout()
        quit_button = QPushButton("প্রস্থান")
        quit_button.clicked.connect(self.reject)
        login = QPushButton("লগইন করুন")
        login.setObjectName("Primary")
        login.clicked.connect(self._submit)
        buttons.addWidget(quit_button)
        buttons.addWidget(login, 1)
        layout.addLayout(buttons)
        hint = QLabel("পাসওয়ার্ড ভুলে গেলে অন্য মালিক অ্যাকাউন্ট থেকে রিসেট করুন।")
        hint.setObjectName("HelpText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        QShortcut(QKeySequence("Return"), self, activated=self._submit)
        self.username.setFocus()

    def _submit(self) -> None:
        try:
            user = self.services.login(self.username.text(), self.password.text())
            self.user = user
        except RetviaError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            self.password.selectAll()
            self.password.setFocus()
            return
        if user.get("must_change"):
            values = FormDialog.ask(
                "পাসওয়ার্ড পরিবর্তন আবশ্যক",
                [
                    FieldSpec("password", "নতুন পাসওয়ার্ড", "text", required=True, help="কমপক্ষে ৮ অক্ষর"),
                ],
                self,
            )
            if values is None:
                self.user = None
                return
            try:
                self.services.users.set_password(user["id"], values["password"])
            except RetviaError as exc:
                show_error(self, exc)
                self.user = None
                return
            show_info(self, "পাসওয়ার্ড পরিবর্তিত হয়েছে")
        self.accept()
