Implement an inventory and order-processing module in `original.py`.
Expose `process_order(order)` returning a dictionary with `items`, `subtotal`, `discount`, `tax`, `shipping`, `total`, and `report`.
`order` must contain `customer`, `items`, and optional `discount_code`; each item has `sku`, `name`, `price`, and `quantity`.
Require nonblank customer/SKU/name, positive numeric prices, positive integer quantities, and a nonempty item list; reject malformed input with `ValueError`.
The item result preserves SKU, name, price, quantity, and line total, in input order.
Subtotal is the sum of line totals; apply 10% off at subtotal >= 100, otherwise 5% off at subtotal >= 50, else no automatic discount.
Discount code `SAVE5` adds 5% off; total discount is capped at 20% of subtotal. Unknown nonempty codes raise `ValueError`.
Tax is 8% of subtotal less discount, rounded to two decimal places using standard Python rounding.
Shipping is $0 for discounted merchandise of at least $75, $5 for subtotal at least $50, and $10 otherwise.
Return monetary values rounded to two decimals and a deterministic multiline report showing customer, item lines, subtotal, discount, tax, shipping, and total.
