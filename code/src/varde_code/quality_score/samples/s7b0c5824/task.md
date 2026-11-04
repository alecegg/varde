Implement a C# order module in the global namespace as `public static class Original`.
`Process(string input)` parses one item per nonblank line, with fields `sku|quantity|unitPrice`.
Trim fields; SKU must be nonempty and unique (case-insensitive), quantity must be an integer from 1 through 100, and unit price a decimal from 0 through 10000.
Reject null, empty/whitespace input, malformed rows, duplicate SKUs, invalid numbers, and out-of-range values with `ArgumentException`.
Return a public `OrderResult` containing item rows, subtotal, discount, tax, shipping, and total; item rows contain SKU, quantity, unit price, and line total.
Calculate line totals and all monetary amounts rounded to two decimals using midpoint-away-from-zero.
Apply one order discount: 10% when pre-discount subtotal is at least 100, 5% when at least 50, otherwise 0%.
Tax is 8.25% of the discounted subtotal. Shipping is 8.95 below 25, 5.95 from 25 through below 75, and free at 75 or more (based on discounted subtotal).
`Report(OrderResult order)` returns lines `Order`, `Items: N`, `Subtotal: $0.00`, `Discount: $0.00`, `Tax: $0.00`, `Shipping: $0.00`, and `Total: $0.00`, in that order, using invariant two-decimal currency values.
Throw `ArgumentNullException` when `Report` receives null; preserve input row order in the returned items.
