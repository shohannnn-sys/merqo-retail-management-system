# Retvia — by MERQO

**সম্পূর্ণ অফলাইন Windows POS, ইনভেন্টরি ও বিজনেস ম্যানেজমেন্ট সিস্টেম**

Retvia is a fully offline, lifetime-licensed Windows desktop application for
Bangladeshi retail businesses — grocery shops, superstores, departmental stores,
wholesale and retail traders. It combines POS, inventory, purchasing, customer
due, supplier payable, expenses, cash register, financial reporting, thermal
printing, backup/restore and offline license activation in one product.

- **Brand:** MERQO
- **Product:** Retvia
- **Founder:** Shohan Khan
- **Contact:** merqoonline@gmail.com
- **Platform:** Windows 10 / 11 (64-bit)
- **Internet:** not required for any business operation
- **License:** one-time payment, lifetime usage per business

---

## Key capabilities

| Area | Modules |
|---|---|
| Sales | POS, barcode scan, cart, discounts, split payment, invoices, receipts |
| Inventory | stock ledger, adjustments, damage/loss/expiry, valuation, low-stock alerts |
| Purchasing | purchase entry, purchase returns, supplier payable |
| Parties | customers, suppliers, ledgers, statements, due collection |
| Finance | expenses, cash register & shifts, COGS, gross/net profit, reconciliation |
| Reports | 34 report types, PDF / Excel / CSV export with correct Bengali |
| Printing | 58 mm / 80 mm thermal receipts, barcode labels, test print |
| Data | automatic & manual backup, validated restore, import/export |
| Licensing | Ed25519-signed offline activation, hardware-change recovery |

## Technology

Python 3.12 · PySide6 (Qt 6) · SQLite (WAL) · integer-poisha financial engine ·
Ed25519 licensing · PyInstaller + Inno Setup · GitHub Actions.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical justification.

## Repository guide

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, layers, ER design, policies |
| [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) | Live progress snapshot |
| [MASTER_CHECKLIST.md](MASTER_CHECKLIST.md) | Requirement-by-requirement checklist |
| [DECISIONS.md](DECISIONS.md) | Architecture decision records |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Open defects and limitations |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting and security model |
| [docs/](docs/) | Requirements, financial policy, licensing, user guide |

## Building from source

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt -r requirements-dev.txt
pytest                            # business-core test suite
python -m retvia                  # run the application
```

Windows packaging (self-contained EXE + installer) is performed by the GitHub
Actions Windows workflow; see [docs/BUILD.md](docs/BUILD.md).

## License

Proprietary — © 2026 MERQO. See [LICENSE](LICENSE).
Third-party components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

> **Status:** this project is under active development. It is **not** yet a
> verified commercial release. See DEVELOPMENT_STATUS.md for exactly what is
> implemented, tested and still pending.
