"""Exact contract cases plus a deterministic, independent Fraction oracle."""

import os
import random
import re
from fractions import Fraction

import solution


def item(sku, qty, price):
    return {"sku": sku, "qty": qty, "price": price}


def request(items, tier="basic", coupon="", region="EU"):
    return {"items": items, "tier": tier, "coupon": coupon, "region": region}


# The seven examples and their outputs are transcribed from the pilot contract.
WORKED = [
    (
        request(
            [item(" ab-12 ", 2, "10.00"), item("CD-34", 1, "5.50")], "Silver", "", "us"
        ),
        {
            "lines": [
                {"sku": "AB-12", "qty": 2, "unit_cents": 1000, "line_cents": 2000},
                {"sku": "CD-34", "qty": 1, "unit_cents": 550, "line_cents": 550},
            ],
            "subtotal": 2550,
            "tier_discount": 128,
            "coupon_discount": 0,
            "shipping": 500,
            "tax": 170,
            "total": 3092,
            "applied": ["tier", "tax"],
        },
    ),
    (
        request([item("X1X", 10, "20.00")], "gold", "pct10", "EU"),
        {
            "lines": [
                {"sku": "X1X", "qty": 10, "unit_cents": 2000, "line_cents": 20000}
            ],
            "subtotal": 20000,
            "tier_discount": 2000,
            "coupon_discount": 1800,
            "shipping": 0,
            "tax": 3240,
            "total": 19440,
            "applied": ["tier", "coupon", "free-shipping", "tax"],
        },
    ),
    (
        request(
            [item("aaa", 3, "1.00"), item("AAA", 4, "1")], "basic", "FIXED5", "ASIA"
        ),
        {
            "lines": [{"sku": "AAA", "qty": 7, "unit_cents": 100, "line_cents": 700}],
            "subtotal": 700,
            "tier_discount": 0,
            "coupon_discount": 500,
            "shipping": 1200,
            "tax": 20,
            "total": 1420,
            "applied": ["coupon", "tax"],
        },
    ),
    (
        request([item("ZZZ", 1, "0.01")], "silver", " freeship ", "EU"),
        {
            "lines": [{"sku": "ZZZ", "qty": 1, "unit_cents": 1, "line_cents": 1}],
            "subtotal": 1,
            "tier_discount": 0,
            "coupon_discount": 0,
            "shipping": 0,
            "tax": 0,
            "total": 1,
            "applied": ["free-shipping"],
        },
    ),
    (
        request([item("RND", 1, "2.50")], "basic", "", "US"),
        {
            "lines": [{"sku": "RND", "qty": 1, "unit_cents": 250, "line_cents": 250}],
            "subtotal": 250,
            "tier_discount": 0,
            "coupon_discount": 0,
            "shipping": 500,
            "tax": 18,
            "total": 768,
            "applied": ["tax"],
        },
    ),
    (
        request([item("CAP", 1, "3.00")], "basic", "FIXED500", "US"),
        {
            "lines": [{"sku": "CAP", "qty": 1, "unit_cents": 300, "line_cents": 300}],
            "subtotal": 300,
            "tier_discount": 0,
            "coupon_discount": 300,
            "shipping": 500,
            "tax": 0,
            "total": 500,
            "applied": ["coupon"],
        },
    ),
]

ERRORS = [
    (request([]), {"error": "EMPTY_ORDER", "index": None}),
    (request([item("a", 1, "1")]), {"error": "BAD_SKU", "index": 0}),
    (request([item("ABC", 0, "1")]), {"error": "BAD_QTY", "index": 0}),
    (request([item("ABC", 1, "1.234")]), {"error": "BAD_PRICE", "index": 0}),
    (
        request([item("ABC", 1, "1"), item("abc", 1, "2")]),
        {"error": "PRICE_CONFLICT", "index": 1},
    ),
    (
        request([item("ABC", 600, "1"), item("abc", 500, "1.0")]),
        {"error": "BAD_QTY", "index": 1},
    ),
    (
        request([item("ABC", 500, "1"), item("abc", 501, "1.00")]),
        {"error": "BAD_QTY", "index": 1},
    ),
    (request([item("ABC", 1, "1")], "platinum"), {"error": "BAD_TIER", "index": None}),
    (
        request([item("ABC", 1, "1")], "platinum", "PCT0", "MARS"),
        {"error": "BAD_TIER", "index": None},
    ),
    (
        request([item("ABC", 1, "1")], "basic", "PCT0"),
        {"error": "BAD_COUPON", "index": None},
    ),
    (
        request([item("ABC", 1, "1")], "basic", "", "MARS"),
        {"error": "BAD_REGION", "index": None},
    ),
    (request([item("ABC", 1, "0")]), {"error": "BAD_PRICE", "index": 0}),
    (request([item("ABC", 1, "0.00")]), {"error": "BAD_PRICE", "index": 0}),
    (request([item("ABC", 1, None)]), {"error": "BAD_PRICE", "index": 0}),
]


def add_error_cases():
    cases = list(ERRORS)
    cases.extend(
        (request([item("A" * n, 1, "1")]), {"error": "BAD_SKU", "index": 0})
        for n in (2, 13)
    )
    cases.extend(
        (request([item(sku, 1, "1")]), {"error": "BAD_SKU", "index": 0})
        for sku in ("AB_", "AB ", "ÄBC")
    )
    cases.extend(
        (request([item("ABC", qty, "1")]), {"error": "BAD_QTY", "index": 0})
        for qty in (1001, True, 1.0, "1")
    )
    bad_prices = (
        "0",
        "0.00",
        "1.234",
        "abc",
        "",
        "1234567",
        "1000000",
        ".50",
        ".5",
        "1.",
        "+1",
        "-1",
        " 1",
        "1 ",
        "1 0",
        "1,5",
        "1a",
        "1e3",
    )
    cases.extend(
        (request([item("ABC", 1, price)]), {"error": "BAD_PRICE", "index": 0})
        for price in bad_prices
    )
    for coupon in (
        "PCT0",
        "PCT51",
        "PCT07",
        "FIXED0",
        "FIXED501",
        "FIXED05",
        "PCT",
        "PCTX",
        "FIXED1A",
        "PCT-5",
        "PCT5.0",
        "FIXED 5",
        "OTHER",
    ):
        cases.append(
            (
                request([item("ABC", 1, "1")], "basic", coupon),
                {"error": "BAD_COUPON", "index": None},
            )
        )
    cases.append(
        (
            request([item("ABC", 1, "1")], "basic", "", "mars"),
            {"error": "BAD_REGION", "index": None},
        )
    )
    # Top-level item-count precedence and field-before-merge precedence.
    cases.append(
        (
            request([item("ABC", 1, "1")] * 51, "bad"),
            {"error": "TOO_MANY_ITEMS", "index": None},
        )
    )
    cases.append(
        (
            request([item("ABC", 1, "1"), item("BAD", 0, "bad"), item("BAD", 1, "1")]),
            {"error": "BAD_QTY", "index": 1},
        )
    )
    cases.append(
        (
            request([item("ABC", 1, "1"), item("abc", 1, "2"), item("bad", 0, "1")]),
            {"error": "BAD_QTY", "index": 2},
        )
    )
    # Validate all individual fields before detecting a duplicate conflict.
    cases.append(
        (
            request([item("ABC", 1, "1"), item("abc", 0, "2")]),
            {"error": "BAD_QTY", "index": 1},
        )
    )
    cases.append(
        (
            request([item("ABC", 1, "1")], "bad", "PCT0", "MARS"),
            {"error": "BAD_TIER", "index": None},
        )
    )
    cases.append(
        (
            request([item("ABC", 1, "1")], "basic", "PCT0", "MARS"),
            {"error": "BAD_COUPON", "index": None},
        )
    )
    # Combined failures prove item errors precede option errors and duplicates.
    cases.append(
        (
            request([item("ABC", 1, "1"), item("abc", 1, "2")], "bad", "PCT0", "MARS"),
            {"error": "PRICE_CONFLICT", "index": 1},
        )
    )
    return cases


ERRORS = add_error_cases()


def rhu(value):
    """Round a nonnegative exact rational half up, at explicit boundaries."""
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def oracle(given):
    """Compute expected output by staged exact arithmetic and ordered checks."""
    rows = given["items"]
    if not rows:
        return {"error": "EMPTY_ORDER", "index": None}
    if len(rows) > 50:
        return {"error": "TOO_MANY_ITEMS", "index": None}
    normalized = []
    for index, raw in enumerate(rows):
        sku = raw["sku"].strip().upper()
        qty = raw["qty"]
        price = raw["price"]
        if not re.fullmatch(r"[A-Z0-9-]{3,12}", sku):
            return {"error": "BAD_SKU", "index": index}
        if type(qty) is not int or not 1 <= qty <= 1000:
            return {"error": "BAD_QTY", "index": index}
        if not isinstance(price, str) or not re.fullmatch(
            r"[0-9]{1,6}(\.[0-9]{1,2})?", price
        ):
            return {"error": "BAD_PRICE", "index": index}
        whole, dot, fraction = price.partition(".")
        cents = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
        if cents <= 0:
            return {"error": "BAD_PRICE", "index": index}
        normalized.append((sku, qty, cents))

    merged = {}
    for index, (sku, qty, cents) in enumerate(normalized):
        if sku not in merged:
            merged[sku] = [qty, cents]
            continue
        if merged[sku][1] != cents:
            return {"error": "PRICE_CONFLICT", "index": index}
        merged[sku][0] += qty
        if merged[sku][0] > 1000:
            return {"error": "BAD_QTY", "index": index}

    tier = given["tier"].strip().lower()
    coupon = given["coupon"].strip().upper()
    region = given["region"].strip().upper()
    failure = next(
        (
            code
            for valid, code in (
                (tier in {"basic", "silver", "gold"}, "BAD_TIER"),
                (
                    coupon == ""
                    or re.fullmatch(
                        r"(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|"
                        r"[1-4][0-9]{2}|500)|FREESHIP)",
                        coupon,
                    )
                    is not None,
                    "BAD_COUPON",
                ),
                (region in {"EU", "US", "ASIA"}, "BAD_REGION"),
            )
            if not valid
        ),
        None,
    )
    if failure:
        return {"error": failure, "index": None}
    rate = {"basic": 0, "silver": 500, "gold": 1000}[tier]
    tax_rate, base_ship, threshold = {
        "EU": (2000, 800, 10000),
        "US": (700, 500, 7500),
        "ASIA": (1000, 1200, 15000),
    }[region]
    lines = [
        {
            "sku": sku,
            "qty": data[0],
            "unit_cents": data[1],
            "line_cents": data[0] * data[1],
        }
        for sku, data in sorted(merged.items())
    ]
    subtotal = sum(line["line_cents"] for line in lines)
    tier_discount = rhu(Fraction(subtotal * rate, 10000))
    remaining = subtotal - tier_discount
    if coupon.startswith("PCT"):
        coupon_discount = rhu(Fraction(remaining * int(coupon[3:]), 100))
    elif coupon.startswith("FIXED"):
        coupon_discount = min(int(coupon[5:]) * 100, remaining)
    else:
        coupon_discount = 0
    net = remaining - coupon_discount
    shipping = 0 if coupon == "FREESHIP" or net >= threshold else base_ship
    tax = rhu(Fraction(net * tax_rate, 10000))
    applied = []
    for present, label in (
        (tier_discount > 0, "tier"),
        (coupon_discount > 0, "coupon"),
        (shipping == 0, "free-shipping"),
        (tax > 0, "tax"),
    ):
        if present:
            applied.append(label)
    return {
        "lines": lines,
        "subtotal": subtotal,
        "tier_discount": tier_discount,
        "coupon_discount": coupon_discount,
        "shipping": shipping,
        "tax": tax,
        "total": net + shipping + tax,
        "applied": applied,
    }


# Set by tools/mutate_check.py --random-only to leave the random loop alone.
RANDOM_ONLY = os.environ.get("ORDER_QUOTE_RANDOM_ONLY") == "1"


def assert_case(given, expected, random_check=False):
    if RANDOM_ONLY and not random_check:
        return
    actual = solution.solution(given)
    assert actual == expected, (given, expected, actual)


for given, expected in WORKED:
    assert_case(given, expected)
for given, expected in ERRORS:
    assert_case(given, expected)

# Half-up ties occur independently at tier, percentage coupon, and tax stages.
assert_case(
    request([item("TIE", 1, "0.10")], "silver", "", "EU"),
    {
        "lines": [{"sku": "TIE", "qty": 1, "unit_cents": 10, "line_cents": 10}],
        "subtotal": 10,
        "tier_discount": 1,
        "coupon_discount": 0,
        "shipping": 800,
        "tax": 2,
        "total": 811,
        "applied": ["tier", "tax"],
    },
)
assert_case(
    request([item("TIE", 1, "0.05")], "basic", "PCT10", "US"),
    {
        "lines": [{"sku": "TIE", "qty": 1, "unit_cents": 5, "line_cents": 5}],
        "subtotal": 5,
        "tier_discount": 0,
        "coupon_discount": 1,
        "shipping": 500,
        "tax": 0,
        "total": 504,
        "applied": ["coupon"],
    },
)
assert_case(
    request([item("TIE", 1, "0.50")], "basic", "", "US"),
    {
        "lines": [{"sku": "TIE", "qty": 1, "unit_cents": 50, "line_cents": 50}],
        "subtotal": 50,
        "tier_discount": 0,
        "coupon_discount": 0,
        "shipping": 500,
        "tax": 4,
        "total": 554,
        "applied": ["tax"],
    },
)

# Exact shipping thresholds and one cent below for every region.
for area, threshold in (("EU", 10000), ("US", 7500), ("ASIA", 15000)):
    for net in (threshold - 1, threshold):
        given = request(
            [item("EDGE", 1, f"{net // 100}.{net % 100:02d}")], "basic", "", area
        )
        assert_case(given, oracle(given))

# Duplicate quantities accept the exact limit regardless of how it is split.
for quantities in ((500, 500), (999, 1)):
    given = request(
        [item("ABC", quantities[0], "1"), item("abc", quantities[1], "1.00")]
    )
    assert_case(given, oracle(given))

# The subtotal reaches each regional threshold, but tier and coupon discounts
# reduce the shipping basis below it. Shipping must still be charged.
for area, threshold in (("EU", 10000), ("US", 7500), ("ASIA", 15000)):
    subtotal = threshold * 112 // 100
    given = request(
        [item("EDGE", 1, f"{subtotal // 100}.{subtotal % 100:02d}")],
        "gold",
        "PCT10",
        area,
    )
    expected = oracle(given)
    assert expected["subtotal"] >= threshold
    after_tier = expected["subtotal"] - expected["tier_discount"]
    assert after_tier >= threshold
    assert after_tier - expected["coupon_discount"] < threshold
    assert expected["shipping"] > 0
    assert_case(given, expected)

# Sorting is ordinal after upper-casing; punctuation and digits matter.
order = request(
    [item("a1x", 1, "1"), item("A1X", 1, "1"), item("A-1", 1, "1"), item("A01", 1, "1")]
)
assert_case(order, oracle(order))

# Exactly fifty distinct products remain valid.
fifty = request(
    [item(f"S{i:02d}", i, "1.25") for i in range(50)], "gold", "PCT7", "ASIA"
)
assert_case(fifty, oracle(fifty))


def random_requests():
    rng = random.Random(20261017)
    skus = ["A-1", "A1B", "x9-y", "SKU-7", "ABC", "Q-42"]
    prices = [
        "0.01",
        "1",
        "1.2",
        "12.34",
        "999999.99",
        "0",
        "1.234",
        "bad",
        "1234567",
        "",
    ]
    tiers = ["basic", "silver", "gold", "platinum", " Silver "]
    coupons = [
        "",
        "PCT1",
        "PCT7",
        "PCT50",
        "PCT0",
        "PCT07",
        "FIXED1",
        "FIXED500",
        "FIXED501",
        "FREESHIP",
        " pct10 ",
    ]
    regions = ["EU", "US", "ASIA", "MARS", " us "]
    for _ in range(4000):
        count = rng.randrange(0, 7)
        rows = []
        for _ in range(count):
            sku = rng.choice(skus + ["ab", "ABCDEFGHIJKLM", "AB_", " "])
            qty = rng.choice([1, 2, 10, 999, 1000, 0, 1001, True, 1.5])
            price = rng.choice(prices)
            rows.append(item(sku, qty, price))
        yield request(rows, rng.choice(tiers), rng.choice(coupons), rng.choice(regions))


for generated in random_requests():
    assert_case(generated, oracle(generated), random_check=True)
