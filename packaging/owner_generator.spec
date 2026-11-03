# PyInstaller spec for the OWNER-ONLY License Generator.
#
# This spec is public; the generator SOURCE is not. CI reconstructs the source
# from the OWNER_TOOL_SOURCE_B64 repository secret before running:
#
#   pyinstaller packaging/owner_generator.spec --noconfirm --clean
#
# The resulting EXE must never be attached to a public GitHub release.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SOURCE = ROOT / "owner-tools" / "license_generator"
APP_NAME = "Retvia-License-Generator"

if not SOURCE.is_dir():
    raise SystemExit(
        "ERROR: owner-tools/license_generator is missing.\n"
        "This build requires the private owner source (OWNER_TOOL_SOURCE_B64 secret)."
    )

datas = [
    (str(ROOT / "retvia" / "assets" / "fonts"), "retvia/assets/fonts"),
    (str(ROOT / "retvia" / "assets" / "icon.ico"), "retvia/assets"),
    (str(ROOT / "retvia" / "data" / "migrations"), "retvia/data/migrations"),
]

a = Analysis(
    [str(ROOT / "packaging" / "entry_owner.py")],
    pathex=[str(ROOT), str(ROOT / "owner-tools")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "license_generator.app",
        "license_generator.vault",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.scrypt",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "runtime_hook.py")],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "openpyxl",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "retvia" / "assets" / "icon.ico"),
)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name=APP_NAME)
