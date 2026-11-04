import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Order:
    recurring_id: int
    date: str
    total_cents: int


@dataclass
class _Plan:
    total_cents: int
    start: date
    generated: int = 0  # monthly occurrences already returned
    cancelled: bool = False

    def occurrence(self, n: int) -> date:
        """The n-th (0-based) occurrence.

        Always derived from the original start day, so clamping in a short
        month (Jan 31 -> Feb 29) does not drag later months down to that day.
        """
        months = self.start.month - 1 + n
        year = self.start.year + months // 12
        month = months % 12 + 1
        day = min(self.start.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)


class OrderSystem:
    """Monthly recurring orders: add plans, cancel them, ask what is due."""

    def __init__(self) -> None:
        self._plans: dict[int, _Plan] = {}
        self._next_id = 1

    def add_recurring(
        self, customer: str, unit_cents: int, quantity: int, start: str
    ) -> int:
        # `customer` is accepted for API compatibility but not used by scheduling.
        if quantity < 1:
            raise ValueError(f"quantity must be at least 1, got {quantity}")
        if unit_cents < 0:
            raise ValueError(f"unit_cents must not be negative, got {unit_cents}")

        recurring_id = self._next_id
        self._next_id += 1
        self._plans[recurring_id] = _Plan(
            total_cents=unit_cents * quantity,
            start=date.fromisoformat(start),
        )
        return recurring_id

    def cancel(self, recurring_id: int) -> None:
        # Unknown ids are ignored: the postcondition (no future orders) already holds.
        plan = self._plans.get(recurring_id)
        if plan is not None:
            plan.cancelled = True

    def orders_through(self, through: str) -> list[Order]:
        limit = date.fromisoformat(through)
        orders: list[Order] = []
        for recurring_id, plan in self._plans.items():
            orders.extend(self._due_orders(recurring_id, plan, limit))
        # Plans are visited in id order and the sort is stable, so ties keep id order.
        orders.sort(key=lambda order: (order.date, order.recurring_id))
        return orders

    @staticmethod
    def _due_orders(recurring_id: int, plan: _Plan, limit: date) -> list[Order]:
        """Emit each not-yet-returned order up to `limit`, marking it generated."""
        orders: list[Order] = []
        if plan.cancelled:
            return orders
        while (due := plan.occurrence(plan.generated)) <= limit:
            orders.append(Order(recurring_id, due.isoformat(), plan.total_cents))
            plan.generated += 1
        return orders
