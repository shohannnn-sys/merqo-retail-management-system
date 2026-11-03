# Licensing — how Retvia activation works

Retvia is sold as a **one-time, lifetime licence**. Activation is **fully
offline**: there is no licence server, no account, no subscription check and no
network call at any point.

---

## 1. Cryptographic design

| Piece | Where it lives | Who can see it |
| --- | --- | --- |
| Ed25519 **private** signing key | Owner's encrypted vault (`%LOCALAPPDATA%\RetviaOwnerTools\owner-vault.json`) | Owner only |
| Ed25519 **public** verification key | Bundled in the application as `retvia/assets/license_public_key.json` | Everyone (it is public by design) |
| Issued licence key | Given to the customer as text or a small JSON file | That customer |
| Activation record | The customer's own SQLite database | That customer |

The application can **verify** a licence but cannot **create** one. Possessing
the application, its source code and the public key does not allow anyone to
issue a valid licence — that requires the private key, which is never shipped,
never committed and never present in CI.

### Why Ed25519

* 32-byte keys, 64-byte signatures — the whole licence fits in a copy-pasteable string.
* Deterministic signatures, so re-signing the same payload is reproducible.
* Fast verification with no parameter choices to get wrong.
* Available in `cryptography`, which is already a dependency.

---

## 2. Licence key format

```
RVIA1.<base64url(canonical JSON payload)>.<base64url(Ed25519 signature)>
```

* `canonical JSON` means `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
  encoded as UTF-8. Any change to whitespace, key order or content invalidates the signature.
* The signature covers the **exact payload bytes**, so adding, removing or editing
  a field is detected.

### Payload claims

| Claim | Meaning |
| --- | --- |
| `license_id` | Unique identifier for this issuance |
| `product_id` | Must equal `merqo-retvia` |
| `business_name` | The licensed business, shown in the About / Licence screen |
| `business_identity` | Owner-supplied identity (phone or e-mail) used for support |
| `license_version` | Format version, currently `1` |
| `license_type` | Always `lifetime` |
| `issued_at` | UTC ISO-8601 timestamp |
| `hardware_fingerprint` | Optional; present only for machine-bound licences |
| `notes` | Free text from the issuer |
| `nonce` | Random value so two licences for the same business differ |

### What is rejected

The verifier refuses a licence when any of these is true:

* the signature does not match the bundled public key (forged or self-signed);
* any payload byte was altered, or a field was added or removed;
* `product_id` is not `merqo-retvia`;
* `license_type` is not `lifetime`;
* a required claim is missing;
* the stored activation row in the database was edited (re-verified on **every** launch);
* the licence is bound to hardware that does not match this machine.

---

## 3. Hardware binding and recovery

Hardware binding is **optional**. The owner decides per customer.

The fingerprint is built from several independent components, each hashed with
SHA-256 so the raw values never leave the machine:

* Windows `MachineGuid` (registry) or `/etc/machine-id`
* system UUID
* hostname
* processor description
* architecture
* a coarse memory-size bucket

A licence matches when **at least 3 components** are unchanged
(`DEFAULT_MIN_MATCHES`). This tolerates a RAM upgrade, a hostname change or a
disk replacement without breaking a working installation, while still failing
on a genuinely different computer.

### Recovery flow (no internet needed)

1. On the new/changed machine the customer opens **লাইসেন্স → রিকভারি ফাইল সংরক্ষণ**.
2. Retvia writes `retvia-recovery-request.json` containing the new fingerprint
   and the previous licence id. It contains **no personal data and no secrets**.
3. The customer sends that file to MERQO by any channel (e-mail, USB, messaging).
4. The owner opens it in the License Generator → **হার্ডওয়্যার রিকভারি** → issues a
   new licence bound to the new fingerprint. The old licence id is recorded as
   `supersedes` in the owner's private registry.
5. The customer pastes the new key. Done.

---

## 4. Owner workflow

> The License Generator is **owner-only**. Its source is not in this repository,
> its executable is not in any release, and it must never be given to a customer.
> See `docs/OWNER_TOOL_SETUP.md` for how it is built privately.

1. **Create the keypair once.** The generator writes an encrypted vault
   (scrypt `n=2^15, r=8, p=1` + AES-256-GCM, minimum 8-character passphrase).
2. **Export the public key** and add it to the repository secret
   `RETVIA_LICENSE_PUBLIC_KEY`. Release builds inject it.
3. **Take an encrypted private-key backup** immediately and store it offline.
   If the vault and its backup are both lost, no further licences can be issued
   for that key and every existing customer would need a new keypair — so keep
   at least two offline copies.
4. **Issue a licence** per customer: business name, identity, optional hardware
   binding. Every issuance is recorded in the owner's private registry.
5. **Handle recovery** as described above.

---

## 5. What CI does (and does not) have

CI never sees a production private key.

* The **CI** and **Windows build** workflows generate a *fresh ephemeral*
  keypair inside the runner, inject its public half, sign a test licence and
  prove the whole activation chain works. The private half dies with the job.
* The **release** workflow refuses to publish unless the repository secret
  `RETVIA_LICENSE_PUBLIC_KEY` (the owner's real **public** key) is present.
* A dedicated job fails the build if any private key, vault, issuance database
  or owner-tool source is ever tracked by git.

---

## 6. Honest limitations

* Offline activation cannot be **revoked remotely**. A leaked licence key that is
  not hardware-bound can be reused on another machine. Hardware binding is the
  mitigation; use it for customers who agree to it.
* A sufficiently determined attacker with local administrator access could patch
  the binary. Signature verification raises the bar substantially but no offline
  scheme is unbreakable.
* The product name **Retvia** has been screened for obvious conflicts, but formal
  trademark and domain clearance is still an owner action and has **not** been
  performed.
