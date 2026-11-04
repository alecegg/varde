"""Shared behaviour test for the aging report item: bank cases, rejections, and a random sweep."""

import random
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import solution

CASES = [
    (
        [],
        {
            "invoices": [],
            "totals": {"current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 0, "balance": 100}],
        {
            "invoices": [{"id": "A", "bucket": "current", "fee": 0}],
            "totals": {"current": 100, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 1, "balance": 100}],
        {
            "invoices": [{"id": "A", "bucket": "1-30", "fee": 2}],
            "totals": {"current": 0, "1-30": 100, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 30, "balance": 100}],
        {
            "invoices": [{"id": "A", "bucket": "1-30", "fee": 2}],
            "totals": {"current": 0, "1-30": 100, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 31, "balance": 200}],
        {
            "invoices": [{"id": "A", "bucket": "31-60", "fee": 10}],
            "totals": {"current": 0, "1-30": 0, "31-60": 200, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 60, "balance": 50}],
        {
            "invoices": [{"id": "A", "bucket": "31-60", "fee": 2.5}],
            "totals": {"current": 0, "1-30": 0, "31-60": 50, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 61, "balance": 100}],
        {
            "invoices": [{"id": "A", "bucket": "61-90", "fee": 8}],
            "totals": {"current": 0, "1-30": 0, "31-60": 0, "61-90": 100, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 90, "balance": 50}],
        {
            "invoices": [{"id": "A", "bucket": "61-90", "fee": 4}],
            "totals": {"current": 0, "1-30": 0, "31-60": 0, "61-90": 50, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 91, "balance": 300}],
        {
            "invoices": [{"id": "A", "bucket": "over-90", "fee": 30}],
            "totals": {"current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 300},
        },
    ),
    (
        [{"id": "B", "days_overdue": -2, "balance": 40}],
        {
            "invoices": [{"id": "B", "bucket": "current", "fee": 0}],
            "totals": {"current": 40, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [
            {"id": "B", "days_overdue": -2, "balance": 40},
            {"id": "A", "days_overdue": 31, "balance": 80},
            {"id": "C", "days_overdue": 5, "balance": 50},
        ],
        {
            "invoices": [
                {"id": "A", "bucket": "31-60", "fee": 4},
                {"id": "B", "bucket": "current", "fee": 0},
                {"id": "C", "bucket": "1-30", "fee": 1},
            ],
            "totals": {
                "current": 40,
                "1-30": 50,
                "31-60": 80,
                "61-90": 0,
                "over-90": 0,
            },
        },
    ),
]

# A whole number day count is a day count however Python spells it. A money amount
# is always read as the decimal literal it was written as, so 0.3 is three tenths
# even though the nearest binary float is a hair below three tenths.
ACCEPTED = [
    (
        [{"id": "A", "days_overdue": True, "balance": 10}],
        {
            "invoices": [{"id": "A", "bucket": "1-30", "fee": 0.2}],
            "totals": {"current": 0, "1-30": 10, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": 31, "balance": 0.3}],
        {
            "invoices": [{"id": "A", "bucket": "31-60", "fee": 0.02}],
            "totals": {"current": 0, "1-30": 0, "31-60": 0.3, "61-90": 0, "over-90": 0},
        },
    ),
    (
        [{"id": "A", "days_overdue": -1, "balance": Decimal("16.6")}],
        {
            "invoices": [{"id": "A", "bucket": "current", "fee": 0.0}],
            "totals": {
                "current": 16.6,
                "1-30": 0,
                "31-60": 0,
                "61-90": 0,
                "over-90": 0,
            },
        },
    ),
    (
        [{"id": "A", "days_overdue": 91, "balance": 1000000}],
        {
            "invoices": [{"id": "A", "bucket": "over-90", "fee": 100000.0}],
            "totals": {
                "current": 0,
                "1-30": 0,
                "31-60": 0,
                "61-90": 0,
                "over-90": 1000000.0,
            },
        },
    ),
]

REJECTED = [
    None,
    "not a list",
    {},
    [None],
    [42],
    [{"days_overdue": 1, "balance": 10}],
    [{"id": 7, "days_overdue": 1, "balance": 10}],
    [{"id": "", "days_overdue": 1, "balance": 10}],
    [{"id": "naive\u0301", "days_overdue": 1, "balance": 10}],
    [{"id": "A", "days_overdue": 1, "balance": "10"}],
    [{"id": "A", "days_overdue": 1, "balance": None}],
    [{"id": "A", "days_overdue": 1, "balance": True}],
    [{"id": "A", "days_overdue": 1, "balance": Fraction(1, 2)}],
    [{"id": "A", "days_overdue": 1, "balance": -1}],
    [{"id": "A", "days_overdue": 1, "balance": 1_000_001}],
    [{"id": "A", "days_overdue": 1, "balance": Decimal("1000000.01")}],
    [{"id": "A", "days_overdue": 1, "balance": float("inf")}],
    [{"id": "A", "days_overdue": 1, "balance": float("nan")}],
    [{"id": "A", "days_overdue": 1, "balance": Decimal("Infinity")}],
    [{"id": "A", "days_overdue": 1, "balance": Decimal("NaN")}],
    [{"id": "A", "days_overdue": 1.5, "balance": 10}],
    [{"id": "A", "days_overdue": None, "balance": 10}],
    [{"id": "A", "days_overdue": "3", "balance": 10}],
    [
        {"id": "A", "days_overdue": 1, "balance": 10},
        {"id": "B", "days_overdue": -1, "balance": -5},
    ],
]

BUCKETS = ("current", "1-30", "31-60", "61-90", "over-90")
RATES = {
    "current": Decimal("0"),
    "1-30": Decimal("0.02"),
    "31-60": Decimal("0.05"),
    "61-90": Decimal("0.08"),
    "over-90": Decimal("0.10"),
}
CENTS = Decimal("0.01")


def literal(value):
    """The exact decimal a supplied amount was written as."""
    return value if isinstance(value, Decimal) else Decimal(repr(value))


def plain_report(invoices):
    """Bucket, price, and total the invoices from exact decimals with this test's own loops."""
    rows = []
    for invoice in sorted(invoices, key=lambda item: item["id"]):
        days = invoice["days_overdue"]
        if days <= 0:
            place = "current"
        elif days <= 30:
            place = "1-30"
        elif days <= 60:
            place = "31-60"
        elif days <= 90:
            place = "61-90"
        else:
            place = "over-90"
        fee = (literal(invoice["balance"]) * RATES[place]).quantize(
            CENTS, rounding=ROUND_HALF_UP
        )
        rows.append({"id": invoice["id"], "bucket": place, "fee": float(fee)})
    totals = {}
    for name in BUCKETS:
        running = Decimal(0)
        for invoice in invoices:
            days = invoice["days_overdue"]
            if days <= 0:
                place = "current"
            elif days <= 30:
                place = "1-30"
            elif days <= 60:
                place = "31-60"
            elif days <= 90:
                place = "61-90"
            else:
                place = "over-90"
            if place == name:
                running = running + literal(invoice["balance"])
        totals[name] = float(running.quantize(CENTS, rounding=ROUND_HALF_UP))
    return {"invoices": rows, "totals": totals}


def sweep_case(seed, count, spelled_as_float):
    """Draw count in-domain invoices, in scrambled identifier order, for one seed."""
    generator = random.Random(seed)
    identifiers = [f"I{index:05d}-{seed}" for index in range(count)]
    generator.shuffle(identifiers)
    invoices = []
    for identifier in identifiers:
        cents = generator.randrange(0, 100_000_001)
        balance = cents / 100 if spelled_as_float else Decimal(cents).scaleb(-2)
        invoices.append(
            {
                "id": identifier,
                "days_overdue": generator.randrange(-30, 201),
                "balance": balance,
            }
        )
    order = [invoice["id"] for invoice in invoices]
    assert order != sorted(identifiers), seed
    assert len(set(order)) == count, seed
    return invoices, plain_report(invoices)


SWEEP = [(101, 750, False), (202, 750, True), (303, 900, False), (404, 900, True)]

for given, expected in [*CASES, *ACCEPTED]:
    assert solution.solution(given) == expected, given

for given in REJECTED:
    try:
        solution.solution(given)
    except ValueError:
        continue
    raise AssertionError(f"expected a rejection: {given!r}")

for seed, count, spelled_as_float in SWEEP:
    given, expected = sweep_case(seed, count, spelled_as_float)
    assert solution.solution(given) == expected, seed
