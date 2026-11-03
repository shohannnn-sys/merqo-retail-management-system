# Master Checklist — Retvia

Legend: `[x]` done & verified · `[~]` implemented, verification pending · `[ ]` not started

## Phase 1–2 · Planning & Architecture
- [x] Requirement analysis and module dependency map
- [x] Technology stack selection with justification (ARCHITECTURE.md)
- [x] Financial calculation policy (docs/FINANCIAL_POLICY.md)
- [x] ER design and integrity rules
- [x] Licensing, backup, printing, security architecture
- [x] Product name research and selection (ADR-001)
- [x] Risk register and acceptance criteria (docs/REQUIREMENTS.md)
- [ ] Formal trademark/domain clearance — **owner action**

## Phase 3 · Foundation
- [ ] Project scaffolding, dependency pinning
- [ ] Application shell, navigation, design system
- [ ] Database connection, WAL, FK, migration framework
- [ ] Logging, error handling, audit service

## Phase 4 · Core database & business foundation
- [ ] Full schema + migrations
- [ ] Repositories and transaction management
- [ ] Money/quantity core, validation layer
- [ ] Calculation engine, invoice numbering
- [ ] Backup framework

## Phase 5 · Product & inventory
- [ ] Products CRUD, archive, duplicate prevention
- [ ] Categories, units, barcodes
- [ ] Stock movements, adjustments, valuation, alerts
- [ ] Bulk import/export

## Phase 6 · Sales & POS
- [ ] POS UI, search, barcode scan, cart
- [ ] Item/invoice discounts, tax
- [ ] Split payments, invoice generation
- [ ] Atomic sale transaction with stock + due + cash + audit

## Phase 7 · Customer & supplier
- [ ] Customer CRUD, ledger, statement, due collection
- [ ] Supplier CRUD, ledger, statement, payments

## Phase 8 · Purchase & returns
- [ ] Purchase entry + stock increase
- [ ] Purchase payment, purchase return
- [ ] Sales return with condition handling

## Phase 9 · Financial management
- [ ] Expenses and categories
- [ ] Cash register, sessions, cash in/out
- [ ] COGS, gross/net profit, receivable/payable

## Phase 10 · Reporting & export
- [ ] All 34 report types
- [ ] Dashboard analytics from live data
- [ ] PDF (embedded Bengali font), XLSX, CSV (UTF-8 BOM)

## Phase 11 · Printing
- [ ] Thermal 58 mm / 80 mm receipts
- [ ] Bengali + English printing, logo, reprint, test print
- [ ] Barcode/QR labels
- [ ] **Physical printer test — pending hardware**

## Phase 12 · Licensing
- [ ] Ed25519 signing/verification core
- [ ] Private License Generator app
- [ ] Offline activation UI, recovery flow

## Phase 13 · Backup & settings
- [ ] Manual/automatic/scheduled backup
- [ ] Validated restore with pre-restore backup
- [ ] Business, printer, invoice, tax, backup settings

## Phase 14–15 · Integration & QA
- [ ] Full module integration
- [ ] Unit, integration, regression, security, performance tests
- [ ] Reconciliation test suite

## Phase 16–18 · Packaging, CI/CD, verification
- [ ] PyInstaller self-contained build
- [ ] Inno Setup installer + uninstaller (data-preserving)
- [ ] GitHub Actions CI + Windows build + release pipelines
- [ ] Silent install / launch / uninstall verification on Windows runner
- [ ] **Clean physical Windows PC install test — pending**

## Phase 19–20 · Release & documentation
- [ ] User guide (Bangla), admin guide (private), technical docs
- [ ] Versioned release, checksums, release notes
- [ ] Final verification report
