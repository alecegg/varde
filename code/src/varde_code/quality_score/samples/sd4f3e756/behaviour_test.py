import importlib.util
import os
import unittest
from decimal import Decimal


MODULE_PATH = os.environ.get("SAMPLE_MODULE_PATH", "original.py")
SPEC = importlib.util.spec_from_file_location("original", MODULE_PATH)
original = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(original)


class LoanPricingTests(unittest.TestCase):
    def test_empty_input_and_blank_lines(self):
        result = original.price_loans("\n  \n")
        self.assertEqual(result["fees"], Decimal("0.00"))
        self.assertEqual(result["late_fines"], Decimal("0.00"))
        self.assertEqual(result["discount"], Decimal("0.00"))
        self.assertEqual(result["taxable"], Decimal("0.00"))
        self.assertEqual(result["tax"], Decimal("0.00"))
        self.assertEqual(result["total"], Decimal("0.00"))
        self.assertEqual(original.receipt("\n  \n"), "TOTAL $0.00 (tax $0.00)")

    def test_period_tiers_and_late_bands(self):
        result = original.price_loans("none,7,1\nnone,8,1\nnone,14,1\nnone,15,1\nnone,21,1")
        self.assertEqual(result["fees"], Decimal("9.50"))
        self.assertEqual(result["late_fines"], Decimal("9.50"))
        self.assertEqual(result["discount"], Decimal("0.00"))
        self.assertEqual(result["taxable"], Decimal("17.00"))
        self.assertEqual(result["tax"], Decimal("1.36"))
        self.assertEqual(result["total"], Decimal("20.36"))

    def test_quantity_membership_discount_and_receipt(self):
        result = original.price_loans("basic,8,2\nplus,7,1")
        self.assertEqual(result["fees"], Decimal("4.50"))
        self.assertEqual(result["late_fines"], Decimal("0.50"))
        self.assertEqual(result["discount"], Decimal("0.60"))
        self.assertEqual(result["taxable"], Decimal("2.40"))
        self.assertEqual(result["tax"], Decimal("0.19"))
        self.assertEqual(result["total"], Decimal("4.59"))
        report = original.receipt("\n basic, 8, 2 \n\nplus,7,1\n")
        self.assertIn("Line 2: fees $3.50, late $0.50, discount $0.40", report)
        self.assertIn("Line 4: fees $1.00, late $0.00, discount $0.20", report)
        self.assertTrue(report.endswith("TOTAL $4.59 (tax $0.19)"))

    def test_tax_free_cap_and_rounding(self):
        exempt = original.price_loans("none,7,2")
        self.assertEqual(exempt["taxable"], Decimal("0.00"))
        self.assertEqual(exempt["tax"], Decimal("0.00"))
        over = original.price_loans("none,7,3")
        self.assertEqual(over["taxable"], Decimal("1.00"))
        self.assertEqual(over["tax"], Decimal("0.08"))
        rounded = original.price_loans("plus,8,1")
        self.assertEqual(rounded["discount"], Decimal("0.40"))
        self.assertEqual(rounded["total"], Decimal("1.60"))

    def test_record_validation_reports_physical_line(self):
        cases = [
            ("none,7", "three fields"),
            ("gold,7,1", "membership"),
            ("none,0,1", "days"),
            ("none,22,1", "1-21"),
            ("none,7,0", "quantity"),
            ("none,7.0,1", "days"),
            ("none,7,-1", "quantity"),
        ]
        for record, expected in cases:
            with self.subTest(record=record):
                with self.assertRaisesRegex(ValueError, expected):
                    original.price_loans("\n  \n" + record)

    def test_receipt_propagates_validation(self):
        with self.assertRaisesRegex(ValueError, "line 2"):
            original.receipt("none,7,1\ninvalid")


if __name__ == "__main__":
    unittest.main()
