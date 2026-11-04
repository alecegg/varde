import unittest

from solution import add


class AdderTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(1, 2), 3)

    def test_negative(self):
        self.assertEqual(add(-1, 1), 0)
