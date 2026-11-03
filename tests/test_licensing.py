"""Licensing security tests: forgery, tampering, identity and recovery."""

import json

import pytest

from retvia.core.errors import LicenseError
from retvia.services.licensing import (
    ActivationService,
    build_license_key,
    canonical_json,
    decrypt_private_key,
    encrypt_private_key,
    fingerprint_matches,
    generate_keypair,
    make_fingerprint,
    new_license_payload,
    parse_license_key,
    public_key_from_private,
    sign_payload,
    validate_payload_claims,
    verify_payload,
)


@pytest.fixture()
def keypair():
    return generate_keypair()


@pytest.fixture()
def signed_license(keypair):
    private, public = keypair
    payload = new_license_payload(
        business_name="মেসার্স নিউ স্টোর", business_identity="BD-01712345678"
    ).to_dict()
    signature = sign_payload(payload, private)
    return build_license_key(payload, signature), payload, public


class TestCryptography:
    def test_keypair_lengths(self, keypair):
        private, public = keypair
        assert len(private) >= 42 and len(public) >= 42

    def test_public_derivable_from_private(self, keypair):
        private, public = keypair
        assert public_key_from_private(private) == public

    def test_sign_and_verify(self, keypair):
        private, public = keypair
        payload = {"a": 1, "b": "বাংলা"}
        signature = sign_payload(payload, private)
        assert verify_payload(payload, signature, public)

    def test_canonical_json_is_deterministic(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_unicode_preserved_in_signature(self, keypair):
        private, public = keypair
        payload = {"business_name": "মেসার্স রহমান ট্রেডার্স"}
        assert verify_payload(payload, sign_payload(payload, private), public)

    def test_wrong_public_key_fails(self, keypair):
        private, _ = keypair
        _, other_public = generate_keypair()
        payload = {"a": 1}
        assert not verify_payload(payload, sign_payload(payload, private), other_public)


class TestForgeryResistance:
    def test_modified_business_name_rejected(self, signed_license, keypair):
        key, payload, public = signed_license
        _, signature = parse_license_key(key)
        forged = dict(payload, business_name="অন্য দোকান")
        assert not verify_payload(forged, signature, public)

    def test_modified_identity_rejected(self, signed_license):
        key, payload, public = signed_license
        _, signature = parse_license_key(key)
        forged = dict(payload, business_identity="BD-99999999999")
        assert not verify_payload(forged, signature, public)

    def test_added_field_rejected(self, signed_license):
        key, payload, public = signed_license
        _, signature = parse_license_key(key)
        forged = dict(payload, admin=True)
        assert not verify_payload(forged, signature, public)

    def test_forged_signature_rejected(self, signed_license):
        key, payload, public = signed_license
        assert not verify_payload(payload, "A" * 86, public)

    def test_self_signed_license_rejected(self, signed_license):
        key, payload, legit_public = signed_license
        attacker_private, _ = generate_keypair()
        forged_key = build_license_key(payload, sign_payload(payload, attacker_private))
        parsed, signature = parse_license_key(forged_key)
        assert not verify_payload(parsed, signature, legit_public)

    def test_garbage_key_rejected(self):
        for bad in ("", "hello", "RVIA1.onlytwo", "XXXX.a.b", "RVIA1.!!!.???"):
            with pytest.raises(LicenseError):
                parse_license_key(bad)

    def test_wrong_product_rejected(self, keypair):
        private, public = keypair
        payload = new_license_payload(business_name="দোকান", business_identity="X").to_dict()
        payload["product_id"] = "some-other-product"
        signature = sign_payload(payload, private)
        assert verify_payload(payload, signature, public)
        with pytest.raises(LicenseError, match="অন্য প্রোডাক্ট"):
            validate_payload_claims(payload)

    def test_wrong_identity_claim_rejected(self, signed_license):
        _, payload, _ = signed_license
        with pytest.raises(LicenseError, match="আইডেন্টিটি"):
            validate_payload_claims(payload, expected_identity="BD-00000000000")

    def test_correct_identity_claim_accepted(self, signed_license):
        _, payload, _ = signed_license
        validate_payload_claims(payload, expected_identity="BD-01712345678")

    def test_non_lifetime_type_rejected(self, keypair):
        private, _ = keypair
        payload = new_license_payload(business_name="দোকান", business_identity="X").to_dict()
        payload["license_type"] = "subscription"
        with pytest.raises(LicenseError):
            validate_payload_claims(payload)

    def test_missing_fields_rejected(self):
        with pytest.raises(LicenseError):
            validate_payload_claims({"product_id": "merqo-retvia", "license_version": 1,
                                     "license_type": "lifetime"})


class TestHardwareFingerprint:
    def test_stable_for_same_components(self):
        components = {"machine_guid": "abc", "hostname": "shop-pc", "processor": "x64"}
        assert make_fingerprint(components)["id"] == make_fingerprint(components)["id"]

    def test_unbound_license_always_matches(self):
        assert fingerprint_matches(None, make_fingerprint({"a": "1"}))

    def test_tolerates_single_component_change(self):
        base = {"machine_guid": "g", "hostname": "h", "processor": "p", "architecture": "a"}
        stored = make_fingerprint(base)
        changed = make_fingerprint({**base, "hostname": "new-pc"})
        assert fingerprint_matches(stored, changed)

    def test_rejects_wholly_different_machine(self):
        stored = make_fingerprint({"machine_guid": "g1", "hostname": "h1", "processor": "p1"})
        other = make_fingerprint({"machine_guid": "g2", "hostname": "h2", "processor": "p2"})
        assert not fingerprint_matches(stored, other)

    def test_no_personal_data_in_components(self):
        fp = make_fingerprint({"hostname": "shop", "machine_guid": "secret-guid"})
        assert "secret-guid" not in json.dumps(fp)
        assert "shop" not in json.dumps(fp)


class TestPrivateKeyProtection:
    def test_encrypt_decrypt_roundtrip(self, keypair):
        private, _ = keypair
        blob = encrypt_private_key(private, "correct horse battery")
        assert private not in json.dumps(blob)
        assert decrypt_private_key(blob, "correct horse battery") == private

    def test_wrong_passphrase_fails(self, keypair):
        private, _ = keypair
        blob = encrypt_private_key(private, "right-passphrase")
        with pytest.raises(LicenseError):
            decrypt_private_key(blob, "wrong-passphrase")

    def test_short_passphrase_rejected(self, keypair):
        with pytest.raises(LicenseError):
            encrypt_private_key(keypair[0], "short")

    def test_tampered_ciphertext_fails(self, keypair):
        blob = encrypt_private_key(keypair[0], "passphrase123")
        blob["ciphertext"] = "A" + blob["ciphertext"][1:]
        with pytest.raises(LicenseError):
            decrypt_private_key(blob, "passphrase123")


class TestActivation:
    def test_activation_and_verify(self, db, signed_license):
        key, payload, public = signed_license
        service = ActivationService(db, public_key=public)
        result = service.activate(key, business_identity="BD-01712345678")
        assert result["activated"] is True
        assert result["business_name"] == "মেসার্স নিউ স্টোর"
        assert service.verify()["activated"] is True

    def test_unactivated_verify_raises(self, db, keypair):
        service = ActivationService(db, public_key=keypair[1])
        with pytest.raises(LicenseError, match="অ্যাক্টিভ"):
            service.verify()

    def test_wrong_business_identity_blocks_activation(self, db, signed_license):
        key, _, public = signed_license
        service = ActivationService(db, public_key=public)
        with pytest.raises(LicenseError):
            service.activate(key, business_identity="BD-00000000000")

    def test_forged_key_blocks_activation(self, db, keypair):
        _, public = keypair
        attacker_private, _ = generate_keypair()
        payload = new_license_payload(business_name="জাল দোকান", business_identity="X").to_dict()
        forged = build_license_key(payload, sign_payload(payload, attacker_private))
        service = ActivationService(db, public_key=public)
        with pytest.raises(LicenseError, match="স্বাক্ষর"):
            service.activate(forged)

    def test_tampered_database_record_detected(self, db, signed_license):
        key, _, public = signed_license
        service = ActivationService(db, public_key=public)
        service.activate(key)
        record = service.active_record()
        tampered = json.loads(record["payload_json"])
        tampered["business_name"] = "হ্যাক করা নাম"
        db.execute("UPDATE license_activations SET payload_json=? WHERE id=?",
                   (json.dumps(tampered, ensure_ascii=False), record["id"]))
        with pytest.raises(LicenseError, match="স্বাক্ষর"):
            service.verify()

    def test_activation_survives_reopen(self, db, signed_license):
        key, _, public = signed_license
        ActivationService(db, public_key=public).activate(key)
        db.close()
        db.reopen()
        assert ActivationService(db, public_key=public).verify()["activated"]

    def test_reactivation_supersedes_previous(self, db, keypair):
        private, public = keypair
        service = ActivationService(db, public_key=public)
        first = new_license_payload(business_name="দোকান", business_identity="ID-1").to_dict()
        service.activate(build_license_key(first, sign_payload(first, private)))
        second = new_license_payload(business_name="দোকান", business_identity="ID-1").to_dict()
        service.activate(build_license_key(second, sign_payload(second, private)))
        assert db.scalar("SELECT COUNT(*) FROM license_activations WHERE status='active'") == 1
        assert db.scalar("SELECT COUNT(*) FROM license_activations WHERE status='superseded'") == 1
        assert service.status()["license_id"] == second["license_id"]

    def test_hardware_bound_license_rejects_other_machine(self, db, keypair):
        private, public = keypair
        payload = new_license_payload(
            business_name="দোকান", business_identity="ID-1",
            hardware_fingerprint=make_fingerprint(
                {"machine_guid": "other1", "hostname": "other2", "processor": "other3"}
            ),
        ).to_dict()
        key = build_license_key(payload, sign_payload(payload, private))
        service = ActivationService(db, public_key=public)
        with pytest.raises(LicenseError, match="কম্পিউটার"):
            service.activate(key)

    def test_recovery_request_contains_fingerprint(self, db, signed_license):
        key, _, public = signed_license
        service = ActivationService(db, public_key=public)
        service.activate(key)
        request = service.recovery_request()
        assert request["previous_license_id"]
        assert request["current_fingerprint"]["id"]
        assert request["business_identity"] == "BD-01712345678"

    def test_recovery_request_export(self, db, signed_license, tmp_path):
        key, _, public = signed_license
        service = ActivationService(db, public_key=public)
        service.activate(key)
        path = service.export_recovery_request(tmp_path / "recovery.json")
        assert json.loads(path.read_text(encoding="utf-8"))["previous_license_id"]

    def test_activation_never_touches_business_data(self, db, signed_license, products, unit_id):
        from retvia.services.catalog import ProductInput

        pid = products.create(ProductInput(name="পণ্য", sku="S1", unit_id=unit_id, opening_qty=5000))
        key, _, public = signed_license
        ActivationService(db, public_key=public).activate(key)
        assert products.get(pid)["stock_qty"] == 5000

    def test_failed_activation_never_deletes_data(self, db, products, unit_id, keypair):
        from retvia.services.catalog import ProductInput

        pid = products.create(ProductInput(name="পণ্য", sku="S1", unit_id=unit_id, opening_qty=5000))
        service = ActivationService(db, public_key=keypair[1])
        with pytest.raises(LicenseError):
            service.activate("RVIA1.bogus.bogus")
        assert products.get(pid)["stock_qty"] == 5000
