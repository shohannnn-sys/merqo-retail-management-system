"""Create an EPHEMERAL signing keypair and a test license for CI verification.

This proves the whole offline activation chain on a real Windows build without
ever putting a production key in the repository. The keypair is generated fresh
in the runner's temp directory and discarded when the job ends.

    python tools/ci_license.py --public-out retvia/assets/license_public_key.json \
        --license-out build/ci-test-license.txt

The generated key is a *test* key. Production builds must use the public key
exported from the owner's real vault.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retvia import __product_id__  # noqa: E402
from retvia.services.licensing import (  # noqa: E402
    build_license_key,
    collect_hardware_components,
    generate_keypair,
    make_fingerprint,
    new_license_payload,
    sign_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-out", type=Path, required=True)
    parser.add_argument("--license-out", type=Path, required=True)
    parser.add_argument("--business-name", default="সিআই পরীক্ষা স্টোর")
    parser.add_argument("--identity", default="ci-test@retvia.local")
    parser.add_argument("--bind-hardware", action="store_true")
    args = parser.parse_args()

    private_key, public_key = generate_keypair()
    document = {
        "product_id": __product_id__,
        "public_key": public_key,
        "algorithm": "Ed25519",
        "development": True,
        "note": "Ephemeral CI key — regenerated on every run. Not a production key.",
    }
    args.public_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_out.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = new_license_payload(
        business_name=args.business_name,
        business_identity=args.identity,
        hardware_fingerprint=make_fingerprint() if args.bind_hardware else None,
        notes="CI verification license",
    ).to_dict()
    signature = sign_payload(payload, private_key)
    license_key = build_license_key(payload, signature)
    args.license_out.parent.mkdir(parents=True, exist_ok=True)
    args.license_out.write_text(license_key, encoding="utf-8")

    print(f"Public key written to {args.public_out}")
    print(f"Test license written to {args.license_out}")
    print(f"Hardware components on this runner: {sorted(collect_hardware_components())}")
    print("The private key exists only in this process and is now discarded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
