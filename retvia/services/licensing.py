"""Offline licensing: Ed25519-signed lifetime licenses.

Security model
--------------
* The **private signing key never ships** with the application. It exists only in
  the private License Generator, encrypted at rest with scrypt + AES-256-GCM.
* The application embeds only the **public verification key**, injected at build
  time from the ``RETVIA_LICENSE_PUBLIC_KEY`` secret.
* A license is canonical JSON plus a detached Ed25519 signature, transported as a
  single copy-pasteable key: ``RVIA1.<base64url(payload)>.<base64url(signature)>``.
* Verification is fully offline and runs on every launch. A failed check never
  deletes or modifies business data.

Offline software cannot offer an absolute anti-piracy guarantee; this module
implements practical defense-in-depth, and recovery is always possible through an
owner-issued re-activation license.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .. import __product_id__, __version__
from ..core.errors import LicenseError
from ..core.textnorm import clean_text

KEY_PREFIX = "RVIA1"
LICENSE_VERSION = 1
LICENSE_TYPE_LIFETIME = "lifetime"
PUBLIC_KEY_ENV = "RETVIA_LICENSE_PUBLIC_KEY"
DEFAULT_MIN_MATCHES = 3


# --------------------------------------------------------------------- base64
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as exc:
        raise LicenseError("লাইসেন্স কী-এর ফরম্যাট সঠিক নয়") from exc


def canonical_json(payload: dict[str, Any]) -> bytes:
    """Deterministic serialization — the exact bytes that get signed."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------- keypair
def generate_keypair() -> tuple[str, str]:
    """Return ``(private_b64, public_b64)`` raw Ed25519 keys (32 bytes each)."""
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return _b64e(private_raw), _b64e(public_raw)


def public_key_from_private(private_b64: str) -> str:
    private = Ed25519PrivateKey.from_private_bytes(_b64d(private_b64))
    return _b64e(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    )


def sign_payload(payload: dict[str, Any], private_b64: str) -> str:
    try:
        private = Ed25519PrivateKey.from_private_bytes(_b64d(private_b64))
    except (ValueError, TypeError) as exc:
        raise LicenseError("প্রাইভেট কী সঠিক নয়") from exc
    return _b64e(private.sign(canonical_json(payload)))


def verify_payload(payload: dict[str, Any], signature_b64: str, public_b64: str) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(_b64d(public_b64))
        public.verify(_b64d(signature_b64), canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ------------------------------------------------------------------- payload
@dataclass(slots=True)
class LicensePayload:
    license_id: str
    business_name: str
    business_identity: str
    product_id: str = __product_id__
    license_version: int = LICENSE_VERSION
    license_type: str = LICENSE_TYPE_LIFETIME
    issued_at: str = ""
    hardware_fingerprint: dict[str, Any] | None = None
    notes: str = ""
    nonce: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["hardware_fingerprint"] is None:
            data.pop("hardware_fingerprint")
        return data


def new_license_payload(
    *,
    business_name: str,
    business_identity: str,
    hardware_fingerprint: dict[str, Any] | None = None,
    notes: str = "",
) -> LicensePayload:
    business_name = clean_text(business_name, max_length=200)
    business_identity = clean_text(business_identity, max_length=120)
    if not business_name:
        raise LicenseError("ব্যবসার নাম আবশ্যক")
    if not business_identity:
        raise LicenseError("বিজনেস আইডেন্টিটি আবশ্যক")
    return LicensePayload(
        license_id=f"LIC-{uuid.uuid4().hex[:16].upper()}",
        business_name=business_name,
        business_identity=business_identity,
        issued_at=datetime.now(UTC).isoformat(timespec="seconds"),
        hardware_fingerprint=hardware_fingerprint,
        notes=clean_text(notes, max_length=500),
        nonce=uuid.uuid4().hex,
    )


def build_license_key(payload: dict[str, Any], signature_b64: str) -> str:
    return f"{KEY_PREFIX}.{_b64e(canonical_json(payload))}.{signature_b64}"


def parse_license_key(key: str) -> tuple[dict[str, Any], str]:
    cleaned = "".join((key or "").split())
    parts = cleaned.split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise LicenseError("লাইসেন্স কী সঠিক নয় — সম্পূর্ণ কী পেস্ট করুন")
    try:
        payload = json.loads(_b64d(parts[1]).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LicenseError("লাইসেন্স কী পড়া যায়নি") from exc
    if not isinstance(payload, dict):
        raise LicenseError("লাইসেন্স কী-এর গঠন সঠিক নয়")
    return payload, parts[2]


def validate_payload_claims(payload: dict[str, Any], *, expected_identity: str | None = None) -> None:
    """Check product, version and business identity (signature checked separately)."""
    if payload.get("product_id") != __product_id__:
        raise LicenseError("এই লাইসেন্স অন্য প্রোডাক্টের জন্য")
    if int(payload.get("license_version", 0)) != LICENSE_VERSION:
        raise LicenseError("লাইসেন্স সংস্করণ সমর্থিত নয়")
    if payload.get("license_type") != LICENSE_TYPE_LIFETIME:
        raise LicenseError("শুধু লাইফটাইম লাইসেন্স সমর্থিত")
    for field in ("license_id", "business_name", "business_identity", "issued_at"):
        if not payload.get(field):
            raise LicenseError(f"লাইসেন্সে '{field}' অনুপস্থিত")
    if expected_identity is not None and (
        clean_text(payload["business_identity"]).casefold() != clean_text(expected_identity).casefold()
    ):
        raise LicenseError("এই লাইসেন্স অন্য ব্যবসাপ্রতিষ্ঠানের — বিজনেস আইডেন্টিটি মিলছে না")


# -------------------------------------------------------------- fingerprint
def collect_hardware_components() -> dict[str, str]:
    """Gather stable-ish machine attributes. Never includes personal data."""
    components: dict[str, str] = {}
    system = platform.system()
    if system == "Windows":
        try:
            import winreg  # type: ignore[import-not-found]

            with winreg.OpenKey(  # type: ignore[attr-defined]
                winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                components["machine_guid"] = str(winreg.QueryValueEx(key, "MachineGuid")[0])  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - missing key must not block activation
            pass
        try:
            output = subprocess.run(
                ["wmic", "csproduct", "get", "uuid"], capture_output=True, text=True, timeout=8
            )
            lines = [ln.strip() for ln in output.stdout.splitlines() if ln.strip()]
            if len(lines) > 1:
                components["system_uuid"] = lines[1]
        except Exception:  # noqa: BLE001
            pass
    else:
        for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            path = Path(candidate)
            if path.is_file():
                components["machine_guid"] = path.read_text(encoding="utf-8").strip()
                break
    components["hostname"] = platform.node()
    components["processor"] = platform.processor() or platform.machine()
    components["architecture"] = platform.machine()
    try:
        components["memory_bucket"] = str(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024**3)
        )
    except (ValueError, AttributeError, OSError):
        components["memory_bucket"] = "unknown"
    return {k: v for k, v in components.items() if v and v != "unknown"}


def make_fingerprint(components: dict[str, str] | None = None) -> dict[str, Any]:
    """Hash each component separately so matching can be tolerant."""
    components = components if components is not None else collect_hardware_components()
    hashed = {
        key: hashlib.sha256(f"{key}:{value}".encode()).hexdigest()[:32]
        for key, value in sorted(components.items())
    }
    combined = hashlib.sha256(canonical_json(hashed)).hexdigest()[:32]
    return {"id": combined, "components": hashed}


def fingerprint_matches(
    stored: dict[str, Any] | None,
    current: dict[str, Any] | None,
    *,
    min_matches: int = DEFAULT_MIN_MATCHES,
) -> bool:
    """Tolerant comparison: hardware upgrades must not lock out a valid customer."""
    if not stored:
        return True  # unbound license
    if not current:
        return False
    stored_components = stored.get("components", {})
    current_components = current.get("components", {})
    if not stored_components:
        return stored.get("id") == current.get("id")
    shared = set(stored_components) & set(current_components)
    matches = sum(1 for key in shared if stored_components[key] == current_components[key])
    required = min(min_matches, len(stored_components))
    return matches >= required


# ------------------------------------------------------- private key at rest
def encrypt_private_key(private_b64: str, passphrase: str) -> dict[str, Any]:
    if len(passphrase) < 8:
        raise LicenseError("পাসফ্রেজ কমপক্ষে ৮ অক্ষরের হতে হবে")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(nonce, _b64d(private_b64), None)
    return {
        "kdf": "scrypt",
        "n": 2**15,
        "r": 8,
        "p": 1,
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
        "cipher": "AES-256-GCM",
    }


def decrypt_private_key(blob: dict[str, Any], passphrase: str) -> str:
    try:
        key = Scrypt(
            salt=_b64d(blob["salt"]),
            length=32,
            n=int(blob.get("n", 2**15)),
            r=int(blob.get("r", 8)),
            p=int(blob.get("p", 1)),
        ).derive(passphrase.encode("utf-8"))
        raw = AESGCM(key).decrypt(_b64d(blob["nonce"]), _b64d(blob["ciphertext"]), None)
        return _b64e(raw)
    except (InvalidTag, InvalidSignature, KeyError, ValueError, TypeError) as exc:
        raise LicenseError("পাসফ্রেজ সঠিক নয় বা কী ফাইল নষ্ট") from exc


def load_public_key(bundled_path: Path | None = None) -> tuple[str, bool]:
    """Return ``(public_key_b64, is_development_key)``.

    Priority: build-time environment injection, then the bundled key file.
    """
    injected = os.environ.get(PUBLIC_KEY_ENV, "").strip()
    if injected:
        return injected, False
    if bundled_path is None:
        bundled_path = Path(__file__).resolve().parent.parent / "assets" / "license_public_key.json"
    if bundled_path.is_file():
        try:
            data = json.loads(bundled_path.read_text(encoding="utf-8"))
            return str(data["public_key"]), bool(data.get("development", False))
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            raise LicenseError("পাবলিক কী ফাইল পড়া যায়নি") from exc
    raise LicenseError("লাইসেন্স যাচাই কী কনফিগার করা নেই — বিল্ডে RETVIA_LICENSE_PUBLIC_KEY সেট করুন")


# ---------------------------------------------------------------- activation
class ActivationService:
    """Stores and re-verifies the activation record in the local database."""

    def __init__(self, db: Any, public_key: str | None = None) -> None:
        self.db = db
        self._public_key = public_key

    @property
    def public_key(self) -> str:
        if self._public_key is None:
            self._public_key, _ = load_public_key()
        return self._public_key

    def activate(
        self,
        license_key: str,
        *,
        business_identity: str | None = None,
        bind_hardware: bool = False,
    ) -> dict[str, Any]:
        payload, signature = parse_license_key(license_key)
        if not verify_payload(payload, signature, self.public_key):
            raise LicenseError("লাইসেন্স স্বাক্ষর যাচাই ব্যর্থ — কী পরিবর্তিত বা জাল")
        validate_payload_claims(payload, expected_identity=business_identity)
        stored_fp = payload.get("hardware_fingerprint")
        current_fp = make_fingerprint()
        if stored_fp and not fingerprint_matches(stored_fp, current_fp):
            raise LicenseError("এই লাইসেন্স অন্য কম্পিউটারের জন্য বাঁধা — MERQO-এর কাছে রি-অ্যাক্টিভেশন লাইসেন্স চান")
        record = {
            "license_id": payload["license_id"],
            "product_id": payload["product_id"],
            "business_name": payload["business_name"],
            "business_identity": payload["business_identity"],
            "license_version": int(payload["license_version"]),
            "issued_at": payload["issued_at"],
            "license_type": payload["license_type"],
            "hardware_fingerprint": json.dumps(stored_fp or {}, ensure_ascii=False),
            "payload_json": canonical_json(payload).decode("utf-8"),
            "signature": signature,
        }
        with self.db.transaction():
            self.db.execute("UPDATE license_activations SET status='superseded' WHERE status='active'")
            activation_id = self.db.insert(
                """INSERT INTO license_activations
                   (license_id, product_id, business_name, business_identity, license_version,
                    issued_at, license_type, hardware_fingerprint, payload_json, signature, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?, 'active')""",
                tuple(record.values()),
            )
            self.db.execute(
                """INSERT INTO app_settings (key, value) VALUES ('business_identity', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (payload["business_identity"],),
            )
            self.db.execute(
                "UPDATE business_profile SET name=? WHERE id=1 AND (name='' OR name IS NULL)",
                (payload["business_name"],),
            )
        return {"activation_id": activation_id, **self.status()}

    def active_record(self) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM license_activations WHERE status='active' ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None

    def verify(self) -> dict[str, Any]:
        """Re-verify on every launch. Raises LicenseError when not usable."""
        record = self.active_record()
        if record is None:
            raise LicenseError("সফটওয়্যার অ্যাক্টিভ করা হয়নি")
        try:
            payload = json.loads(record["payload_json"])
        except json.JSONDecodeError as exc:
            raise LicenseError("অ্যাক্টিভেশন রেকর্ড নষ্ট") from exc
        if not verify_payload(payload, record["signature"], self.public_key):
            raise LicenseError("অ্যাক্টিভেশন রেকর্ডের স্বাক্ষর মিলছে না — সম্ভবত পরিবর্তন করা হয়েছে")
        validate_payload_claims(payload)
        stored_fp = payload.get("hardware_fingerprint")
        if stored_fp and not fingerprint_matches(stored_fp, make_fingerprint()):
            raise LicenseError("হার্ডওয়্যার পরিবর্তন শনাক্ত হয়েছে — MERQO-এর কাছে রি-অ্যাক্টিভেশন চান")
        return {"activated": True, **self.status()}

    def status(self) -> dict[str, Any]:
        record = self.active_record()
        if record is None:
            return {
                "activated": False,
                "app_version": __version__,
                "product_id": __product_id__,
                "license_type": "",
            }
        return {
            "activated": True,
            "license_id": record["license_id"],
            "business_name": record["business_name"],
            "business_identity": record["business_identity"],
            "license_type": record["license_type"],
            "issued_at": record["issued_at"],
            "activated_at": record["activated_at"],
            "hardware_bound": bool(json.loads(record["hardware_fingerprint"] or "{}")),
            "app_version": __version__,
            "product_id": record["product_id"],
        }

    def recovery_request(self) -> dict[str, Any]:
        """Data the customer sends to MERQO to obtain a re-activation license."""
        record = self.active_record()
        return {
            "product_id": __product_id__,
            "app_version": __version__,
            "previous_license_id": record["license_id"] if record else "",
            "business_name": record["business_name"] if record else "",
            "business_identity": record["business_identity"] if record else "",
            "current_fingerprint": make_fingerprint(),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    def export_recovery_request(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.recovery_request(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target
