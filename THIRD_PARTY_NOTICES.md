# Third-Party Notices

Retvia bundles or depends on the components below. All of them permit
redistribution inside a commercial, closed-source application under the terms
summarised here. This file ships with the installer.

Nothing in this list requires a paid licence, a subscription, an online account
or a runtime download. Retvia works fully offline after installation.

---

## Python runtime — PSF License Agreement

* Bundled inside the executable by PyInstaller.
* Copyright © Python Software Foundation.
* Permissive; redistribution in binary form is allowed.
* Full text: <https://docs.python.org/3/license.html>

## PySide6 / Qt 6 (Qt for Python) — LGPL v3

* Package: `PySide6-Essentials==6.8.1.1`
* Copyright © The Qt Company Ltd. and other contributors.
* Licensed under the GNU Lesser General Public License v3.
* Retvia uses the **Essentials** distribution only and links to Qt dynamically
  (the Qt DLLs sit beside `Retvia.exe` in the `_internal` folder). End users can
  replace those DLLs with their own compatible build, which satisfies the LGPL
  relinking requirement.
* No Qt module that requires a commercial licence is used. In particular
  Qt Charts, Qt Data Visualization and Qt WebEngine are **not** used — the charts
  in Retvia are drawn with `QPainter` by our own code.
* Full text: <https://www.gnu.org/licenses/lgpl-3.0.html> and
  <https://www.qt.io/licensing/open-source-lgpl-obligations>

## cryptography — Apache 2.0 / BSD 3-Clause (dual)

* Package: `cryptography==44.0.0`
* Copyright © The cryptography developers.
* Used for Ed25519 license signatures, AES-256-GCM key encryption and scrypt.
* Full text: <https://github.com/pyca/cryptography/blob/main/LICENSE>

## openpyxl — MIT

* Package: `openpyxl==3.1.5`
* Copyright © Eric Gazoni, Charlie Clark and contributors.
* Used to write `.xlsx` report exports.
* Full text: <https://foss.heptapod.net/openpyxl/openpyxl/-/blob/branch/3.1/LICENCE>

## Pillow — MIT-CMU (HPND)

* Package: `Pillow==11.1.0`
* Copyright © Jeffrey A. Clark and contributors.
* Used indirectly by the barcode and QR writers to produce PNG images.
* Full text: <https://github.com/python-pillow/Pillow/blob/main/LICENSE>

## python-barcode — MIT

* Package: `python-barcode==0.15.1`
* Copyright © Thorsten Weimann and contributors.
* Used to generate Code128 product barcodes.
* Full text: <https://github.com/WhyNotHugo/python-barcode/blob/main/LICENCE>

## qrcode — BSD 3-Clause

* Package: `qrcode==8.0`
* Copyright © Lincoln Loop and contributors.
* Used to generate QR codes for labels.
* Full text: <https://github.com/lincolnloop/python-qrcode/blob/main/LICENSE>

## Noto Sans Bengali — SIL Open Font License 1.1

* File: `retvia/assets/fonts/NotoSansBengali.ttf`
* Copyright © Google LLC. Noto is a trademark of Google LLC.
* Embedded in the application and in exported PDFs so Bengali text renders
  identically on every machine and on thermal printers.
* The OFL permits bundling and embedding in documents and software. The font is
  not sold on its own and its name is not used for the product.
* Full licence text ships beside the font:
  `retvia/assets/fonts/OFL-NotoSansBengali.txt`

## PyInstaller — GPL v2 with a special exception

* Build-time tool only (`pyinstaller==6.11.1`); **not** shipped to customers as a
  tool. Its bootloader is embedded in the executable under the explicit
  exception that allows distributing the generated executable under any licence.
* Full text: <https://pyinstaller.org/en/stable/license.html>

## Inno Setup — Inno Setup License (permissive)

* Build-time tool only; the generated installer may be distributed freely.
* Copyright © Jordan Russell and Martijn Laan.
* Full text: <https://jrsoftware.org/files/is/license.txt>

---

## Development-only dependencies (never shipped)

| Package | Licence | Purpose |
| --- | --- | --- |
| pytest 8.3.4 | MIT | Test runner |
| pytest-cov 6.0.0 | MIT | Coverage reporting |
| ruff 0.9.3 | MIT | Lint and format |
| mypy 1.14.1 | MIT | Static type checking |
| pip-audit 2.7.3 | Apache 2.0 | Dependency vulnerability audit |

---

## Standard library

Retvia uses `sqlite3` (public domain SQLite engine), `hashlib`, `hmac`,
`secrets`, `csv`, `json`, `zipfile`, `logging` and `decimal` from the Python
standard library. SQLite is in the public domain and requires no attribution,
but is acknowledged here for completeness: <https://www.sqlite.org/copyright.html>.

---

## Verification

The dependency set is audited on every CI run with `pip-audit`. If you redistribute
Retvia, keep this file with the application and keep the Qt DLLs replaceable.
