# Master Checklist — Retvia

Legend: `[x]` done & verified locally · `[~]` implemented, verification runs in CI or needs hardware · `[ ]` not started

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
- [x] Project scaffolding, dependency pinning
- [x] Application shell, sidebar navigation, design system (single light theme)
- [x] Database connection, WAL, FK, forward-only migration framework
- [x] Rotating local logging, global exception hook, audit service
- [x] Frozen-bundle resource resolution (`retvia/paths.py`)

## Phase 4 · Core database & business foundation
- [x] Full schema + migrations (v1 → v3, 39 tables)
- [x] Nested ACID transactions (`BEGIN IMMEDIATE` + SAVEPOINT)
- [x] Money/quantity core in integer minor units, single rounding boundary
- [x] Calculation engine, largest-remainder allocation, invoice numbering
- [x] Checksummed backup framework

## Phase 5 · Product & inventory
- [x] Products CRUD, archive, duplicate prevention, history protection
- [x] Categories, units, multiple barcodes, auto barcode generation
- [x] Stock movements, adjustments, moving-average valuation, alerts
- [x] CSV / XLSX export of the stock report
- [ ] Bulk product **import** (CSV wizard) — deferred, see PENDING_TASKS

## Phase 6 · Sales & POS
- [x] POS UI, live search, barcode scan, cart, keyboard shortcuts
- [x] Item/invoice discounts (% and fixed), tax, discount caps
- [x] Split payments across methods, unique sequential invoices
- [x] Atomic sale transaction: stock + due + cash + transaction row + audit

## Phase 7 · Customer & supplier
- [x] Customer CRUD, ledger, running balance, due collection, receipt print
- [x] Supplier CRUD, ledger, statement, payments
- [x] Payment allocation to specific invoices; immutable original due

## Phase 8 · Purchase & returns
- [x] Purchase entry + stock increase + MAC update
- [x] Purchase payment, purchase return with cumulative quantity validation
- [x] Sales return with restock / damaged / no-restock handling and write-off

## Phase 9 · Financial management
- [x] Expenses, categories, voucher numbering, reversal-not-delete
- [x] Cash register, shifts, cash in/out, expected-vs-counted difference
- [x] COGS, gross/net profit, receivable/payable, 8 reconciliation invariants

## Phase 10 · Reporting & export
- [x] All 34 report types, verified on populated and empty databases
- [x] Dashboard analytics from live data (12 KPIs, 6 charts, 3 tables)
- [x] XLSX with real number formats, CSV with UTF-8 BOM
- [~] PDF with embedded Bengali font — implemented, renders in CI

## Phase 11 · Printing
- [x] Thermal 58 mm / 80 mm receipt geometry, Bangla raster mode
- [x] Business-only branding on receipts (no MERQO/Retvia on customer paper)
- [x] Reprint with "পুনরায় মুদ্রিত কপি" label, PDF save
- [x] Barcode (Code128) / QR generation and label sheet printing
- [ ] **Physical printer test — pending hardware**

## Phase 12 · Licensing
- [x] Ed25519 signing/verification core, canonical-JSON payload
- [x] Owner License Generator (private source, 21 local tests)
- [x] Offline activation UI, re-verification on every launch
- [x] Hardware fingerprint with tolerant matching and recovery flow

## Phase 13 · Backup, users & settings
- [x] Manual + automatic + on-exit backup, retention pruning
- [x] Validated restore with mandatory pre-restore safety backup
- [x] Business profile, printer, invoice, tax, discount, backup settings
- [x] Local users, scrypt hashing, three roles, lockout, login history
- [x] Audit trail viewer with date/actor/action filters

## Phase 14–15 · Integration & QA
- [x] Full module integration through one service container
- [x] 354 local tests + 21 owner-tool tests
- [x] Reconciliation test suite (stock, parties, invoices, cash)
- [x] Security tests: forged/tampered licences, lockout, secret scanning in CI
- [x] Lint, format and static typing clean

## Phase 16–18 · Packaging, CI/CD, verification
- [x] PyInstaller one-folder spec, runtime hook, version resource, icon
- [x] Inno Setup installer + data-preserving uninstaller
- [x] CI + Windows build + release + private owner-tool workflows
- [~] Silent install / launch / all-screens / uninstall verification — runs in CI
- [ ] **Clean physical Windows PC install test — pending**

## Phase 19–20 · Release & documentation
- [x] Bangla user guide (Markdown + offline HTML with embedded font)
- [x] Private owner/admin guide (git-ignored)
- [x] Technical docs: BUILD, LICENSING, OWNER_TOOL_SETUP, THIRD_PARTY_NOTICES
- [x] Continuity docs refreshed
- [ ] Versioned public release with checksums — after CI verification
- [ ] Final verification report — after CI verification
