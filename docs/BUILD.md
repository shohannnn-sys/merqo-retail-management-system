# Building Retvia

Everything needed to produce the Windows installer is in this repository and
runs on a standard `windows-latest` GitHub Actions runner. No paid service,
no code-signing subscription and no online activation server is required.

---

## 1. Local development (any OS)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

ruff check retvia tests tools      # lint
ruff format --check retvia tests tools
mypy retvia                        # static types
pytest                             # 354 tests
python -m retvia                   # run the desktop app
```

`python -m retvia --smoke-test --screenshot-dir build/shots` opens every screen,
captures a PNG of each and exits non-zero if any screen fails. On a headless
Linux box set `QT_QPA_PLATFORM=offscreen`; you also need `libGL.so.1` present.

### Where data lives

| Platform | Path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Retvia\` |
| macOS | `~/Library/Application Support/Retvia/` |
| Linux | `$XDG_DATA_HOME/retvia` (default `~/.local/share/retvia`) |

Override with `RETVIA_DATA_DIR`. Inside it: `data/retvia.db`, `backups/`,
`logs/`, `assets/business/`. **Nothing is ever written next to the executable.**

---

## 2. Building the Windows executable locally

```powershell
pip install -r requirements.txt -r requirements-dev.txt

# A verification key must exist. For a development build only:
python tools/ci_license.py --public-out retvia/assets/license_public_key.json `
                           --license-out build/dev-license.txt

pyinstaller packaging/retvia.spec --noconfirm --clean
# → dist/Retvia/Retvia.exe
```

For a **production** build, replace that JSON with the public key exported from
the owner's real vault. The spec aborts if the file is missing, so you cannot
accidentally ship an application that is unable to verify licences.

### Building the installer

```powershell
choco install innosetup -y
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" `
    /DAppVersion=1.0.0 /DSourceDir=..\dist\Retvia /DOutputDir=..\dist\installer `
    packaging\installer.iss
# → dist/installer/Retvia-Setup-1.0.0.exe
```

Installer behaviour:

* per-user install by default (no UAC prompt); an all-users install into
  `Program Files` is offered in the privileges dialog;
* completely offline — the PyInstaller folder already contains the Python
  runtime, Qt and every dependency;
* the uninstaller removes only program files and explicitly tells the user that
  `%LOCALAPPDATA%\Retvia` was preserved.

---

## 3. Cutting a release

```bash
python tools/set_version.py 1.0.0      # syncs source, pyproject, version resource, installer
# update CHANGELOG.md and RELEASE_NOTES.md
git commit -am "release: v1.0.0"
git tag v1.0.0
git push origin main --tags
```

The `Release` workflow then:

1. re-runs lint, format check, mypy and the full test suite;
2. injects the production public key from the `RETVIA_LICENSE_PUBLIC_KEY` secret
   (fails the build if the secret is absent);
3. builds the executable and the installer;
4. silently installs it, launches it, renders and screenshots **every** screen,
   activates a licence, checks database integrity, then uninstalls and asserts
   the user data survived;
5. produces SHA-256 checksums;
6. asserts no owner-only artifact is present;
7. publishes the installer, the portable ZIP and `SHA256SUMS.txt` to the GitHub release.

### Required repository secrets

| Secret | Required by | Content |
| --- | --- | --- |
| `RETVIA_LICENSE_PUBLIC_KEY` | `release.yml` | The **public** half of the owner's Ed25519 key (base64). Safe to store in CI. |
| `OWNER_TOOL_SOURCE_B64` | `owner-tool-build.yml` | Base64 ZIP of the private owner tool source. See `OWNER_TOOL_SETUP.md`. |

No private key is ever stored in GitHub.

---

## 4. Workflows at a glance

| Workflow | Trigger | What it proves |
| --- | --- | --- |
| `ci.yml` | every push / PR | lint, format, mypy, 354 tests on Linux **and** Windows, every Qt screen renders offscreen, offline activation works, dependency audit, no secrets tracked |
| `windows-build.yml` | pushes touching app/packaging, or manual | real EXE + installer, silent install, launch, screen render, activation, data-preserving uninstall, checksums |
| `release.yml` | `v*.*.*` tag | everything above with the production public key, then publishes the release |
| `owner-tool-build.yml` | manual only | builds the owner-only generator from the private secret; artifact expires in 7 days and is never attached to a release |

---

## 5. Reproducibility notes

* All runtime and development dependencies are pinned in `requirements*.txt`.
* `tools/make_icon.py` regenerates the icon byte-for-byte; CI fails if the
  committed icon differs from a fresh render.
* PyInstaller runs with `upx=False` so binaries are not rewritten by a packer.
* The build is one-folder rather than one-file: faster startup, no temporary
  extraction of Qt DLLs, and individual files can be serviced.

---

## 6. What has and has not been verified

Be precise about this when reporting status.

**Verified locally (headless Linux, this repository):**

* financial maths, quantity maths, validation, text normalisation;
* database migrations, ACID transactions, integrity and foreign-key checks;
* catalog, inventory, POS, purchases, payments, returns, expenses, cash shifts;
* the finance engine and all 34 reports, on populated and empty databases;
* backup creation, validation, tamper detection and restore;
* Ed25519 issuance → activation → re-verification → hardware recovery;
* CSV and XLSX exports for every report;
* the full service container end-to-end, including local authentication;
* lint, formatting and static typing.

**Verified only in CI (Windows runner):**

* the Qt user interface actually rendering — proven by per-screen screenshots;
* PyInstaller producing a working executable;
* Inno Setup producing a working installer;
* silent install, first-run database creation and uninstall data preservation;
* PDF rendering and the print pipeline executing without error.

**Not verified anywhere — requires real hardware:**

* output on a physical 58 mm or 80 mm thermal printer (paper width, cut command,
  Bangla raster legibility);
* a physical barcode scanner's exact prefix/suffix behaviour;
* a real label printer's alignment;
* installation on a customer's own Windows PC outside the CI runner.

These are listed in `KNOWN_ISSUES.md` and must be tested on real devices before
general availability.
