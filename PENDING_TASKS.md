# Pending Tasks — Retvia

Ordered by dependency. See MASTER_CHECKLIST.md for the full requirement matrix.

## Immediate
1. Project scaffolding and pinned dependencies.
2. Domain core: money, quantity, validation, errors + tests.
3. Database layer: connection, WAL/FK, migrations, transaction manager.
4. Full schema and repositories.
5. Audit, settings, numbering services.

## Business modules
6. Products, categories, units, barcodes.
7. Inventory: movements, adjustments, valuation, alerts.
8. Sales/POS service + atomic transaction.
9. Customers, suppliers, ledgers, payments.
10. Purchases, purchase returns, sales returns.
11. Expenses, cash register, sessions.
12. Financial engine: COGS, gross/net profit, reconciliation.
13. Reports (34 types) and dashboard analytics.
14. Export: PDF, XLSX, CSV.

## Platform
15. Design system and application shell.
16. All UI views wired to services.
17. Printing: thermal receipts, labels, test print.
18. Licensing core + activation UI + private License Generator.
19. Backup/restore with validation.
20. Settings screens.

## Quality & delivery
21. Integration, regression, security, performance test suites.
22. PyInstaller + Inno Setup packaging.
23. GitHub Actions CI, Windows build, release pipelines.
24. Windows silent-install verification with evidence.
25. User guide, private admin guide, technical documentation.
26. Final verification report.

## Owner actions (cannot be done by the agent)
- Trademark/domain clearance for "Retvia".
- Production signing key generation and secure custody.
- `RETVIA_LICENSE_PUBLIC_KEY` GitHub secret.
- Physical printer verification.
- Clean Windows PC installation acceptance.
- Repository privacy change (only the owner does this).
