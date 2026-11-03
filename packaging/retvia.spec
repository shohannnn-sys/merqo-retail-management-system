# PyInstaller spec for the Retvia customer application (Windows, one-folder).
#
#   pyinstaller packaging/retvia.spec --noconfirm --clean
#
# One-folder (not one-file) is deliberate: faster startup, no temp extraction of
# Qt DLLs, and the installer can service individual files. Business data never
# lives beside the executable — it is created under %LOCALAPPDATA%\Retvia.

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "Retvia"

datas = [
    (str(ROOT / "retvia" / "assets" / "fonts"), "retvia/assets/fonts"),
    (str(ROOT / "retvia" / "data" / "migrations"), "retvia/data/migrations"),
    (str(ROOT / "retvia" / "assets" / "icon.png"), "retvia/assets"),
    (str(ROOT / "retvia" / "assets" / "icon.ico"), "retvia/assets"),
]

# The public verification key is injected by the build. Without it the app
# cannot validate any license, so the build fails loudly instead of shipping a
# silently unlicensed product.
public_key_file = ROOT / "retvia" / "assets" / "license_public_key.json"
if public_key_file.is_file():
    datas.append((str(public_key_file), "retvia/assets"))
elif not os.environ.get("RETVIA_ALLOW_MISSING_KEY"):
    raise SystemExit(
        "ERROR: retvia/assets/license_public_key.json is missing.\n"
        "Generate it with the owner License Generator, or set RETVIA_ALLOW_MISSING_KEY=1 "
        "for a development build."
    )

for extra in ("docs", "THIRD_PARTY_NOTICES.md", "LICENSE", "CHANGELOG.md"):
    candidate = ROOT / extra
    if candidate.exists():
        datas.append((str(candidate), extra if candidate.is_dir() else "."))

hiddenimports = [
    "openpyxl",
    "openpyxl.cell._writer",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
    "cryptography.hazmat.primitives.kdf.scrypt",
    "sqlite3",
    "PIL",
    "barcode",
    "barcode.writer",
    "qrcode",
    "qrcode.image.pil",
    "retvia.ui.views.labels",
    "retvia.ui.views.catalog",
    "retvia.ui.views.dashboard",
    "retvia.ui.views.documents",
    "retvia.ui.views.finance_views",
    "retvia.ui.views.inventory",
    "retvia.ui.views.parties",
    "retvia.ui.views.pos",
    "retvia.ui.views.products",
    "retvia.ui.views.reports",
    "retvia.ui.views.system",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "entry_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "runtime_hook.py")],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtBluetooth", "PySide6.QtMultimedia", "PySide6.QtQuick3D",
        "PySide6.QtNetworkAuth", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "pytest", "ruff", "mypy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "retvia" / "assets" / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
