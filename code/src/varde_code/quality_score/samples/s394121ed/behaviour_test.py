import importlib.util
import os
import unittest


MODULE_PATH = os.environ.get("SAMPLE_MODULE_PATH", "original.py")
_spec = importlib.util.spec_from_file_location("original", MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError("Cannot load module at " + MODULE_PATH)
original = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(original)


def order(price=20, quantity=1, code=None):
    value = {
        "customer": "Ari",
        "items": [{"sku": "A1", "name": "Widget", "price": price, "quantity": quantity}],
    }
    if code is not None:
        value["discount_code"] = code
    return value


class OrderTests(unittest.TestCase):
    def test_basic_order_fields_and_report(self):
        result = original.process_order(order())
        self.assertEqual(result["items"][0]["sku"], "A1")
        self.assertEqual(result["items"][0]["name"], "Widget")
        self.assertEqual(result["items"][0]["price"], 20.0)
        self.assertEqual(result["items"][0]["quantity"], 1)
        self.assertEqual(result["items"][0]["line_total"], 20.0)
        self.assertEqual(result["subtotal"], 20.0)
        self.assertEqual(result["discount"], 0.0)
        self.assertEqual(result["tax"], 1.6)
        self.assertEqual(result["shipping"], 10.0)
        self.assertEqual(result["total"], 31.6)
        self.assertEqual(result["report"].splitlines()[0], "Customer: Ari")
        self.assertIn("A1 | Widget | 1 x $20.00 = $20.00", result["report"])
        self.assertTrue(result["report"].endswith("Total: $31.60"))

    def test_discount_thresholds_and_shipping(self):
        mid = original.process_order(order(50))
        self.assertEqual(mid["discount"], 2.5)
        self.assertEqual(mid["shipping"], 5.0)
        high = original.process_order(order(100))
        self.assertEqual(high["discount"], 10.0)
        self.assertEqual(high["shipping"], 0.0)
        self.assertEqual(high["tax"], 7.2)
        self.assertEqual(high["total"], 97.2)

    def test_code_is_additive_and_discount_is_capped(self):
        result = original.process_order(order(100, code="SAVE5"))
        self.assertEqual(result["discount"], 15.0)
        self.assertEqual(result["tax"], 6.8)
        capped = original.process_order(order(1000, code="SAVE5"))
        self.assertEqual(capped["discount"], 150.0)
        self.assertEqual(capped["shipping"], 0.0)

    def test_multiple_lines_preserve_order(self):
        data = order()
        data["items"].append({"sku": "B2", "name": "Cable", "price": 3.25, "quantity": 2})
        result = original.process_order(data)
        self.assertEqual([x["sku"] for x in result["items"]], ["A1", "B2"])
        self.assertEqual(result["subtotal"], 26.5)
        self.assertEqual(result["items"][1]["line_total"], 6.5)

    def test_invalid_orders_raise_value_error(self):
        invalid = [
            {},
            {"customer": "Ari", "items": []},
            {"customer": " ", "items": [{"sku": "A", "name": "X", "price": 1, "quantity": 1}]},
            {"customer": "Ari", "items": [{"sku": "", "name": "X", "price": 1, "quantity": 1}]},
            {"customer": "Ari", "items": [{"sku": "A", "name": " ", "price": 1, "quantity": 1}]},
            {"customer": "Ari", "items": [{"sku": "A", "name": "X", "price": 0, "quantity": 1}]},
            {"customer": "Ari", "items": [{"sku": "A", "name": "X", "price": -1, "quantity": 1}]},
            {"customer": "Ari", "items": [{"sku": "A", "name": "X", "price": 1, "quantity": 0}]},
            {"customer": "Ari", "items": [{"sku": "A", "name": "X", "price": 1, "quantity": True}]},
            order(10, code="UNKNOWN"),
            None,
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                original.process_order(value)

    def test_rounding_and_optional_code(self):
        result = original.process_order(order(1.005))
        self.assertEqual(result["items"][0]["price"], 1.0)
        self.assertEqual(original.process_order(order(20))["report"].count("Customer:"), 1)


if __name__ == "__main__":
    unittest.main()
