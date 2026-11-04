"""Contract examples and an independent night-by-night quote oracle."""

import random

import solution


def request(  # noqa: PLR0913, PLR0917
    property_id="CEDAR",
    arrival=10,
    departure=11,
    adults=2,
    children=0,
    extras=(),
    bookings=(),
    promo_code="",
):
    return {
        "property_id": property_id,
        "arrival": arrival,
        "departure": departure,
        "adults": adults,
        "children": children,
        "extras": list(extras),
        "bookings": list(bookings),
        "promo_code": promo_code,
    }


def booking(property_id, arrival, departure):
    return {"property_id": property_id, "arrival": arrival, "departure": departure}


def rhu(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def oracle(given):  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Validate in contract order, then price direct day lookups."""
    property_id = given["property_id"].strip().upper()
    adults, children = given["adults"], given["children"]
    arrival, departure = given["arrival"], given["departure"]
    extras = [value.strip().upper() for value in given["extras"]]
    bookings = given["bookings"]
    promo = given["promo_code"].strip().upper()
    if property_id not in ("CEDAR", "LAKE"):
        return {"error": "BAD_PROPERTY", "index": None}
    if type(adults) is not int or not 1 <= adults <= 8:
        return {"error": "BAD_ADULTS", "index": None}
    if type(children) is not int or not 0 <= children <= 8:
        return {"error": "BAD_CHILDREN", "index": None}
    if (
        type(arrival) is not int
        or type(departure) is not int
        or not 0 <= arrival <= 1_000_000
        or not 0 <= departure <= 1_000_000
        or departure <= arrival
    ):
        return {"error": "BAD_DAYS", "index": None}
    if len(extras) > 4:
        return {"error": "BAD_EXTRA", "index": None}
    seen = set()
    for index, value in enumerate(extras):
        if value not in ("PARKING", "PET") or value in seen:
            return {"error": "BAD_EXTRA", "index": index}
        seen.add(value)
    if len(bookings) > 100:
        return {"error": "BAD_BOOKING", "index": None}
    normal_bookings = []
    for index, row in enumerate(bookings):
        booked_property = row["property_id"].strip().upper()
        start, end = row["arrival"], row["departure"]
        if (
            booked_property not in ("CEDAR", "LAKE")
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        ):
            return {"error": "BAD_BOOKING", "index": index}
        normal_bookings.append((booked_property, start, end))
    nights = departure - arrival
    if not 1 <= nights <= 30:
        return {"error": "BAD_STAY", "index": None}
    capacity = 4 if property_id == "CEDAR" else 6
    if adults + children > capacity:
        return {"error": "OVER_CAPACITY", "index": None}
    seasons = {"LOW": 0, "PEAK": 0, "SHOULDER": 0}
    base_rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
    for day in range(arrival, departure):
        season_day = day % 365
        season = (
            "LOW" if season_day < 120 else "PEAK" if season_day < 240 else "SHOULDER"
        )
        seasons[season] += 1
    for season, minimum in (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2)):
        if seasons[season] and nights < minimum:
            return {"error": "MIN_STAY", "index": None}
    for index, (booked_property, start, end) in enumerate(normal_bookings):
        if booked_property == property_id and arrival < end and start < departure:
            return {"error": "UNAVAILABLE", "index": index}
    if promo not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return {"error": "BAD_PROMO", "index": None}

    night_lines = []
    for day in range(arrival, departure):
        season_day = day % 365
        if season_day < 120:
            season = "LOW"
        elif season_day < 240:
            season = "PEAK"
        else:
            season = "SHOULDER"
        base = base_rates[season]
        weekend = 1500 if day % 7 in (4, 5) else 0
        night_lines.append(
            {
                "day": day,
                "season": season,
                "base_cents": base,
                "weekend_cents": weekend,
                "night_cents": base + weekend,
            }
        )
    night_subtotal = sum(line["night_cents"] for line in night_lines)
    cleaning = 4500
    extra_guest = (2000 * max(0, adults - 2) + 1000 * children) * nights
    tourist_tax = 800 * (adults + children) * min(nights, 5)
    extras_fee = sum(1200 * nights if item == "PARKING" else 2500 for item in extras)
    pre_discount = night_subtotal + cleaning + extra_guest + tourist_tax + extras_fee
    if nights >= 14:
        long_discount = rhu(night_subtotal * 15, 100)
    elif nights >= 7:
        long_discount = rhu(night_subtotal * 10, 100)
    else:
        long_discount = 0
    after_long = pre_discount - long_discount
    if promo == "PCT10":
        promo_discount = rhu(after_long * 10, 100)
    elif promo == "FIXED5000":
        promo_discount = min(5000, after_long)
    elif promo == "ONENIGHT":
        promo_discount = min(line["night_cents"] for line in night_lines)
    else:
        promo_discount = 0
    total = after_long - promo_discount
    deposit = min(total, max(10000, rhu(total * 30, 100)))
    applied = []
    effects = (
        (any(line["weekend_cents"] for line in night_lines), "weekend"),
        (cleaning > 0, "cleaning"),
        (extra_guest > 0, "extra-guests"),
        (tourist_tax > 0, "tourist-tax"),
        ("PARKING" in extras, "parking"),
        ("PET" in extras, "pet"),
        (long_discount > 0, "long-stay"),
        (promo_discount > 0, "promo"),
        (total > 0, "deposit"),
    )
    for enabled, label in effects:
        if enabled:
            applied.append(label)
    cancellation = "FLEX" if arrival >= 30 else "STANDARD" if arrival >= 7 else "FIRM"
    return {
        "nights": nights,
        "night_lines": night_lines,
        "cleaning_fee": cleaning,
        "extra_guest_fee": extra_guest,
        "tourist_tax": tourist_tax,
        "extras_fee": extras_fee,
        "long_stay_discount": long_discount,
        "promo_discount": promo_discount,
        "total": total,
        "deposit": deposit,
        "balance_due": total - deposit,
        "applied": applied,
        "cancellation": cancellation,
    }


def assert_case(given, expected=None):
    wanted = oracle(given) if expected is None else expected
    actual = solution.solution(given)
    assert actual == wanted, (
        f"request={given!r}\nexpected={wanted!r}\nactual={actual!r}"
    )


# Worked examples from the contract, including all stated cents. Example 3
# returns the PEAK minimum-stay error required by validation rule 10.
WORKED = [
    request(),
    request(arrival=11, departure=12),
    request(arrival=120, departure=121),
    request(arrival=10, departure=13),
    request(arrival=120, departure=123),
    request(arrival=14, departure=21),
    request("LAKE", 10, 12, 3, 2, ["PARKING", "PET"]),
    request(arrival=10, departure=11, promo_code="PCT10"),
    request(arrival=120, departure=123, promo_code="FIXED5000"),
    request(arrival=11, departure=12, promo_code="ONENIGHT"),
    request(arrival=240, departure=247),
    request(arrival=364, departure=366),
]
for given in WORKED:
    assert_case(given)
quotes = [solution.solution(given) for given in WORKED]
assert quotes[0]["total"] == 11100 and quotes[0]["deposit"] == 10000
assert (
    quotes[1]["night_lines"][0]["night_cents"] == 6500 and quotes[1]["total"] == 12600
)
assert quotes[2] == {"error": "MIN_STAY", "index": None}
assert sum(row["night_cents"] for row in quotes[3]["night_lines"]) == 18000
assert quotes[3]["cleaning_fee"] == 4500 and quotes[3]["tourist_tax"] == 4800
assert quotes[3]["total"] == 27300 and quotes[4]["total"] == 36300
assert quotes[4]["deposit"] == 10890 and quotes[4]["balance_due"] == 25410
assert quotes[5]["long_stay_discount"] == 3800 and quotes[5]["total"] == 46700
assert quotes[5]["deposit"] == 14010 and quotes[5]["balance_due"] == 32690
assert quotes[6]["extra_guest_fee"] == 8000 and quotes[6]["extras_fee"] == 4900
assert quotes[6]["tourist_tax"] == 8000 and quotes[6]["total"] == 36900
assert quotes[6]["deposit"] == 11070 and quotes[7]["promo_discount"] == 1110
assert quotes[7]["total"] == 9990 and quotes[7]["deposit"] == 9990
assert quotes[8]["promo_discount"] == 5000 and quotes[8]["total"] == 31300
assert quotes[8]["deposit"] == 10000 and quotes[8]["balance_due"] == 21300
assert quotes[9]["promo_discount"] == 6500 and quotes[9]["total"] == 6100
assert quotes[9]["deposit"] == 6100 and quotes[10]["long_stay_discount"] == 4850
assert quotes[10]["total"] == 56150 and quotes[10]["deposit"] == 16845
assert quotes[11]["night_lines"][0]["season"] == "SHOULDER"
assert quotes[11]["night_lines"][1]["season"] == "LOW"
assert quotes[11]["total"] == 19200 and quotes[11]["deposit"] == 10000

ERRORS = [
    (request(property_id="bad", adults=0), "BAD_PROPERTY", None),
    (request(adults=0, children=-1), "BAD_ADULTS", None),
    (request(children=-1), "BAD_CHILDREN", None),
    (request(property_id="LAKE", adults=1, children=6), "OVER_CAPACITY", None),
    (request(adults=9), "BAD_ADULTS", None),
    (request(adults=10), "BAD_ADULTS", None),
    (request(children=9), "BAD_CHILDREN", None),
    (request(children=10), "BAD_CHILDREN", None),
    (request(adults=True), "BAD_ADULTS", None),
    (request(children=True), "BAD_CHILDREN", None),
    (request(arrival=-1, departure=1), "BAD_DAYS", None),
    (request(bookings=[booking("CEDAR", -1, 1)]), "BAD_BOOKING", 0),
    (request(bookings=[booking("CEDAR", 0, -1)]), "BAD_BOOKING", 0),
    (request(bookings=[booking("CEDAR", 0, 0)]), "BAD_BOOKING", 0),
    (request(adults="2"), "BAD_ADULTS", None),
    (request(arrival="10"), "BAD_DAYS", None),
    (request(children=None), "BAD_CHILDREN", None),
    (request(arrival=10, departure=10, extras=["bad"]), "BAD_DAYS", None),
    (request(extras=["PET", "BOGUS"]), "BAD_EXTRA", 1),
    (request(extras=["PET", "PET"]), "BAD_EXTRA", 1),
    (request(bookings=[booking("bad", 4, 3)] * 101), "BAD_BOOKING", None),
    (request(bookings=[booking("bad", 4, 3)]), "BAD_BOOKING", 0),
    (request(arrival=120, departure=122), "MIN_STAY", None),
    (
        request(adults=4, children=1, bookings=[booking("CEDAR", 10, 11)]),
        "OVER_CAPACITY",
        None,
    ),
    (
        request(
            property_id="LAKE",
            arrival=120,
            departure=123,
            bookings=[booking("LAKE", 122, 125), booking("LAKE", 119, 121)],
        ),
        "UNAVAILABLE",
        0,
    ),
    (request(bookings=[booking("CEDAR", 10, 11)], promo_code="bad"), "UNAVAILABLE", 0),
    (request(arrival=0, departure=31, promo_code="bad"), "BAD_STAY", None),
    (request(extras=["PET", "bad"], bookings=[booking("bad", 4, 3)]), "BAD_EXTRA", 1),
    (request(bookings=[booking("bad", 4, 3)], promo_code="bad"), "BAD_BOOKING", 0),
]
for given, code, index in ERRORS:
    assert_case(given, {"error": code, "index": index})

# Seasonal, stay, availability, promo and cancellation boundaries.
BOUNDARIES = [
    request(property_id=" cedar "),
    request(property_id=" lake ", adults=6),
    request(adults=1),
    request(adults=8),
    request(property_id="LAKE", children=8),
    request(arrival=0, departure=1),
    request(arrival=999999, departure=1000000),
    request(arrival=1000000, departure=1000001),
    request(extras=[" parking "]),
    request(extras=["PET", "PARKING"]),
    request(extras=["PET", "PARKING", "PET", "PARKING", "PET"]),
    request(bookings=[booking(" cedar ", 11, 12)]),
    request(arrival=120, departure=123),
    request(arrival=239, departure=242),
    request(arrival=364, departure=366),
    request(arrival=11, departure=12),
    request(arrival=10, departure=10, adults=0),
    request(property_id="x", adults=0, children=-1),
    request(bookings=[booking("CEDAR", 0, 1)]),
    request(bookings=[booking("CEDAR", 9, 10)]),
    request(bookings=[booking("CEDAR", 11, 12)]),
    request(bookings=[booking("CEDAR", 10, 10)]),
    request(bookings=[booking("CEDAR", 10, 11)]),
    request(bookings=[booking("LAKE", 10, 11)]),
    request(bookings=[booking("LAKE", 0, 101)] * 101),
    request(extras=["PET", "PARKING", "PET", "PARKING", "PET"]),
    request(extras=["PARKING"] * 5),
    request(arrival=30, departure=31),
    request(arrival=29, departure=30),
    request(arrival=31, departure=32),
    request(arrival=8, departure=9),
    request(arrival=7, departure=8),
    request(arrival=0, departure=1, promo_code="PCT10"),
    request(arrival=0, departure=1, promo_code="FIXED5000"),
    request(arrival=0, departure=1, promo_code="ONENIGHT"),
    request(arrival=6, departure=7),
    request(arrival=7, departure=8),
    request(arrival=13, departure=20),
    request(arrival=20, departure=34),
    request(arrival=0, departure=6),
    request(arrival=0, departure=7),
    request(arrival=0, departure=13),
    request(arrival=0, departure=14),
    request(arrival=0, departure=30),
    request(arrival=0, departure=19),
    request(arrival=10, departure=11, promo_code=" PCT10 "),
    request(arrival=10, departure=11, promo_code="FIXED5000"),
    request(arrival=10, departure=11, promo_code="ONENIGHT"),
]
for given in BOUNDARIES:
    assert_case(given)
assert solution.solution(request(arrival=0, departure=19))["deposit"] == 29888

one_hundred = [
    booking("LAKE", 100 + 2 * index, 101 + 2 * index) for index in range(100)
]
assert_case(request(bookings=one_hundred))


def random_requests():
    rng = random.Random(20261018)
    error_codes = (
        "BAD_PROPERTY", "BAD_ADULTS", "BAD_CHILDREN", "BAD_DAYS", "BAD_EXTRA",
        "BAD_BOOKING", "BAD_STAY", "OVER_CAPACITY", "MIN_STAY", "UNAVAILABLE",
        "BAD_PROMO",
    )
    counts = {"valid": 0, "invalid": 0}
    for _ in range(5000):
        prop = rng.choice(("CEDAR", "LAKE"))
        season = rng.randrange(3)
        if season == 0:
            phase, minimum = rng.randrange(0, 90), 1
        elif season == 1:
            phase, minimum = rng.randrange(120, 210), 3
        else:
            phase, minimum = rng.randrange(240, 335), 2
        start = rng.randrange(0, 100_001) // 365 * 365 + phase
        length = rng.randrange(minimum, 31)
        guests = rng.randrange(1, 5 if prop == "CEDAR" else 7)
        adults = rng.randrange(1, min(8, guests) + 1)
        children = guests - adults
        extras = rng.sample(("PARKING", "PET"), rng.randrange(3))
        rows = []
        if rng.random() < 0.5:
            rows.append(booking("LAKE" if prop == "CEDAR" else "CEDAR", start, start + 1))
        promo = rng.choice(("", "PCT10", "FIXED5000", "ONENIGHT"))
        given = request(prop, start, start + length, adults, children, extras, rows, promo)
        expected_error = None
        code = None
        if rng.random() < 0.25:
            code = rng.choice(error_codes)
            if code == "BAD_PROPERTY":
                given["property_id"] = "bad"
            elif code == "BAD_ADULTS":
                given["adults"] = rng.choice((0, 9, True, "2"))
            elif code == "BAD_CHILDREN":
                given["children"] = rng.choice((-1, 9, True, None))
            elif code == "BAD_DAYS":
                given["arrival"], given["departure"] = -1, 1
            elif code == "BAD_EXTRA":
                given["extras"] = ["PARKING"] * 5
            elif code == "BAD_BOOKING":
                given["bookings"] = [booking("CEDAR", -1, 1)]
            elif code == "BAD_STAY":
                given["arrival"], given["departure"] = 10, 42
            elif code == "OVER_CAPACITY":
                given["property_id"], given["adults"], given["children"] = "CEDAR", 4, 1
            elif code == "MIN_STAY":
                given["arrival"], given["departure"] = 120, 121
            elif code == "UNAVAILABLE":
                given["bookings"] = [booking(given["property_id"], given["arrival"], given["departure"])]
            elif code == "BAD_PROMO":
                given["promo_code"] = "unknown"
            expected_error = code
        actual = oracle(given)
        if expected_error is not None:
            assert actual == {"error": expected_error, "index": None} or actual["error"] == expected_error, (given, actual, expected_error)
        else:
            assert "error" not in actual, (given, actual)
        counts["invalid" if expected_error else "valid"] += 1
        yield given
    assert counts["valid"] >= 2500, counts
    print(f"random requests: {counts['valid']} valid, {counts['invalid']} invalid")


for generated in random_requests():
    assert_case(generated)
