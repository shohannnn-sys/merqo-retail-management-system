# Financial Calculation Policy — Retvia

This document is normative. Every service and report MUST follow it. All amounts
are **integer poisha** (1 BDT = 100 poisha). All quantities are **integer
milli-units** (1 unit = 1000 milli-units). No floating point is used for money or
quantity anywhere in the codebase.

## 1. Rounding

- Single policy: **round half up** (away from zero on .5), applied at defined
  boundaries only.
- Implemented once in `retvia/core/money.py::round_div`.
- Boundaries where rounding occurs: line discount, invoice-discount allocation,
  tax per line, moving-average cost recompute, unit-price derivation from a total.
- Never round twice. Intermediate values stay exact integers.

## 2. Sale calculation order

```
line_gross      = unit_price × quantity                 (exact, ÷1000 for qty)
line_discount   = percentage of line_gross  OR  fixed amount
line_net        = line_gross − line_discount
invoice_gross   = Σ line_gross
invoice_discount= percentage of Σ line_net  OR  fixed amount
allocation      = largest-remainder distribution of invoice_discount over lines
line_revenue    = line_net − allocated_invoice_discount
taxable_base    = line_revenue
line_tax        = taxable_base × rate  (only if tax enabled, exclusive)
net_sales       = Σ line_revenue
grand_total     = net_sales + Σ line_tax
paid            = Σ sale_payments
due             = grand_total − paid
```

**Largest-remainder allocation** guarantees `Σ allocated == invoice_discount`
exactly, so per-product profit reports always reconcile to the invoice total.

## 3. Costing — Moving Average Cost (MAC)

On receipt (purchase or restocking return):

```
new_total_qty   = old_qty + received_qty
new_total_value = old_qty × old_mac + received_qty × received_cost
new_mac         = round_half_up(new_total_value / new_total_qty)
```

- Opening stock establishes the initial MAC.
- `products.avg_cost` is the current MAC in poisha per whole unit.
- Sale COGS is snapshotted into `sale_items.unit_cost` at sale time; later MAC
  changes never restate historical profit.

## 4. Profit definitions

```
gross_sales      = Σ line_gross for non-cancelled sales
sales_discounts  = Σ line_discount + Σ invoice_discount
sales_returns    = Σ returned line_revenue (restocked or not)
net_sales        = gross_sales − sales_discounts − sales_returns
cogs             = Σ (sold_qty × snapshot_cost) − Σ (restocked_return_qty × snapshot_cost)
gross_profit     = net_sales − cogs
operating_expense= Σ expenses in period
write_offs       = Σ value of damage/loss/expiry adjustments + non-restockable return cost
net_profit       = gross_profit − operating_expense − write_offs
```

- Tax collected is a **liability**, excluded from revenue and profit.
- Estimated profit (dashboard, before expenses are entered) is labelled
  `estimated` and equals gross profit; it is never presented as net profit.

## 5. Returns

**Sales return**
- Returnable qty = sold qty − cumulative returned qty (enforced per sale item).
- Revenue reversed at the original line's effective net unit revenue.
- If condition = `restock`: stock increases at the **original snapshot cost**,
  COGS reversed by the same value, MAC recomputed.
- If condition = `damaged` / `no_restock`: no stock increase; original COGS stays
  and is reported as a write-off.
- Refund settles first against the invoice due; any excess becomes cash out or
  customer advance, per the operator's choice.

**Purchase return**
- Returnable qty = purchased qty − cumulative returned qty.
- Stock decreases at the **original purchase unit cost**; supplier payable
  decreases by the same value; MAC recomputed on the remaining stock.
- If the remaining stock value would go negative, the removal is capped at the
  current stock value and the difference is booked to inventory adjustment.

## 6. Party balances

```
customer_due = opening_due + Σ credit_sale_due − Σ collections − Σ return_credits
supplier_payable = opening_payable + Σ purchase_due − Σ payments − Σ return_debits
```

- Negative customer due = **advance received** (liability), shown as such.
- Payments allocate to specific invoices when given, otherwise oldest-first.
- Every allocation is a row; balances are always derivable from the ledger.

## 7. Cash register

```
expected_close = opening_cash
               + cash sales + cash collections + cash in
               − cash refunds − cash expenses − supplier cash payments − cash out
difference     = actual_close − expected_close
```

Only movements whose payment method is flagged `is_cash` affect the drawer.
A session must be open to record cash movements; closing writes a
`cash_sessions` summary that is immutable afterwards.

## 8. Reconciliation invariants (enforced by automated tests)

1. `Σ stock_movements.qty_delta` per product == `products.stock_qty`.
2. `Σ stock_movements.value_delta` per product == current inventory value.
3. `Σ sale_payments + due` == `sales.grand_total` for every sale.
4. `Σ customer ledger entries` == `customers.current_due`.
5. `Σ supplier ledger entries` == `suppliers.current_payable`.
6. `Σ allocated invoice discount` == `sales.invoice_discount`.
7. Dashboard totals == report totals for the same filter.
8. `Σ cash_movements` in a session == `expected_close − opening_cash`.
