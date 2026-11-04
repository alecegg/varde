Implement an inventory and order-processing module in `Original`.
Inventory rows use `sku|name|unitPrice|stock|group`; order rows use `sku|quantity`.
Rows are newline-separated; blank rows are ignored and surrounding whitespace is trimmed.
Expose `validate(String inventory, String order)`, `process(String inventory, String order)`, and `report(String inventory, String order)` as public static methods.
`validate` returns true only when every row is well formed, SKUs are unique, values are valid, and each ordered SKU exists with sufficient stock; otherwise false.
Prices must be nonnegative decimal amounts with at most two fractional digits; stock and quantity must be positive whole numbers.
Group `A` gets a 5% discount on each matching line amount; other groups get no group discount. Round each monetary step to cents, half up.
The 10% order discount applies to the subtotal after group discounts. Tax is 8.25% and shipping tier are both computed on the amount after the order discount.
Shipping is $8.00 below $50.00, $5.00 from $50.00 through $99.99, and free at $100.00 or more.
`process` returns `Subtotal=...; Discount=...; Tax=...; Shipping=...; Total=...` with two decimal places, or `INVALID` for invalid input.
`report` returns the same values on separate labeled lines; its Subtotal is pre-order-discount and Discount is the 10% order discount.
