Implement an inventory order module in Go, package `original`.
Expose `ValidateOrder(lines []string) error`; accept 1-20 rows in `SKU,quantity` form.
SKUs are `PEN`, `BOOK`, and `BAG`; quantities are decimal integers from 1 through 99.
Reject malformed rows, unknown SKUs, duplicate SKUs, and empty orders with an error.
Expose `ProcessOrder(lines []string) (string, error)`; it must validate before pricing.
Unit prices in cents are PEN 125, BOOK 850, and BAG 2400.
Discount the merchandise subtotal by 10% at $50 or more, otherwise 5% at $25 or more.
Apply discount before tax; tax is 8% of the discounted subtotal, rounded to nearest cent.
Shipping is $0 below $25 after discount, $4.95 from $25 through $74.99, and $9.95 at $75 or more.
The report lists each input item in input order as `SKU x quantity: $amount`, then Subtotal, Discount, Tax, Shipping, and Total, each as dollars with two decimals.
