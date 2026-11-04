Build a subscription invoicing module in `original.ts` with no third-party dependencies.
Export `createInvoice(input)` and `renderInvoice(invoice)` as its public functions.
`input` has `customerId`, `period`, `plan`, `units`, `credits`, and `taxRate` fields.
Plans are `basic` ($20, includes 100 units), `plus` ($50, includes 500), and `max` ($100, includes 1500).
Each unit above the plan allowance costs $0.10; counts must be nonnegative integers.
Credits are nonnegative dollar amounts applied after usage charges, capped at the pre-credit subtotal.
Tax rate is a finite number from 0 through 1 and applies after credits; round each monetary result to cents.
Reject missing/blank customerId or period, unknown plans, invalid units, credits, or taxRate with `TypeError`.
`createInvoice` returns customerId, period, plan, base, includedUnits, units, overage, credits, taxable, tax, and total.
The report has lines `Invoice: <customerId>`, `Period: <period>`, `Plan: <plan>`, `Base: $0.00`, `Usage: <units> units ($0.00)`, `Credits: -$0.00`, `Tax: $0.00`, and `Total: $0.00` in that order, joined by newlines.
All amounts display exactly two decimal places; usage shows the original unit count and overage charge.
