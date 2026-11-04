Implement an event ticket booking module in `Original`, with one booking request per nonblank input line.
`Original.ProcessLine(string)` accepts `name|class|quantity`; trim all fields and match classes case-insensitively: Standard, Premium, VIP.
Reject missing/extra fields, blank names, unsupported classes, non-integer quantities, and quantities outside 1-20.
For invalid requests, return exactly `REJECTED: <reason>`; reasons are `format`, `name`, `class`, or `quantity` as applicable.
`Original.SeatPrice(string)` returns 50.00, 90.00, or 140.00 for Standard, Premium, or VIP, and 0.00 for an unknown class.
`Original.CalculateTotal(string, int)` returns the final amount using the same class prices and quantity rules; return 0.00 for invalid inputs.
Apply a 10% discount to ticket subtotal when quantity is at least 6; otherwise apply no discount.
Add a booking fee based on the discounted subtotal: $5.00 through $100.00, $10.00 through $500.00, and $20.00 above $500.00.
Apply 8% tax to discounted subtotal plus booking fee; round currency to two decimals using midpoint-away-from-zero.
For valid input, `ProcessLine` returns these lines: `CONFIRMED: <name>`, `Tickets: <quantity> x <class>`, `Subtotal: $<0.00>`, `Discount: $<0.00>`, `Booking fee: $<0.00>`, `Tax: $<0.00>`, `Total: $<0.00>`.
`Original.ProcessAll(string)` processes nonblank lines in order, omits blank lines, and joins each line's result block with one newline.
