Implement an inventory order-processing module in `original.ts`.
Export `processOrder(input, catalog)` to validate and price one order.
An order has a nonempty `id` and a nonempty `items` array of `{ sku, quantity }` rows.
Catalog values map each SKU to `{ price, stock }`; prices must be finite and positive, stock a nonnegative integer.
Reject malformed input, unknown SKUs, duplicate SKUs, and quantities that are not positive integers or exceed stock, using `Error` messages that identify the issue.
Apply a 10% item discount when the subtotal is at least 100, and a further 5% when it is at least 200; discounts are cumulative.
Tax is 8% of the discounted subtotal; round money to cents after each pricing stage.
Shipping is 0 for totals of at least 150 before tax, 5 for totals of at least 50, and 12 otherwise.
Return `{ id, items, subtotal, discount, tax, shipping, total }`, where `items` contains `{ sku, quantity, unitPrice, lineTotal }` rows.
Export `formatOrderReport(result)` as a deterministic multi-line text report showing the order ID, item rows, and all five monetary amounts to two decimals.
