# Security Policy — MERQO Retvia

## Reporting a vulnerability

Please report security issues privately to **merqoonline@gmail.com**.
Do **not** open public issues for security vulnerabilities. Include a
description, reproduction steps, and impact assessment. We aim to
acknowledge reports within 72 hours.

## Supported versions

Only the latest released minor version receives security fixes.

## Security model (summary)

- **Offline-first.** The application performs no network calls during
  normal operation. No telemetry or analytics is enabled by default.
- **Local data ownership.** All business data lives in a local SQLite
  database in the Windows user-data directory. The user owns their data.
- **Licensing.** Licenses are signed with Ed25519. The private signing key
  exists only in the private License Generator and is never shipped with
  the main application or committed to this repository. The main
  application embeds only the public verification key.
- **No secrets in source.** Private keys, passwords, customer data,
  production license files and signing material are excluded via
  `.gitignore` and must never be committed. CI uses GitHub Secrets.
- **Input validation & parameterized SQL.** All database access uses
  prepared statements; all user input is validated at the service layer.
- **Safe file handling.** Backup/restore paths are validated; restore
  always creates a pre-restore backup and verifies integrity.
- **Audit trail.** Financial and stock mutations are recorded in an
  append-only audit log.

## Known limitations

Offline software cannot provide an absolute anti-piracy guarantee. The
licensing system implements practical defense-in-depth (cryptographic
signatures, integrity checks, tamper detection) but a determined attacker
with full control of the machine may bypass client-side checks. This is an
accepted limitation of fully offline lifetime-licensed software.

## Secret handling checklist for contributors

- [ ] No private signing keys committed
- [ ] No real customer/business data committed
- [ ] No production license files committed
- [ ] No credentials, tokens or passwords committed
- [ ] `.env` files excluded (only `.env.example` allowed)
