"""Retvia design system — a single premium light theme.

There is deliberately no dark mode and no theme switching. All colours, spacing,
radii and typography live here so every screen shares one visual language.
"""

from __future__ import annotations

from ..paths import resource_path

# ---------------------------------------------------------------- design tokens
COLORS = {
    "bg": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
    "text": "#1B2430",
    "text_muted": "#64748B",
    "text_subtle": "#94A3B8",
    "primary": "#1F3A5F",
    "primary_hover": "#284B78",
    "primary_soft": "#E8EEF6",
    "accent": "#0E7C66",
    "accent_soft": "#E3F4F0",
    "warning": "#B45309",
    "warning_soft": "#FEF3E2",
    "danger": "#B42318",
    "danger_soft": "#FEECEB",
    "info": "#1D4ED8",
    "info_soft": "#E8EEFF",
    "sidebar": "#16273D",
    "sidebar_hover": "#22374F",
    "sidebar_active": "#2E4A68",
    "sidebar_text": "#C7D3E0",
}

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 6, "md": 10, "lg": 14}
FONT_SIZE = {"xs": 11, "sm": 12, "base": 13, "md": 15, "lg": 18, "xl": 22, "xxl": 28}

FONT_FAMILY = "'Noto Sans Bengali', 'Nirmala UI', 'Segoe UI', sans-serif"
FONT_DIR = resource_path("assets", "fonts")


def load_fonts() -> list[str]:
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


def stylesheet() -> str:
    c = COLORS
    return f"""
    QWidget {{
        background: {c["bg"]};
        color: {c["text"]};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE["base"]}px;
    }}
    QMainWindow, QDialog {{ background: {c["bg"]}; }}

    /* ---------------- sidebar ---------------- */
    #Sidebar {{ background: {c["sidebar"]}; border: none; }}
    #SidebarBrand {{
        color: #FFFFFF; font-size: {FONT_SIZE["xl"]}px; font-weight: 700;
        padding: {SPACE["lg"]}px {SPACE["lg"]}px {SPACE["xs"]}px {SPACE["lg"]}px;
        background: transparent;
    }}
    #SidebarTag {{
        color: {c["sidebar_text"]}; font-size: {FONT_SIZE["xs"]}px;
        padding: 0 {SPACE["lg"]}px {SPACE["md"]}px {SPACE["lg"]}px; background: transparent;
    }}
    #Sidebar QLabel {{ background: transparent; color: {c["sidebar_text"]}; }}
    #SidebarProduct {{
        color: #8FA3BA; font-size: {FONT_SIZE["xs"]}px;
        padding: 0 {SPACE["lg"]}px; background: transparent;
    }}
    #SidebarUser {{
        color: {c["sidebar_text"]}; font-size: {FONT_SIZE["sm"]}px;
        padding: {SPACE["sm"]}px {SPACE["lg"]}px; background: transparent;
    }}
    #Sidebar QPushButton#Ghost {{ color: {c["sidebar_text"]}; text-align: left; }}
    #Sidebar QPushButton#Ghost:hover {{ background: {c["sidebar_hover"]}; color: #FFFFFF; }}
    #Sidebar QScrollArea, #Sidebar QScrollArea > QWidget > QWidget {{ background: transparent; }}
    #TopbarBusiness {{ font-size: {FONT_SIZE["md"]}px; font-weight: 700; }}
    #NavButton {{
        background: transparent; color: {c["sidebar_text"]};
        text-align: left; padding: 9px {SPACE["lg"]}px;
        border: none; border-left: 3px solid transparent;
        font-size: {FONT_SIZE["base"]}px;
    }}
    #NavButton:hover {{ background: {c["sidebar_hover"]}; color: #FFFFFF; }}
    #NavButton:checked {{
        background: {c["sidebar_active"]}; color: #FFFFFF;
        border-left: 3px solid {c["accent"]}; font-weight: 600;
    }}
    #NavGroup {{
        color: #7C8DA3; font-size: {FONT_SIZE["xs"]}px; font-weight: 700;
        padding: {SPACE["md"]}px {SPACE["lg"]}px {SPACE["xs"]}px {SPACE["lg"]}px;
        background: transparent; letter-spacing: 0.5px;
    }}

    /* ---------------- topbar ---------------- */
    #Topbar {{ background: {c["surface"]}; border-bottom: 1px solid {c["border"]}; }}
    #Topbar QLabel {{ background: transparent; }}
    #PageTitle {{ font-size: {FONT_SIZE["lg"]}px; font-weight: 700; }}
    #PageSubtitle {{ color: {c["text_muted"]}; font-size: {FONT_SIZE["sm"]}px; }}
    #StatusChip {{
        background: {c["accent_soft"]}; color: {c["accent"]};
        border-radius: {RADIUS["sm"]}px; padding: 4px 10px; font-size: {FONT_SIZE["xs"]}px;
        font-weight: 600;
    }}
    #StatusChipWarn {{
        background: {c["warning_soft"]}; color: {c["warning"]};
        border-radius: {RADIUS["sm"]}px; padding: 4px 10px; font-size: {FONT_SIZE["xs"]}px;
        font-weight: 600;
    }}

    /* ---------------- cards ---------------- */
    #Card {{
        background: {c["surface"]}; border: 1px solid {c["border"]};
        border-radius: {RADIUS["md"]}px;
    }}
    #Card QLabel {{ background: transparent; }}
    #CardTitle {{ font-size: {FONT_SIZE["md"]}px; font-weight: 700; }}
    #KpiLabel {{ color: {c["text_muted"]}; font-size: {FONT_SIZE["sm"]}px; }}
    #KpiValue {{ font-size: {FONT_SIZE["xl"]}px; font-weight: 700; }}
    #KpiValueAccent {{ font-size: {FONT_SIZE["xl"]}px; font-weight: 700; color: {c["accent"]}; }}
    #KpiValueDanger {{ font-size: {FONT_SIZE["xl"]}px; font-weight: 700; color: {c["danger"]}; }}
    #KpiHint {{ color: {c["text_subtle"]}; font-size: {FONT_SIZE["xs"]}px; }}

    /* ---------------- buttons ---------------- */
    QPushButton {{
        background: {c["surface"]}; color: {c["text"]};
        border: 1px solid {c["border_strong"]}; border-radius: {RADIUS["sm"]}px;
        padding: 7px 14px; font-size: {FONT_SIZE["base"]}px; min-height: 18px;
    }}
    QPushButton:hover {{ background: {c["surface_alt"]}; border-color: {c["primary"]}; }}
    QPushButton:pressed {{ background: {c["primary_soft"]}; }}
    QPushButton:disabled {{ color: {c["text_subtle"]}; background: {c["surface_alt"]}; }}
    QPushButton#Primary {{
        background: {c["primary"]}; color: #FFFFFF; border: 1px solid {c["primary"]};
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {c["primary_hover"]}; }}
    QPushButton#Primary:disabled {{ background: {c["border_strong"]}; border-color: {c["border_strong"]}; }}
    QPushButton#Accent {{
        background: {c["accent"]}; color: #FFFFFF; border: 1px solid {c["accent"]}; font-weight: 600;
    }}
    QPushButton#Accent:hover {{ background: #0B6B58; }}
    QPushButton#Danger {{
        background: {c["danger_soft"]}; color: {c["danger"]}; border: 1px solid #F3C7C3;
    }}
    QPushButton#Danger:hover {{ background: #FBDCD9; }}
    QPushButton#Ghost {{ background: transparent; border: none; color: {c["primary"]}; }}
    QPushButton#Ghost:hover {{ background: {c["primary_soft"]}; }}
    QPushButton#BigAction {{
        background: {c["accent"]}; color: #FFFFFF; border: none;
        font-size: {FONT_SIZE["md"]}px; font-weight: 700; padding: 14px;
        border-radius: {RADIUS["md"]}px;
    }}
    QPushButton#BigAction:hover {{ background: #0B6B58; }}

    /* ---------------- inputs ---------------- */
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {{
        background: {c["surface"]}; border: 1px solid {c["border_strong"]};
        border-radius: {RADIUS["sm"]}px; padding: 7px 10px;
        selection-background-color: {c["primary"]}; selection-color: #FFFFFF;
        min-height: 18px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {{
        border: 1px solid {c["primary"]};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ background: {c["surface_alt"]}; color: {c["text_muted"]}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c["surface"]}; border: 1px solid {c["border_strong"]};
        selection-background-color: {c["primary_soft"]}; selection-color: {c["text"]};
        outline: none;
    }}
    QLabel#FieldLabel {{ font-size: {FONT_SIZE["sm"]}px; color: {c["text_muted"]}; font-weight: 600; }}
    QLabel#FieldError {{ font-size: {FONT_SIZE["xs"]}px; color: {c["danger"]}; }}
    QLabel#HelpText {{ font-size: {FONT_SIZE["xs"]}px; color: {c["text_subtle"]}; }}

    /* ---------------- tables ---------------- */
    QTableWidget, QTableView {{
        background: {c["surface"]}; border: 1px solid {c["border"]};
        border-radius: {RADIUS["sm"]}px; gridline-color: {c["border"]};
        alternate-background-color: {c["surface_alt"]};
    }}
    QTableWidget::item, QTableView::item {{ padding: 6px 8px; border: none; }}
    QTableWidget::item:selected, QTableView::item:selected {{
        background: {c["primary_soft"]}; color: {c["text"]};
    }}
    QHeaderView::section {{
        background: {c["surface_alt"]}; color: {c["text_muted"]};
        padding: 8px; border: none; border-bottom: 1px solid {c["border"]};
        font-weight: 700; font-size: {FONT_SIZE["sm"]}px;
    }}
    QTableCornerButton::section {{ background: {c["surface_alt"]}; border: none; }}
    QListWidget {{
        background: {c["surface"]}; border: 1px solid {c["border"]};
        border-radius: {RADIUS["sm"]}px; padding: 4px; outline: none;
    }}
    QListWidget::item {{ padding: 7px 8px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: {c["primary_soft"]}; color: {c["text"]}; }}
    QListWidget::item:hover {{ background: {c["surface_alt"]}; }}
    QSplitter::handle {{ background: {c["border"]}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QStatusBar {{ background: {c["surface"]}; border-top: 1px solid {c["border"]};
                  color: {c["text_muted"]}; font-size: {FONT_SIZE["sm"]}px; }}
    QMenuBar {{ background: {c["surface"]}; border-bottom: 1px solid {c["border"]}; }}
    QMenuBar::item:selected {{ background: {c["primary_soft"]}; }}
    QMenu {{ background: {c["surface"]}; border: 1px solid {c["border_strong"]}; padding: 4px; }}
    QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c["primary_soft"]}; }}

    /* ---------------- misc ---------------- */
    QScrollArea {{ border: none; background: {c["bg"]}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c["border_strong"]}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c["text_subtle"]}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c["border_strong"]}; border-radius: 5px; min-width: 30px; }}
    QTabWidget::pane {{ border: 1px solid {c["border"]}; border-radius: {RADIUS["sm"]}px; background: {c["surface"]}; }}
    QTabBar::tab {{
        background: transparent; color: {c["text_muted"]}; padding: 8px 16px;
        border-bottom: 2px solid transparent; font-weight: 600;
    }}
    QTabBar::tab:selected {{ color: {c["primary"]}; border-bottom: 2px solid {c["primary"]}; }}
    QGroupBox {{
        border: 1px solid {c["border"]}; border-radius: {RADIUS["sm"]}px;
        margin-top: {SPACE["md"]}px; padding-top: {SPACE["md"]}px; font-weight: 600;
        background: {c["surface"]};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {c["text_muted"]}; }}
    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1px solid {c["border_strong"]};
        border-radius: 4px; background: {c["surface"]};
    }}
    QCheckBox::indicator:checked {{ background: {c["primary"]}; border-color: {c["primary"]}; }}
    QToolTip {{
        background: {c["sidebar"]}; color: #FFFFFF; border: none; padding: 6px 8px;
        border-radius: 4px; font-size: {FONT_SIZE["sm"]}px;
    }}
    QMessageBox {{ background: {c["surface"]}; }}
    QLabel#EmptyState {{ color: {c["text_subtle"]}; font-size: {FONT_SIZE["md"]}px; padding: 40px; }}
    QLabel#SectionTitle {{ font-size: {FONT_SIZE["md"]}px; font-weight: 700; }}
    QLabel#Muted {{ color: {c["text_muted"]}; }}
    QFrame#Divider {{ background: {c["border"]}; max-height: 1px; border: none; }}
    QProgressBar {{
        border: 1px solid {c["border"]}; border-radius: {RADIUS["sm"]}px;
        background: {c["surface_alt"]}; text-align: center; height: 16px;
    }}
    QProgressBar::chunk {{ background: {c["accent"]}; border-radius: {RADIUS["sm"]}px; }}
    """
