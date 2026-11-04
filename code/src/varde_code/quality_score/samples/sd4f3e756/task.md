Implement a library loan fines module with public functions `price_loans(text)` and `receipt(text)`.
Input is comma-separated `membership,days,quantity`, one record per nonblank line; surrounding whitespace is ignored.
Membership is exactly `none`, `basic`, or `plus`; days and quantity must be base-10 positive integers, with days 1-21 and quantity at least 1.
Each malformed record raises `ValueError` whose message identifies its 1-based physical line number; empty/whitespace-only input is valid.
For each item, the loan-period fee is $1.00 for 1-7 days, $1.75 for 8-14 days, and $2.50 for 15-21 days; multiply by quantity.
Late fine per item is $0 through day 7, $0.25 for each day 8-14, and $0.50 for each day 15-21 (the bands are marginal); multiply by quantity.
`basic` discounts 10% and `plus` 20% from the combined loan fees and late fines; `none` has no discount. Round each record's discounted amount to cents, half up.
Sum record amounts, then tax 8% only on the amount above the $2.00 tax-free fee cap; round tax to cents, half up. No negative amounts occur.
`price_loans(text)` returns a dictionary with Decimal values under `fees`, `late_fines`, `discount`, `taxable`, `tax`, and `total`; `discount` is positive and total is after tax.
`receipt(text)` returns a text report with rows `Line N: fees $X.XX, late $X.XX, discount $X.XX` per nonblank record in input order, then `TOTAL $X.XX (tax $X.XX)`; empty input returns `TOTAL $0.00 (tax $0.00)`.
Receipt amounts use two decimal places, rows use physical input line numbers, and any input validation error propagates from `price_loans`.
