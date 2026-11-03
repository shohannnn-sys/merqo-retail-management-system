"""Settings, backup, activation and about screens."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import __brand__, __contact__, __founder__, __product_name__, __version__
from ...core.errors import LicenseError
from ..theme import SPACE
from ..widgets import (
    Card,
    DataTable,
    FieldSpec,
    FormDialog,
    KpiCard,
    PageHeader,
    TableColumn,
    confirm,
    guarded,
    show_error,
    show_info,
)


class SettingsView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.addWidget(PageHeader("সেটিংস", "ব্যবসার তথ্য, পিওএস, প্রিন্টার, ব্যবহারকারী ও অডিট লগ"))
        self.tabs = QTabWidget()

        # --- business profile
        profile_page = QWidget()
        profile_layout = QVBoxLayout(profile_page)
        profile_card = Card("ব্যবসার তথ্য (ইনভয়েস ও রিসিটে ব্যবহৃত হবে)")
        self.profile_labels: dict[str, QLabel] = {}
        for key, label in (
            ("name", "ব্যবসার নাম"),
            ("address", "ঠিকানা"),
            ("phone", "মোবাইল"),
            ("email", "ইমেইল"),
            ("tax_number", "BIN / টিন নম্বর"),
            ("receipt_footer", "রিসিট ফুটার"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            value = QLabel("—")
            value.setWordWrap(True)
            row.addWidget(value, 1)
            profile_card.add_layout(row)
            self.profile_labels[key] = value
        edit = PageHeader("", "")
        edit.add_action("ব্যবসার তথ্য সম্পাদনা", self._edit_profile, kind="Primary")
        profile_card.add(edit)
        profile_layout.addWidget(profile_card)
        profile_layout.addStretch(1)
        self.tabs.addTab(profile_page, "ব্যবসার তথ্য")

        # --- general settings
        general_page = QWidget()
        general_layout = QVBoxLayout(general_page)
        self.settings_table = DataTable(
            [
                TableColumn("key", "সেটিং", width=260),
                TableColumn("value", "মান", width=300),
            ]
        )
        general_card = Card("অ্যাপ্লিকেশন সেটিংস")
        general_card.add(self.settings_table)
        actions = PageHeader("", "")
        actions.add_action("নির্বাচিত সেটিং পরিবর্তন", self._edit_setting, kind="Primary")
        actions.add_action("পিওএস ও ডিস্কাউন্ট সেটিংস", self._edit_pos)
        actions.add_action("প্রিন্টার সেটিংস", self._edit_printer)
        general_card.add(actions)
        general_layout.addWidget(general_card)
        general_layout.addStretch(1)
        self.tabs.addTab(general_page, "সাধারণ")

        # --- users
        users_page = QWidget()
        users_layout = QVBoxLayout(users_page)
        self.users_table = DataTable(
            [
                TableColumn("id", "আইডি", "int", 60),
                TableColumn("username", "ইউজারনেম", width=180),
                TableColumn("display_name", "নাম", width=200),
                TableColumn("role", "ভূমিকা", width=120),
                TableColumn("is_active", "সক্রিয়", "int", 90),
                TableColumn("last_login_at", "সর্বশেষ লগইন", width=170),
            ]
        )
        users_card = Card("ব্যবহারকারী ও ভূমিকা")
        users_card.add(self.users_table)
        user_actions = PageHeader("", "")
        user_actions.add_action("+ নতুন ব্যবহারকারী", self._create_user, kind="Primary")
        user_actions.add_action("পাসওয়ার্ড পরিবর্তন", self._change_password)
        user_actions.add_action("সক্রিয় / নিষ্ক্রিয়", self._toggle_user)
        users_card.add(user_actions)
        users_layout.addWidget(users_card)
        users_layout.addStretch(1)
        self.tabs.addTab(users_page, "ব্যবহারকারী")

        # --- audit
        audit_page = QWidget()
        audit_layout = QVBoxLayout(audit_page)
        audit_controls = QHBoxLayout()
        audit_controls.addWidget(QLabel("তারিখ:"))
        self.audit_start = QDateEdit(QDate.currentDate().addDays(-7))
        self.audit_end = QDateEdit(QDate.currentDate())
        for widget in (self.audit_start, self.audit_end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.dateChanged.connect(lambda: self._load_audit())
        audit_controls.addWidget(self.audit_start)
        audit_controls.addWidget(QLabel("থেকে"))
        audit_controls.addWidget(self.audit_end)
        audit_controls.addStretch(1)
        audit_layout.addLayout(audit_controls)
        self.audit_table = DataTable(
            [
                TableColumn("created_at", "সময়", width=160),
                TableColumn("actor", "ব্যবহারকারী", width=130),
                TableColumn("action", "কাজ", width=150),
                TableColumn("entity_type", "এন্টিটি", width=140),
                TableColumn("entity_id", "আইডি", "int", 70),
                TableColumn("summary", "বিবরণ", width=300),
            ]
        )
        audit_card = Card("অডিট ট্রেইল")
        audit_card.add(self.audit_table)
        audit_layout.addWidget(audit_card)
        self.tabs.addTab(audit_page, "অডিট লগ")

        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        profile = self.services.profile.get()
        mapping = {
            "name": profile.name,
            "address": profile.address,
            "phone": profile.phone,
            "email": profile.email,
            "tax_number": profile.tax_number,
            "receipt_footer": profile.receipt_footer,
        }
        for key, value in mapping.items():
            self.profile_labels[key].setText(value or "—")
        settings = self.services.settings.all()
        self.settings_table.set_rows([{"key": k, "value": v} for k, v in sorted(settings.items())])
        self.users_table.set_rows(self.services.users.list())
        self._load_audit()

    def _load_audit(self) -> None:
        rows = self.services.audit.search(
            start=self.audit_start.date().toString("yyyy-MM-dd"),
            end=self.audit_end.date().toString("yyyy-MM-dd"),
            limit=500,
        )
        self.audit_table.set_rows(rows)

    def _edit_profile(self) -> None:
        profile = self.services.profile.get()
        values = FormDialog.ask(
            "ব্যবসার তথ্য",
            [
                FieldSpec("name", "ব্যবসার নাম", "text", required=True, value=profile.name),
                FieldSpec("tagline", "ট্যাগলাইন", "text", value=profile.tagline),
                FieldSpec("address", "ঠিকানা", "textarea", value=profile.address),
                FieldSpec("phone", "মোবাইল", "text", value=profile.phone),
                FieldSpec("email", "ইমেইল", "text", value=profile.email),
                FieldSpec("website", "ওয়েবসাইট", "text", value=profile.website),
                FieldSpec("tax_number", "BIN / টিন নম্বর", "text", value=profile.tax_number),
                FieldSpec("logo_path", "লোগো ফাইলের পথ", "text", value=profile.logo_path),
                FieldSpec("receipt_header", "রিসিট হেডার", "textarea", value=profile.receipt_header),
                FieldSpec("receipt_footer", "রিসিট ফুটার", "textarea", value=profile.receipt_footer),
            ],
            self,
        )
        if values is None:
            return
        from ...services.settings import BusinessProfile

        guarded(self, lambda: self.services.profile.update(BusinessProfile(**values)) or True)
        self.refresh()

    def _edit_setting(self) -> None:
        record = self.settings_table.selected_record()
        if record is None:
            show_error(self, "আগে একটি সেটিং নির্বাচন করুন")
            return
        values = FormDialog.ask(
            f"সেটিং পরিবর্তন — {record['key']}",
            [
                FieldSpec("value", "নতুন মান", "text", required=True, value=record["value"]),
            ],
            self,
        )
        if values is None:
            return
        guarded(self, lambda: self.services.settings.set(record["key"], values["value"]) or True)
        self.refresh()

    def _edit_pos(self) -> None:
        s = self.services.settings
        values = FormDialog.ask(
            "পিওএস ও ডিস্কাউন্ট",
            [
                FieldSpec("cashier", "ক্যাশিয়ারের নাম", "text", value=s.get("cashier_name", "")),
                FieldSpec(
                    "negative",
                    "নেগেটিভ স্টক অনুমতি",
                    "combo",
                    options=[("0", "না"), ("1", "হ্যাঁ")],
                    value=s.get("allow_negative_stock", "0"),
                ),
                FieldSpec(
                    "max_item",
                    "সর্বোচ্চ আইটেম ডিস্কাউন্ট (%)",
                    "money",
                    value=s.get_int("max_item_discount_bp", 10000),
                ),
                FieldSpec(
                    "max_invoice",
                    "সর্বোচ্চ ইনভয়েস ডিস্কাউন্ট (%)",
                    "money",
                    value=s.get_int("max_invoice_discount_bp", 10000),
                ),
                FieldSpec("tax", "ডিফল্ট ট্যাক্স (%)", "money", value=s.get_int("default_tax_bp", 0)),
                FieldSpec(
                    "require_shift",
                    "ক্যাশ নিতে শিফট বাধ্যতামূলক",
                    "combo",
                    options=[("1", "হ্যাঁ"), ("0", "না")],
                    value=s.get("require_open_register_for_cash", "1"),
                ),
            ],
            self,
        )
        if values is None:
            return
        s.update(
            {
                "cashier_name": values["cashier"],
                "allow_negative_stock": values["negative"],
                "max_item_discount_bp": str(values["max_item"]),
                "max_invoice_discount_bp": str(values["max_invoice"]),
                "default_tax_bp": str(values["tax"]),
                "require_open_register_for_cash": values["require_shift"],
            }
        )
        show_info(self, "সেটিংস সংরক্ষিত হয়েছে")
        self.refresh()

    def _edit_printer(self) -> None:
        from ...printing.documents import available_printers, default_printer_name

        try:
            printers = available_printers()
        except (RuntimeError, ImportError):
            printers = []
        options = [(p, p) for p in printers] or [(default_printer_name() or "", "ডিফল্ট প্রিন্টার")]
        s = self.services.settings
        values = FormDialog.ask(
            "প্রিন্টার সেটিংস",
            [
                FieldSpec(
                    "printer", "রিসিট প্রিন্টার", "combo", options=options, value=s.get("printer_name", "")
                ),
                FieldSpec(
                    "label_printer",
                    "লেবেল প্রিন্টার",
                    "combo",
                    options=[("", "— নেই —")] + options,
                    value=s.get("label_printer_name", ""),
                ),
                FieldSpec(
                    "width",
                    "কাগজের প্রস্থ",
                    "combo",
                    options=[("58", "৫৮ মিমি"), ("80", "৮০ মিমি"), ("210", "A4 (২১০ মিমি)")],
                    value=s.get("paper_width_mm", "80"),
                ),
                FieldSpec(
                    "raster",
                    "বাংলা রাস্টার প্রিন্ট (থার্মালের জন্য প্রস্তাবিত)",
                    "combo",
                    options=[("1", "হ্যাঁ"), ("0", "না")],
                    value=s.get("receipt_raster_mode", "1"),
                ),
                FieldSpec("copies", "রিসিট কপি সংখ্যা", "int", value=s.get_int("receipt_copies", 1)),
                FieldSpec("margin", "মার্জিন (মিমি)", "int", value=s.get_int("receipt_margin_mm", 3)),
            ],
            self,
        )
        if values is None:
            return
        s.update(
            {
                "printer_name": values["printer"] or "",
                "label_printer_name": values["label_printer"] or "",
                "paper_width_mm": values["width"],
                "receipt_raster_mode": values["raster"],
                "receipt_copies": str(values["copies"]),
                "receipt_margin_mm": str(values["margin"]),
            }
        )
        show_info(self, "প্রিন্টার সেটিংস সংরক্ষিত হয়েছে")
        self.refresh()

    # ------------------------------------------------------------------ users
    def _create_user(self) -> None:
        values = FormDialog.ask(
            "নতুন ব্যবহারকারী",
            [
                FieldSpec("username", "ইউজারনেম", "text", required=True),
                FieldSpec("display_name", "পূর্ণ নাম", "text", required=True),
                FieldSpec(
                    "role",
                    "ভূমিকা",
                    "combo",
                    options=[("cashier", "ক্যাশিয়ার"), ("manager", "ম্যানেজার"), ("owner", "মালিক")],
                ),
                FieldSpec("password", "পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)", "text", required=True),
            ],
            self,
        )
        if values is None:
            return
        guarded(
            self,
            lambda: self.services.users.create(
                username=values["username"],
                password=values["password"],
                display_name=values["display_name"],
                role=values["role"],
            ),
        )
        self.refresh()

    def _change_password(self) -> None:
        record = self.users_table.selected_record()
        if record is None:
            show_error(self, "আগে একজন ব্যবহারকারী নির্বাচন করুন")
            return
        values = FormDialog.ask(
            "পাসওয়ার্ড পরিবর্তন",
            [
                FieldSpec("password", "নতুন পাসওয়ার্ড", "text", required=True, help="কমপক্ষে ৮ অক্ষর"),
            ],
            self,
        )
        if values is None:
            return
        guarded(self, lambda: self.services.users.set_password(record["id"], values["password"]) or True)
        show_info(self, "পাসওয়ার্ড পরিবর্তিত হয়েছে")

    def _toggle_user(self) -> None:
        record = self.users_table.selected_record()
        if record is None:
            return
        guarded(
            self, lambda: self.services.users.set_active(record["id"], not bool(record["is_active"])) or True
        )
        self.refresh()


class BackupView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("ব্যাকআপ ও রিস্টোর", "সম্পূর্ণ ডেটা সংরক্ষণ, যাচাই এবং নিরাপদ পুনরুদ্ধার")
        header.add_action("এখনই ব্যাকআপ নিন", self._create, kind="Primary")
        header.add_action("ফাইল যাচাই করুন", self._validate)
        header.add_action("রিস্টোর করুন", self._restore, kind="Danger")
        header.add_action("ব্যাকআপ সেটিংস", self._settings)
        layout.addWidget(header)

        kpis = QHBoxLayout()
        self.count_card = KpiCard("মোট ব্যাকআপ", "০")
        self.last_card = KpiCard("সর্বশেষ ব্যাকআপ", "—")
        self.dir_card = KpiCard("ব্যাকআপ ফোল্ডার", "—")
        for card in (self.count_card, self.last_card, self.dir_card):
            kpis.addWidget(card)
        layout.addLayout(kpis)

        self.files_table = DataTable(
            [
                TableColumn("name", "ফাইল", width=300),
                TableColumn("size_text", "আকার", width=110),
                TableColumn("modified", "সময়", width=170),
            ]
        )
        card = Card("ব্যাকআপ ফাইল")
        card.add(self.files_table)
        layout.addWidget(card, 1)

        self.history = DataTable(
            [
                TableColumn("created_at", "সময়", width=170),
                TableColumn("backup_type", "ধরন", width=120),
                TableColumn("file_name", "ফাইল", width=280),
                TableColumn("size_bytes", "আকার (বাইট)", "int", 130),
                TableColumn("status", "স্ট্যাটাস", width=100),
                TableColumn("notes", "বিবরণ", width=220),
            ]
        )
        history_card = Card("ব্যাকআপ হিস্ট্রি")
        history_card.add(self.history)
        layout.addWidget(history_card, 1)

    def refresh(self) -> None:
        files = self.services.backup.list_files()
        rows = [
            {
                "path": f["path"],
                "name": f["file_name"],
                "size_text": f"{f['size_bytes'] / 1024:.1f} KB",
                "modified": f["modified"].replace("T", " "),
            }
            for f in files
        ]
        self.files_table.set_rows(rows)
        self.count_card.set_value(str(len(files)))
        self.last_card.set_value(rows[0]["modified"] if rows else "কখনো নয়")
        self.dir_card.set_value(str(self.services.backup.backup_dir()))
        self.history.set_rows(self.services.backup.history(limit=100))

    def _selected_path(self) -> Path | None:
        record = self.files_table.selected_record()
        if record is None:
            show_error(self, "আগে একটি ব্যাকআপ ফাইল নির্বাচন করুন")
            return None
        return Path(record["path"])

    def _create(self) -> None:
        result = guarded(self, lambda: self.services.backup.create())
        if result:
            show_info(self, f"ব্যাকআপ সম্পন্ন\n{result['path']}\nআকার: {result['size_bytes'] / 1024:.1f} KB")
        self.refresh()

    def _validate(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        report = guarded(self, lambda: self.services.backup.validate(path))
        if report:
            show_info(
                self,
                "ব্যাকআপ ফাইল সঠিক ✓\n\n"
                f"অ্যাপ সংস্করণ: {report['app_version']}\n"
                f"স্কিমা সংস্করণ: {report['schema_version']}\n"
                f"তৈরির সময়: {report['created_at']}",
            )

    def _restore(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        if not confirm(
            self,
            "রিস্টোর করলে বর্তমান সব ডেটা এই ব্যাকআপের ডেটা দিয়ে প্রতিস্থাপিত হবে।\n\n"
            "নিরাপত্তার জন্য রিস্টোরের আগে বর্তমান ডেটার একটি ব্যাকআপ নেওয়া হবে।\n\n"
            "আপনি কি নিশ্চিত?",
            "রিস্টোর নিশ্চিত করুন",
        ):
            return
        result = guarded(self, lambda: self.services.backup.restore(path, confirmed=True))
        if result:
            show_info(self, "রিস্টোর সফল হয়েছে ✓\n\nঅ্যাপ্লিকেশনটি এখন পুনরায় চালু করুন।")
        self.refresh()

    def _settings(self) -> None:
        s = self.services.settings
        directory = QFileDialog.getExistingDirectory(
            self, "ব্যাকআপ ফোল্ডার নির্বাচন", s.get("backup_dir") or str(Path.home())
        )
        values = FormDialog.ask(
            "ব্যাকআপ সেটিংস",
            [
                FieldSpec(
                    "auto",
                    "স্বয়ংক্রিয় ব্যাকআপ",
                    "combo",
                    options=[("1", "চালু"), ("0", "বন্ধ")],
                    value=s.get("backup_auto_enabled", "1"),
                ),
                FieldSpec(
                    "interval",
                    "কত মিনিট পর পর",
                    "combo",
                    options=[
                        ("30", "৩০ মিনিট"),
                        ("60", "১ ঘণ্টা"),
                        ("120", "২ ঘণ্টা"),
                        ("360", "৬ ঘণ্টা"),
                        ("1440", "২৪ ঘণ্টা"),
                    ],
                    value=s.get("backup_interval_minutes", "120"),
                ),
                FieldSpec(
                    "on_exit",
                    "অ্যাপ বন্ধের সময় ব্যাকআপ",
                    "combo",
                    options=[("1", "হ্যাঁ"), ("0", "না")],
                    value=s.get("backup_on_exit", "1"),
                ),
                FieldSpec(
                    "retention", "কতটি স্বয়ংক্রিয় ব্যাকআপ রাখা হবে", "int", value=s.get_int("backup_retention", 20)
                ),
            ],
            self,
        )
        if values is None:
            return
        if directory:
            s.set("backup_dir", directory)
        s.update(
            {
                "backup_auto_enabled": values["auto"],
                "backup_interval_minutes": values["interval"],
                "backup_on_exit": values["on_exit"],
                "backup_retention": str(values["retention"]),
            }
        )
        show_info(self, "ব্যাকআপ সেটিংস সংরক্ষিত হয়েছে")
        self.refresh()


class ActivationView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        header = PageHeader("লাইসেন্স ও অ্যাক্টিভেশন", "আজীবন লাইসেন্স — সম্পূর্ণ অফলাইনে সক্রিয়করণ")
        header.add_action("লাইসেন্স সক্রিয় করুন", self._activate, kind="Primary")
        header.add_action("পুনরায় যাচাই", self._verify)
        header.add_action("রিকভারি ফাইল সংরক্ষণ", self._recovery)
        layout.addWidget(header)

        card = Card("লাইসেন্সের অবস্থা")
        self.status_labels: dict[str, QLabel] = {}
        for key, label in (
            ("state", "স্ট্যাটাস"),
            ("business", "লাইসেন্সপ্রাপ্ত প্রতিষ্ঠান"),
            ("license_id", "লাইসেন্স আইডি"),
            ("issued", "ইস্যুর তারিখ"),
            ("fingerprint", "হার্ডওয়্যার ফিঙ্গারপ্রিন্ট"),
            ("message", "বার্তা"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(value, 1)
            card.add_layout(row)
            self.status_labels[key] = value
        layout.addWidget(card)

        note = QLabel(
            "এই কম্পিউটারের হার্ডওয়্যার ফিঙ্গারপ্রিন্ট সরবরাহকারীকে দিন। তিনি আপনার জন্য "
            "একটি স্বাক্ষরিত লাইসেন্স কী তৈরি করবেন। ইন্টারনেট সংযোগের প্রয়োজন নেই।"
        )
        note.setObjectName("HelpText")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def refresh(self) -> None:
        message = ""
        try:
            status = self.services.activation.verify()
            state_text = "সক্রিয় ✓"
        except LicenseError as exc:
            status = self.services.activation.status()
            state_text = "সক্রিয় নয়" if not status.get("activated") else "যাচাই ব্যর্থ"
            message = str(exc)
        self.status_labels["state"].setText(state_text)
        self.status_labels["business"].setText(status.get("business_name") or "—")
        self.status_labels["license_id"].setText(status.get("license_id") or "—")
        self.status_labels["issued"].setText(status.get("issued_at") or "—")
        self.status_labels["fingerprint"].setText(self._fingerprint_text())
        self.status_labels["message"].setText(message)

    def _fingerprint_text(self) -> str:
        fingerprint = self.services.activation.recovery_request()["current_fingerprint"]
        combined = fingerprint.get("fingerprint_id", "")
        components = fingerprint.get("components", {})
        parts = [f"আইডি: {combined}"]
        parts += [f"{key}: {str(value)[:12]}…" for key, value in sorted(components.items())]
        return "\n".join(parts)

    def _activate(self) -> None:
        values = FormDialog.ask(
            "লাইসেন্স সক্রিয়করণ",
            [
                FieldSpec(
                    "key",
                    "লাইসেন্স কী",
                    "textarea",
                    required=True,
                    help="সরবরাহকারীর দেওয়া RVIA1.… কী এখানে পেস্ট করুন",
                ),
                FieldSpec(
                    "bind",
                    "এই কম্পিউটারের সাথে বাঁধুন",
                    "checkbox",
                    value=False,
                    help="হার্ডওয়্যার পরিবর্তন হলে নতুন লাইসেন্স প্রয়োজন হবে",
                ),
            ],
            self,
        )
        if values is None:
            return
        record = guarded(
            self,
            lambda: self.services.activation.activate(values["key"].strip(), bind_hardware=values["bind"]),
        )
        if record:
            show_info(self, "লাইসেন্স সফলভাবে সক্রিয় হয়েছে ✓")
        self.refresh()

    def _verify(self) -> None:
        result = guarded(self, lambda: self.services.activation.verify())
        if result is not None:
            show_info(
                self,
                "লাইসেন্স বৈধ ✓\n\n"
                f"প্রতিষ্ঠান: {result.get('business_name', '')}\n"
                f"লাইসেন্স আইডি: {result.get('license_id', '')}",
            )
        self.refresh()

    def _recovery(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "রিকভারি অনুরোধ সংরক্ষণ", "retvia-recovery-request.json", "JSON (*.json)"
        )
        if not path:
            return
        saved = guarded(self, lambda: self.services.activation.export_recovery_request(path))
        if saved:
            show_info(
                self, f"রিকভারি ফাইল সংরক্ষিত:\n{saved}\n\nএই ফাইলটি সরবরাহকারীকে পাঠান; তিনি নতুন লাইসেন্স কী দেবেন।"
            )


class AboutView(QWidget):
    def __init__(self, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        layout.addWidget(PageHeader("পরিচিতি", "সফটওয়্যার সম্পর্কে তথ্য"))
        card = Card()
        brand = QLabel(__brand__)
        brand.setObjectName("SidebarBrand")
        card.add(brand)
        product = QLabel(f"{__product_name__} — রিটেইল ম্যানেজমেন্ট সিস্টেম")
        product.setObjectName("SectionTitle")
        card.add(product)
        for label, value in (
            ("সংস্করণ", __version__),
            ("প্রতিষ্ঠাতা", __founder__),
            ("যোগাযোগ", __contact__),
            ("লাইসেন্সের ধরন", "আজীবন এককালীন লাইসেন্স"),
            ("ইন্টারনেট", "সম্পূর্ণ অফলাইন — কোনো ক্লাউড সংযোগ নেই"),
            ("ডেটা", "আপনার কম্পিউটারেই সংরক্ষিত থাকে"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(value_label, 1)
            card.add_layout(row)
        layout.addWidget(card)

        health_card = Card("সিস্টেম স্বাস্থ্য")
        self.health_table = DataTable(
            [
                TableColumn("check", "যাচাই", width=220),
                TableColumn("result", "ফলাফল", width=400),
            ]
        )
        health_card.add(self.health_table)
        actions = PageHeader("", "")
        actions.add_action("স্বাস্থ্য যাচাই করুন", self._health, kind="Primary")
        health_card.add(actions)
        layout.addWidget(health_card)
        layout.addStretch(1)
        self._health()

    def _health(self) -> None:
        health = self.services.health()
        self.health_table.set_rows(health["checks"])

    def refresh(self) -> None:
        self._health()
