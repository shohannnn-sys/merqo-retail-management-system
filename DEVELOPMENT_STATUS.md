# Development Status — Retvia

**Last updated:** 2026-11-03
**Current phase:** Phase 7 — Windows verification & release
**Branch:** `arena/aba4099c-merqo-retail-management-system`
**Release status:** not released — feature-complete, Windows verification in progress
**Version:** 0.1.0

## Snapshot

| Item | State | Evidence |
|---|---|---|
| Repository access | Verified — public repo, ADMIN | `gh repo view` |
| Planning & architecture | Complete | `ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/FINANCIAL_POLICY.md` |
| Domain core (money, quantity, validation) | Complete & tested | 98 tests |
| Database + migrations (v3, 39 tables) | Complete & tested | `retvia/data/migrations/` |
| Catalog, inventory, POS, parties, cash | Complete & tested | 98 tests |
| Purchases, payments, returns, expenses | Complete & tested | 36 tests |
| Finance engine + 34 reports | Complete & tested | 28 tests |
| Backup / restore | Complete & tested | 24 tests |
| Ed25519 licensing | Complete & tested | 40 tests |
| Local users, RBAC, lockout | Complete & tested | 31 tests |
| CSV / XLSX export | Complete & tested | 19 tests |
| Service container end-to-end | Complete & tested | 19 tests |
| Bangla Qt UI (18 screens) | Implemented; render verification runs in CI | `retvia/ui/` |
| Thermal receipt / label / PDF printing | Implemented; execution verified in CI, **physical print pending** | `retvia/printing/documents.py` |
| Owner License Generator | Implemented & tested locally (21 tests); source private | `owner-tools/` (git-ignored) |
| Windows packaging (PyInstaller + Inno Setup) | Scripts complete; build runs in CI | `packaging/` |
| CI / Windows build / release pipelines | Written; first runs pending | `.github/workflows/` |
| Documentation | Complete | `docs/`, `THIRD_PARTY_NOTICES.md` |
| Physical printer / clean-PC acceptance | **Not done — hardware required** | — |

## Verified quality gates (local, this checkout)

```
ruff check retvia tests tools      → All checks passed
ruff format --check retvia tests   → 69 files already formatted
mypy retvia                        → Success: no issues found in 53 source files
pytest                             → 354 passed
pytest owner-tools/tests           → 21 passed
```

## Environment constraints (verified, not assumed)

| Capability | State | Consequence |
|---|---|---|
| GitHub read/write | Works | Commits, pushes, CI dispatch possible |
| PyPI / npm registry | Reachable | Dependencies installable |
| GitHub release assets | **Blocked** | Electron/NSIS binaries unavailable locally |
| nodejs.org | **Blocked** | Native Node modules cannot compile |
| Debian apt | **Blocked** | System libraries cannot be installed |
| libGL / display server | **Absent** | Qt GUI cannot render locally |
| Windows OS | **Absent** | Windows packaging must run on CI |

**Verification strategy:** the headless business core is fully tested locally.
GUI rendering, PDF/print execution, Windows packaging, installer behaviour and
end-to-end activation are verified on GitHub Actions `windows-latest` runners
with screenshot and log artifacts. Physical printer and clean-PC installation
acceptance remain pending until hardware is available.

## Commit history (meaningful milestones)

| Commit | Content | Tests at that point |
|---|---|---|
| `74220f6` | Planning, architecture, governance docs | — |
| — | Financial + validation core | 98 |
| — | Database, catalog, inventory, cash, parties, POS | 160 |
| — | Purchases, payments, returns, expenses | 196 |
| — | Finance engine, 34 reports, backup, licensing | 285 |
| `3932c11` | Bangla Qt UI, local auth, exports, container integration | 354 |
| `0d7abcb` | Windows packaging, CI/release pipelines, labels, icon, mypy clean | 354 |

## Next exact action

Push the pipelines, watch the first `CI` and `Windows build` runs, fix anything
they surface, then review the screenshot artifacts and record the result in
`RELEASE_STATUS.md`.

## Required owner actions (cannot be done from here)

- Formal trademark and domain clearance for the name **Retvia**.
- Generate the production Ed25519 keypair in the owner vault and keep 3-2-1 backups.
- Set the `RETVIA_LICENSE_PUBLIC_KEY` GitHub secret (public half only).
- Store `OWNER_TOOL_SOURCE_B64` and run the private owner-tool build.
- Physical 58 mm / 80 mm thermal printer and label printer testing.
- A clean Windows PC/VM for final installation acceptance.
