# recurring-orders API

Solution file: `solution.py` / `solution.ts` / `Solution.cs`. Errors: Python `ValueError`, TypeScript `Error`, C# any exception.

- Python: `class OrderSystem` with `add_recurring(customer: str, unit_cents: int, quantity: int, start: str) -> int`, `cancel(recurring_id: int) -> None`, `orders_through(through: str) -> list[Order]`; `Order` has attributes `recurring_id`, `date`, `total_cents`.
- TypeScript: `export class OrderSystem` with `addRecurring(customer, unitCents, quantity, start): number`, `cancel(id): void`, `ordersThrough(through): Order[]`; `Order` is `{recurringId, date, totalCents}`.
- C#: `class OrderSystem` with `int AddRecurring(string customer, int unitCents, int quantity, string start)`, `void Cancel(int id)`, `List<Order> OrdersThrough(string through)`; `record Order(int RecurringId, string Date, int TotalCents)`.
