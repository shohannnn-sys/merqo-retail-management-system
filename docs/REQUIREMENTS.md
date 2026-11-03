# Requirements Analysis — Retvia

## 1. Module dependency map

```
core(money,quantity,validation)
        └── data(db,migrations,repositories)
                ├── settings, audit, numbering
                ├── catalog(products,categories,units,barcodes)
                │        └── inventory(movements,adjustments,valuation)
                │                ├── sales ── sale_payments ── cash_register
                │                ├── purchases ── purchase_payments
                │                └── returns(sales,purchase)
                ├── parties(customers,suppliers) ── payments ── ledgers
                ├── expenses
                └── finance(COGS,profit,reconciliation)
                        └── reports ── exports(PDF,XLSX,CSV)
                                └── printing(receipts,labels)
licensing (independent; gates application entry)
backup (depends on data + settings + assets)
```

Build order follows this map: nothing is built before its dependencies have a
stable, tested contract.

## 2. Business workflows (acceptance-level)

**Sale:** scan/search → cart → discounts → customer → payment(s) → validate stock
policy → allocate invoice number → persist sale + items + payments + stock
movements + due + cash movement + audit **in one transaction** → print receipt.

**Purchase:** supplier → items + cost → payment(s) → persist purchase + items +
payments + stock movements (MAC recompute) + payable + cash movement + audit →
print purchase record.

**Sales return:** locate invoice → validate returnable qty (cumulative) → choose
condition per line → restock or write off → refund/adjust due → stock + financial
+ audit entries in one transaction.

**Due collection:** select customer → optionally select invoice → amount + method
→ allocate → update due → cash movement if cash → receipt → audit.

**Backup/restore:** snapshot via `VACUUM INTO` → package + checksum → store;
restore validates → pre-restore backup → swap → integrity check → recovery log.

**Activation:** enter license key/file → verify Ed25519 signature → verify product
and business identity → optional tolerant hardware check → store activation →
re-verify on every launch, fully offline.

## 3. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | Floating-point money errors | High if unmanaged | Critical | Integer poisha everywhere; single rounding policy; reconciliation tests |
| R-02 | Bengali text breaks in print/PDF | High | Critical | Qt shaping + bundled Noto Sans Bengali; raster fallback; CI geometry checks |
| R-03 | Partial writes corrupt stock/ledger | Medium | Critical | Single `BEGIN IMMEDIATE` transaction per business operation; rollback tests |
| R-04 | Duplicate invoice numbers under concurrency | Medium | High | Atomic sequence table + UNIQUE index; concurrency test |
| R-05 | Data loss on restore/update | Medium | Critical | Pre-restore backup, staged swap, integrity check, migration backups |
| R-06 | License locks out legitimate customer | Medium | High | Optional tolerant binding + owner-issued re-activation |
| R-07 | Private signing key leaks | Low | Critical | Key only in private generator, encrypted at rest, gitignored, CI secret |
| R-08 | Cannot verify on real Windows/printer | **Certain in this environment** | High | CI Windows runner evidence; explicit pending status disclosed |
| R-09 | Large dataset slows POS/reports | Medium | Medium | Indexes, pagination, prepared statements, performance tests with synthetic data |
| R-10 | Name trademark conflict | Medium | Medium | Screened candidates; formal clearance flagged as owner action |

## 4. Global acceptance criteria

1. Every action performs real validation, business logic, DB mutation and error
   handling — no placeholder buttons, no static dashboard numbers, no dummy reports.
2. All money is integer poisha; all quantity is integer milli-units.
3. Every stock change has a movement row; every financial change has an audit row.
4. Every report reconciles with the ledgers and with the dashboard for the same filter.
5. All data survives restart, backup/restore, update and uninstall.
6. No network access is required for any business function.
7. No secret, private key or real business data is committed.
8. Nothing is reported as verified unless a test or CI run actually proved it.
