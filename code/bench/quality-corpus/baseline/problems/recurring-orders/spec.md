# recurring-orders behaviour spec

Dates are ISO strings (`YYYY-MM-DD`). Money is integer cents. `add_recurring(customer, unit_cents, quantity, start)` returns an integer id (1, 2, ...). `orders_through(date)` returns the orders not yet generated whose date is on or before `date`. `cancel(id)` stops future orders.

1. A plan creates its first order on the start date, with total = unit_cents * quantity.
2. Orders then repeat monthly: start 2024-01-15 through 2024-03-20 gives 01-15, 02-15, 03-15.
3. The day is clamped to the month length but keeps the original day: start 2024-01-31 gives 01-31, 02-29, 03-31 (2024 is a leap year).
4. An order is generated once: a later call returns only orders not returned before.
5. After `cancel(id)` no more orders are generated for that plan; earlier orders are unaffected.
6. A plan whose start is after the requested date generates nothing.
7. quantity < 1 or unit_cents < 0 is an error.
8. Orders from several plans are returned sorted by date, then by plan id.
