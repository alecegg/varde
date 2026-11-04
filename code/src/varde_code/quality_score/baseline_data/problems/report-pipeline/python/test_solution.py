import unittest

from solution import render_report


class ReportPipelineTest(unittest.TestCase):
    def test_aggregates_by_key(self):
        text = "region,amount\nnorth,10\nsouth,5.5\nnorth,2.25\n"
        self.assertEqual(
            "north: 2 rows, total 12.25\n"
            "south: 1 rows, total 5.50\n"
            "TOTAL: 3 rows, total 17.75",
            render_report(text, "region", "amount"),
        )

    def test_sorts_by_total_then_key(self):
        report = render_report("k,v\nb,5\na,5\nc,7\n", "k", "v")
        self.assertEqual(
            ["c", "a", "b"], [line.split(":")[0] for line in report.split("\n")[:3]]
        )

    def test_quoted_field_with_comma(self):
        report = render_report('name,v\n"Smith, Jo",4\n', "name", "v")
        self.assertTrue(report.startswith("Smith, Jo: 1 rows, total 4.00"))

    def test_blank_lines_ignored(self):
        report = render_report("k,v\n\na,1\n\n\na,2\n\n", "k", "v")
        self.assertEqual("a: 2 rows, total 3.00\nTOTAL: 2 rows, total 3.00", report)

    def test_missing_column_is_an_error(self):
        with self.assertRaises(ValueError):
            render_report("k,v\na,1\n", "k", "amount")
        with self.assertRaises(ValueError):
            render_report("k,v\na,1\n", "name", "v")

    def test_non_numeric_value_is_an_error(self):
        with self.assertRaises(ValueError):
            render_report("k,v\na,abc\n", "k", "v")

    def test_other_columns_and_order_ignored(self):
        report = render_report("id,amount,team\n1,3,x\n2,4,x\n", "team", "amount")
        self.assertEqual("x: 2 rows, total 7.00\nTOTAL: 2 rows, total 7.00", report)

    def test_header_only_has_no_data(self):
        self.assertEqual("No data", render_report("k,v\n", "k", "v"))


if __name__ == "__main__":
    unittest.main()
