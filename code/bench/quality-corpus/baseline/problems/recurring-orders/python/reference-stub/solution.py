import calendar
from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    recurring_id: int
    date: str
    total_cents: int


class OrderSystem:
    def __init__(self):
        self._plans = []

    def add_recurring(self, customer, unit_cents, quantity, start):
        if quantity < 1 or unit_cents < 0:
            raise ValueError("invalid order")
        year, month, day = map(int, start.split("-"))
        plan = {
            "id": len(self._plans) + 1,
            "start": (year, month, day),
            "total": unit_cents * quantity,
            "generated": 0,
            "active": True,
        }
        self._plans.append(plan)
        return plan["id"]

    def cancel(self, recurring_id):
        self._plans[recurring_id - 1]["active"] = False

    def orders_through(self, through):
        orders = []
        for plan in self._plans:
            while plan["active"]:
                date = self._date(plan)
                if date > through:
                    break
                orders.append(Order(plan["id"], date, plan["total"]))
                plan["generated"] += 1
        return sorted(orders, key=lambda o: (o.date, o.recurring_id))

    @staticmethod
    def _date(plan):
        year, month, day = plan["start"]
        year, month0 = divmod(year * 12 + month - 1 + plan["generated"], 12)
        day = min(day, calendar.monthrange(year, month0 + 1)[1])
        return f"{year:04d}-{month0 + 1:02d}-{day:02d}"
