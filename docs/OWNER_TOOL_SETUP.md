# Owner tool setup (private License Generator)

The License Generator signs customer licences. It is **owner-only**:

* its source is **not** in this repository;
* its executable is **not** in any GitHub release;
* it is built by a manual, private workflow and delivered out of band.

This document is public because it describes only the *process*. It contains no
keys and no source.

---

## Why the source is kept out of the repo

Hiding code is not what protects the licence scheme — Ed25519 does that, and the
verification code is public. The source is kept private because the owner asked
for the generator to never appear in the public repository or releases, and
because keeping the issuance console out of public view avoids publishing
customer names and licence history alongside it.

The cryptographic primitives the generator uses (`generate_keypair`,
`new_license_payload`, `sign_payload`, `build_license_key`,
`encrypt_private_key`) live in `retvia/services/licensing.py` and are covered by
the public test suite. The private part is the console UI and the owner's vault
and issuance registry.

---

## One-time setup

### 1. Keep the private source somewhere safe

The generator source tree is:

```
owner-tools/
  license_generator/
    __init__.py
    __main__.py
    app.py        # Qt console
    vault.py      # encrypted key vault + issuance registry
  tests/
    conftest.py
    test_vault.py
```

`owner-tools/` is listed in `.gitignore`, so it can never be committed by
accident. Keep a copy in your own private storage (encrypted USB, private repo,
or password manager attachment).

### 2. Turn it into a CI secret

```bash
python tools/pack_owner_tool.py --out owner-tool-source.b64
```

Then in GitHub:

1. **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `OWNER_TOOL_SOURCE_B64`
3. Value: the entire contents of `owner-tool-source.b64`
4. Delete the local `.b64` file afterwards.

The blob contains **source code only** — no keys, no customer data.

### 3. Build the EXE privately

**Actions → "Owner tool build (private)" → Run workflow.**

The workflow restores the source into the runner, runs the vault tests, builds
`Retvia-License-Generator.exe`, zips it with a SHA-256 checksum and uploads it as
an artifact that **expires after 7 days**. It is never attached to a release.
The restored source is deleted at the end of the job.

Download the ZIP, verify the checksum, and keep the EXE only on your own machine.

---

## First run of the generator

1. **কী ভল্ট → নতুন কীপেয়ার তৈরি করুন.** Choose a strong passphrase (minimum 8
   characters; longer is better). This creates
   `%LOCALAPPDATA%\RetviaOwnerTools\owner-vault.json` containing the private key
   encrypted with scrypt + AES-256-GCM.
2. **প্রাইভেট কী ব্যাকআপ** — immediately create at least two encrypted backups on
   separate offline media. Losing the vault *and* its backups means you can no
   longer issue licences that existing installations will accept.
3. **পাবলিক কী এক্সপোর্ট** — save `license_public_key.json`.
4. Copy the `public_key` value into the GitHub secret
   `RETVIA_LICENSE_PUBLIC_KEY`. Release builds inject it automatically.

---

## Issuing a licence

1. Unlock the vault.
2. **লাইসেন্স ইস্যু** tab → enter the customer's business name and identity
   (phone or e-mail).
3. Optionally attach the customer's hardware fingerprint file to bind the
   licence to one machine.
4. **লাইসেন্স কী তৈরি করুন** → copy the key, or **গ্রাহক ফাইল সংরক্ষণ** to produce a
   small JSON file with Bangla instructions.
5. Send it to the customer. Every issuance is recorded in your private registry
   (`issuance.db`) so you can re-send it later.

## Handling a hardware change

1. Ask the customer for `retvia-recovery-request.json`
   (লাইসেন্স → রিকভারি ফাইল সংরক্ষণ in their app).
2. **হার্ডওয়্যার রিকভারি** tab → open the file → **নতুন লাইসেন্স ইস্যু করুন**.
3. Send the new key. The registry records which licence it supersedes.

---

## Rules

* Never commit `owner-tools/`, `owner-vault*.json`, `issuance.db`, any
  `*.private.json`, or `owner-tool-source.b64`. CI fails the build if it sees them.
* Never put the private key in a GitHub secret, an issue, a chat message or a
  release asset.
* Never give the generator EXE to a customer, a reseller or a support contractor.
* Keep the vault passphrase separate from the vault backup.
