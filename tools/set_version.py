"""Synchronise the product version across source, packaging and docs.

python tools/set_version.py 1.0.0
python tools/set_version.py v1.0.0 --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def normalise(raw: str) -> tuple[int, int, int]:
    match = SEMVER.match(raw.strip())
    if not match:
        raise SystemExit(f"ERROR: '{raw}' is not a semantic version (expected 1.2.3 or v1.2.3)")
    return int(match[1]), int(match[2]), int(match[3])


def apply(version: tuple[int, int, int]) -> list[Path]:
    text = ".".join(str(part) for part in version)
    quad = (*version, 0)
    changed: list[Path] = []

    init = ROOT / "retvia" / "__init__.py"
    updated = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{text}"', init.read_text(encoding="utf-8"))
    init.write_text(updated, encoding="utf-8")
    changed.append(init)

    pyproject = ROOT / "pyproject.toml"
    updated = re.sub(
        r'^version = "[^"]+"',
        f'version = "{text}"',
        pyproject.read_text(encoding="utf-8"),
        count=1,
        flags=re.MULTILINE,
    )
    pyproject.write_text(updated, encoding="utf-8")
    changed.append(pyproject)

    resource = ROOT / "packaging" / "version_info.txt"
    content = resource.read_text(encoding="utf-8")
    content = re.sub(r"filevers=\([^)]*\)", f"filevers={quad}", content)
    content = re.sub(r"prodvers=\([^)]*\)", f"prodvers={quad}", content)
    content = re.sub(
        r"StringStruct\('FileVersion', '[^']*'\)",
        f"StringStruct('FileVersion', '{'.'.join(str(p) for p in quad)}')",
        content,
    )
    content = re.sub(
        r"StringStruct\('ProductVersion', '[^']*'\)", f"StringStruct('ProductVersion', '{text}')", content
    )
    resource.write_text(content, encoding="utf-8")
    changed.append(resource)

    installer = ROOT / "packaging" / "installer.iss"
    content = installer.read_text(encoding="utf-8")
    content = re.sub(r'#define AppVersion "[^"]+"', f'#define AppVersion "{text}"', content)
    installer.write_text(content, encoding="utf-8")
    changed.append(installer)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    version = normalise(args.version)
    text = ".".join(str(part) for part in version)

    if args.check:
        content = (ROOT / "retvia" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__ = "([^"]+)"', content)
        if not match or match[1] != text:
            print(f"ERROR: source version is {match[1] if match else 'missing'}, expected {text}")
            return 1
        print(f"Version check passed: {text}")
        return 0

    for path in apply(version):
        print(f"updated {path.relative_to(ROOT)}")
    print(f"Version set to {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
