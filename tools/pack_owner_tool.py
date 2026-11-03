"""Package the private owner tool source for the GitHub Actions secret.

The License Generator source must never appear in the public repository. This
script turns ``owner-tools/license_generator`` into a single base64 blob that
you store as the repository secret ``OWNER_TOOL_SOURCE_B64``. The private
workflow decodes it at build time, builds the EXE and uploads it as a
short-lived, owner-only artifact.

    python tools/pack_owner_tool.py --out owner-tool-source.b64

Nothing secret is produced by this script itself: the blob contains source code
only. Signing keys live in the owner's encrypted vault, never in the source.
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "owner-tools" / "license_generator"


def build_blob() -> bytes:
    if not SOURCE.is_dir():
        raise SystemExit(f"ERROR: {SOURCE} does not exist. Restore your private owner source first.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(SOURCE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            archive.write(path, arcname=str(Path("license_generator") / path.relative_to(SOURCE)))
    return base64.b64encode(buffer.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "owner-tool-source.b64")
    args = parser.parse_args()
    blob = build_blob()
    args.out.write_bytes(blob)
    print(f"Wrote {args.out} ({len(blob)} base64 characters)")
    print()
    print("Next steps (owner only):")
    print("  1. GitHub → Settings → Secrets and variables → Actions → New repository secret")
    print("  2. Name: OWNER_TOOL_SOURCE_B64")
    print(f"  3. Value: the entire contents of {args.out.name}")
    print("  4. Actions → 'Owner tool build (private)' → Run workflow")
    print("  5. Download the artifact, then delete the local .b64 file")
    print()
    print("Never commit the .b64 file, the built EXE, or your vault.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
