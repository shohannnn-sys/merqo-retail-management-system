# Development Status — Retvia

**Last updated:** 2026-11-03
**Current phase:** Phase 3 — Project Foundation
**Branch:** `arena/aba4099c-merqo-retail-management-system`
**Release status:** not released — in development

## Snapshot

| Item | State |
|---|---|
| Repository access | Verified — public repo, ADMIN permission |
| Planning & architecture | Complete |
| Business core | Not started |
| UI | Not started |
| Tests | Not started |
| Windows build | Not started |
| CI/CD | Not started |

## Environment constraints (verified, not assumed)

| Capability | State | Consequence |
|---|---|---|
| GitHub read/write | Works | Commits and pushes possible |
| PyPI / npm registry | Reachable | Dependencies installable |
| GitHub release assets | **Blocked** | Electron/NSIS binaries unavailable locally |
| nodejs.org | **Blocked** | Native Node modules cannot compile |
| Debian apt | **Blocked** | System libraries cannot be installed |
| libGL / display server | **Absent** | Qt GUI cannot render locally |
| Windows OS | **Absent** | Windows packaging must run on CI |

**Verification strategy:** the headless business core (money, inventory, sales,
purchases, returns, payments, finance, reports, licensing, backup) is tested
locally with pytest. GUI rendering, Windows packaging, installer and end-to-end
verification run on GitHub Actions `windows-latest` runners with screenshot and
log evidence. Physical printer and clean-PC installation tests remain pending
until hardware is available.

## Next exact action

Scaffold the Python package, pin dependencies, and implement the domain core
(money, quantity, validation, errors) with its test suite.

## Required permissions / owner actions

- Formal trademark and domain clearance for the name **Retvia**.
- Generation and secure custody of the production Ed25519 signing keypair.
- Setting the `RETVIA_LICENSE_PUBLIC_KEY` GitHub secret before a commercial build.
- Physical thermal printer access for print verification.
- A clean Windows PC/VM for final installation acceptance.
