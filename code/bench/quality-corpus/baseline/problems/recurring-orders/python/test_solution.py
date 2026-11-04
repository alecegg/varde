import unittest

from solution import OrderSystem


def dates(orders):
    return [o.date for o in orders]


class RecurringOrdersTest(unittest.TestCase):
    def setUp(self):
        self.system = OrderSystem()

    def test_first_order_on_start_date(self):
        plan = self.system.add_recurring("ann", 1000, 2, "2024-01-15")
        orders = self.system.orders_through("2024-01-15")
        self.assertEqual(
            [(plan, "2024-01-15", 2000)],
            [(o.recurring_id, o.date, o.total_cents) for o in orders],
        )

    def test_repeats_monthly(self):
        self.system.add_recurring("ann", 500, 1, "2024-01-15")
        self.assertEqual(
            ["2024-01-15", "2024-02-15", "2024-03-15"],
            dates(self.system.orders_through("2024-03-20")),
        )

    def test_day_clamped_to_month_length(self):
        self.system.add_recurring("ann", 500, 1, "2024-01-31")
        self.assertEqual(
            ["2024-01-31", "2024-02-29", "2024-03-31"],
            dates(self.system.orders_through("2024-03-31")),
        )

    def test_orders_are_generated_once(self):
        self.system.add_recurring("ann", 500, 1, "2024-01-15")
        self.assertEqual(
            ["2024-01-15"], dates(self.system.orders_through("2024-01-31"))
        )
        self.assertEqual(
            ["2024-02-15"], dates(self.system.orders_through("2024-02-20"))
        )
        self.assertEqual([], dates(self.system.orders_through("2024-02-20")))

    def test_cancel_stops_future_orders(self):
        plan = self.system.add_recurring("ann", 500, 1, "2024-01-15")
        self.assertEqual(1, len(self.system.orders_through("2024-01-20")))
        self.system.cancel(plan)
        self.assertEqual([], self.system.orders_through("2024-06-01"))

    def test_start_after_date_generates_nothing(self):
        self.system.add_recurring("ann", 500, 1, "2024-05-01")
        self.assertEqual([], self.system.orders_through("2024-04-30"))

    def test_invalid_plan_rejected(self):
        with self.assertRaises(ValueError):
            self.system.add_recurring("ann", 500, 0, "2024-01-01")
        with self.assertRaises(ValueError):
            self.system.add_recurring("ann", -1, 1, "2024-01-01")

    def test_orders_sorted_by_date_then_plan(self):
        self.system.add_recurring("a", 100, 1, "2024-01-20")
        self.system.add_recurring("b", 100, 1, "2024-01-10")
        self.system.add_recurring("c", 100, 1, "2024-01-10")
        orders = self.system.orders_through("2024-01-31")
        self.assertEqual([2, 3, 1], [o.recurring_id for o in orders])


if __name__ == "__main__":
    unittest.main()
