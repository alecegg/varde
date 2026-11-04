"""Shared behaviour test for the sales summary item: bank, invalid, and large cases."""

import random
from decimal import ROUND_HALF_UP, Decimal

import solution


class MyInt(int):
    """A quantity given as an int subclass, which is out of domain."""


class MyFloat(float):
    """A price given as a float subclass, which is out of domain."""


CASES = [
    (
        [{"product": "Tea", "quantity": 2, "unit_price": 3}],
        [{"product": "Tea", "quantity": 2, "revenue": 6}],
    ),
    ([], []),
    (
        [
            {"product": "Pen", "quantity": 3, "unit_price": 1.2},
            {"product": "Book", "quantity": 1, "unit_price": 8},
        ],
        [
            {"product": "Book", "quantity": 1, "revenue": 8},
            {"product": "Pen", "quantity": 3, "revenue": 3.6},
        ],
    ),
    (
        [
            {"product": "Tea", "quantity": 1, "unit_price": 2},
            {"product": "Tea", "quantity": 4, "unit_price": 2.5},
        ],
        [{"product": "Tea", "quantity": 5, "revenue": 12}],
    ),
    (
        [{"product": "A", "quantity": 1, "unit_price": 0}],
        [{"product": "A", "quantity": 1, "revenue": 0}],
    ),
    (
        [
            {"product": "z", "quantity": 2, "unit_price": 1.11},
            {"product": "a", "quantity": 2, "unit_price": 1.11},
        ],
        [
            {"product": "a", "quantity": 2, "revenue": 2.22},
            {"product": "z", "quantity": 2, "revenue": 2.22},
        ],
    ),
    (
        [
            {"product": "Mug", "quantity": 2, "unit_price": 4.5},
            {"product": "Mug", "quantity": 1, "unit_price": 4.5},
            {"product": "Bag", "quantity": 1, "unit_price": 7},
        ],
        [
            {"product": "Bag", "quantity": 1, "revenue": 7},
            {"product": "Mug", "quantity": 3, "revenue": 13.5},
        ],
    ),
    (
        [{"product": "x", "quantity": 10, "unit_price": 0.05}],
        [{"product": "x", "quantity": 10, "revenue": 0.5}],
    ),
    (
        [
            {"product": "same", "quantity": 1, "unit_price": 1},
            {"product": "Same", "quantity": 1, "unit_price": 2},
        ],
        [
            {"product": "Same", "quantity": 1, "revenue": 2},
            {"product": "same", "quantity": 1, "revenue": 1},
        ],
    ),
    (
        [{"product": "K", "quantity": 7, "unit_price": 2.35}],
        [{"product": "K", "quantity": 7, "revenue": 16.45}],
    ),
    ([{"product": "", "quantity": 1, "unit_price": 2}], {"error": "invalid_row"}),
]

INVALID = [
    None,
    "not a list",
    {"product": "Tea", "quantity": 1, "unit_price": 1},
    [None],
    [{}],
    [{"product": "Tea", "quantity": 1}],
    [{"product": "Tea", "unit_price": 2}],
    [{"quantity": 1, "unit_price": 1}],
    [{"product": 7, "quantity": 1, "unit_price": 1}],
    [{"product": "naive\u0301", "quantity": 1, "unit_price": 1}],
    [{"product": "Tea", "quantity": True, "unit_price": 1}],
    [{"product": "Tea", "quantity": 1.5, "unit_price": 1}],
    [{"product": "Tea", "quantity": 0, "unit_price": 1}],
    [{"product": "Tea", "quantity": 1, "unit_price": True}],
    [{"product": "Tea", "quantity": 1, "unit_price": "1"}],
    [{"product": "Tea", "quantity": 1, "unit_price": -0.01}],
    [{"product": "Tea", "quantity": 1, "unit_price": float("inf")}],
    [{"product": "Tea", "quantity": 1, "unit_price": float("nan")}],
    [{"product": "Tea", "quantity": MyInt(1), "unit_price": 1}],
    [{"product": "Tea", "quantity": 1, "unit_price": MyFloat(1.5)}],
    [
        {"product": "Tea", "quantity": 1, "unit_price": Decimal("sNaN")},
        {"product": "", "quantity": 1, "unit_price": 1},
    ],
    [
        {"product": "Tea", "quantity": 1, "unit_price": 10**400},
        {"product": "", "quantity": 1, "unit_price": 1},
    ],
    [{"product": "Tea", "quantity": 1, "unit_price": 1}, None],
]

INVALID_RESULT = {"error": "invalid_row"}


def exact_price(value):
    """Read a stated price as its decimal literal, never as a binary float."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def plain_summary(rows):
    """Group rows with exact decimals and round each product separately."""
    totals = {}
    for row in rows:
        product = row["product"]
        if product not in totals:
            totals[product] = [0, Decimal(0)]
        totals[product][0] += row["quantity"]
        totals[product][1] += exact_price(row["unit_price"]) * row["quantity"]
    summary = []
    for product in sorted(totals):
        quantity, revenue = totals[product]
        rounded = revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        summary.append(
            {
                "product": product,
                "quantity": quantity,
                "revenue": float(rounded),
            }
        )
    return summary


def full_size_case():
    """Three thousand sales over sixty products, in scrambled name order."""
    generator = random.Random(20261017)
    rows = []
    for _ in range(3000):
        cents = generator.randrange(0, 100000)
        rows.append(
            {
                "product": f"P{generator.randrange(60):02d}",
                "quantity": generator.randrange(1, 100),
                "unit_price": Decimal(cents) / 100,
            }
        )
    order = [row["product"] for row in rows]
    assert order != sorted(order)
    return rows, plain_summary(rows)


for given, expected in CASES:
    assert solution.solution(given) == expected, given

for given in INVALID:
    assert solution.solution(given) == INVALID_RESULT, given

given, expected = full_size_case()
assert solution.solution(given) == expected
