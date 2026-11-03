# Architecture Decision Records — Retvia

## ADR-001 — Official product name: **Retvia**

**Status:** accepted (provisional pending formal trademark clearance)

The specification fixes the company brand as **MERQO** and requires a distinct
official product name. Candidates were screened by web search:

| Candidate | Finding | Verdict |
|---|---|---|
| Merqo One | `merqone.com` — existing procurement SaaS, near-identical pronunciation | **Rejected** |
| Retailo | "Retailo POS" on Microsoft Store; Retailo Technologies (PK) | Rejected |
| Stockora | Existing retail inventory project | Rejected |
| Retailio | Ayro Retail Solutions B2B platform (IN) | Rejected |
| Vanijo | Small clothing brand + equestrian product; "Vanijya" e-commerce app | Rejected |
| **Retvia** | No software-class hits; only a phonetically similar diet product ("Retiva") in an unrelated class | **Selected** |

Retvia is coined (retail + via), six letters, pronounceable in Bengali (রেটভিয়া)
and English, premium, and not tied to POS alone, so it remains valid as the
product grows into a full ERP.

**Limitation disclosed:** screening was limited to public web search. Formal
trademark registry search (Bangladesh DPDT, USPTO, EUIPO), domain acquisition and
legal clearance are **owner actions and remain pending**. Nothing here is a claim
that the name is legally available or trademark-free.

## ADR-002 — Python 3.12 + PySide6 instead of Electron/Tauri/.NET

**Status:** accepted

Driven by two forces: (a) Bengali complex-script fidelity for thermal printing and
PDF, and (b) the build environment. Qt's text engine shapes Bengali conjuncts
correctly and `QPrinter` addresses exact paper widths in millimetres. The Python
stack installs entirely from the allowlisted package index and its business core
is fully testable headlessly. Electron/Tauri/.NET toolchains require hosts that are
blocked in this environment and could not be built or verified here. Full
comparison in ARCHITECTURE.md §1.

## ADR-003 — Integer minor units for money and quantity

**Status:** accepted

Money is stored and computed as integer poisha; quantity as integer milli-units.
This removes an entire class of floating-point defects that are unacceptable in a
commercial accounting product. SQLite columns are `INTEGER`. Conversion to display
strings happens only at the presentation boundary.

## ADR-004 — Moving Average Cost

**Status:** accepted

MAC suits Bangladeshi retail: prices fluctuate per purchase, FIFO batches add
operational complexity for shopkeepers, and standard cost drifts from reality.
MAC is recomputed on each receipt and snapshotted into sale items so historical
profit is never restated. Policy details in docs/FINANCIAL_POLICY.md.

## ADR-005 — Ed25519 offline licensing with owner-held private key

**Status:** accepted

Ed25519 gives small, fast, offline-verifiable signatures. The private key exists
only in the private License Generator, encrypted at rest with scrypt + AES-256-GCM.
The application embeds only the public key, injected at build time from a GitHub
secret. Hardware binding is optional and tolerant, with owner-issued re-activation
as the recovery path, so legitimate customers are never permanently locked out.

## ADR-006 — Backup as a checksummed archive, not a raw file copy

**Status:** accepted

A raw copy of a live WAL database can be inconsistent. Backups use `VACUUM INTO`
for a consistent snapshot, then package the database, business assets and a
manifest with per-member SHA-256 into a `.retvia-backup` ZIP. Restore validates,
stages, takes a pre-restore backup, swaps, and re-checks integrity.

## ADR-007 — Windows builds run on GitHub Actions, not in the dev sandbox

**Status:** accepted (environment constraint)

The sandbox blocks GitHub release assets, `nodejs.org` and Debian apt, and has no
`libGL`/display. Windows packaging, installer creation, silent-install verification
and GUI screenshot capture therefore execute on `windows-latest` runners. This is
recorded as a constraint, not hidden: local verification covers the headless
business core; Windows verification is evidenced by CI logs and artifacts.

## ADR-008 — Single session branch for the automated agent

**Status:** accepted (platform constraint)

The Arena agent is pinned to `arena/aba4099c-merqo-retail-management-system` and
must not create or push other branches. The branch strategy in CONTRIBUTING.md
applies to human maintainers; the agent delivers via its session branch and pull
requests. Repository visibility is never changed by the agent.
