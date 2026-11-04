"""Integer-cent holiday rental quote contract."""

QUOTE_KEYS = (
    "nights",
    "night_lines",
    "cleaning_fee",
    "extra_guest_fee",
    "tourist_tax",
    "extras_fee",
    "long_stay_discount",
    "promo_discount",
    "total",
    "deposit",
    "balance_due",
    "applied",
    "cancellation",
)
APPLIED_AMOUNT_LABELS = (
    ("guests", "extra-guests"),
    ("promo_discount", "promo"),
    ("long_discount", "long-stay"),
    ("total", "deposit"),
)
APPLIED_NAMES = (
    "weekend",
    "cleaning",
    "extra-guests",
    "tourist-tax",
    "parking",
    "pet",
    "long-stay",
    "promo",
    "deposit",
)
PROPERTIES = {"CEDAR", "LAKE"}
EXTRAS = {"PARKING", "PET"}
PROMOS = {"", "PCT10", "FIXED5000", "ONENIGHT"}
MINIMUMS = (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2))


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    data = normalize_request(request)
    if failure := validate_request(data):
        return failure
    rows = build_nights(data)
    return assemble_quote(data, rows, price_quote(data, rows))


def normalize_request(request):
    return {
        **request,
        "property_id": request["property_id"].strip(" ").upper(),
        "extras": [item.strip(" ").upper() for item in request["extras"]],
        "bookings": normalize_bookings(request["bookings"]),
        "promo_code": request["promo_code"].strip(" ").upper(),
    }


def normalize_bookings(bookings):
    return [
        (row["property_id"].strip(" ").upper(), row["arrival"], row["departure"])
        for row in bookings
    ]


def error_result(code: str, index: int | None = None) -> dict:
    return {"error": code, "index": index}


def validate_request(data):
    checks = (
        property_error,
        days_error,
        extras_error,
        bookings_error,
        stay_error,
        minimum_stay_error,
        availability_error,
    )
    for check in checks:
        failure = check(data)
        if failure:
            return failure
    return error_result("BAD_PROMO") if data["promo_code"] not in PROMOS else None


def property_error(data):
    if data["property_id"] not in PROPERTIES:
        return error_result("BAD_PROPERTY")
    limits = (("adults", 1, 8, "BAD_ADULTS"), ("children", 0, 8, "BAD_CHILDREN"))
    return next(
        (
            error_result(code)
            for key, low, high, code in limits
            if type(data[key]) is not int or not low <= data[key] <= high
        ),
        None,
    )


def days_error(data):
    start, end = data["arrival"], data["departure"]
    valid_days = (
        type(start) is int
        and type(end) is int
        and 0 <= start <= 1_000_000
        and 0 <= end <= 1_000_000
    )
    if not valid_days or end <= start:
        return error_result("BAD_DAYS")
    return None


def extras_error(data):
    extras = data["extras"]
    if len(extras) > 4:
        return error_result("BAD_EXTRA")
    seen = set()
    for index, item in enumerate(extras):
        if item not in EXTRAS or item in seen:
            return error_result("BAD_EXTRA", index)
        seen.add(item)
    return None


def bookings_error(data):
    rows = data["bookings"]
    if len(rows) > 100:
        return error_result("BAD_BOOKING")
    invalid = next(
        (
            index
            for index, (prop, start, end) in enumerate(rows)
            if prop not in PROPERTIES
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        ),
        None,
    )
    return error_result("BAD_BOOKING", invalid) if invalid is not None else None


def stay_error(data):
    nights = data["departure"] - data["arrival"]
    if not 1 <= nights <= 30:
        return error_result("BAD_STAY")
    capacity = 4 if data["property_id"] == "CEDAR" else 6
    guests = data["adults"] + data["children"]
    return error_result("OVER_CAPACITY") if guests > capacity else None


def season_terms(day):
    position = day % 365
    if position < 120:
        return "LOW", 5000
    if position < 240:
        return "PEAK", 9000
    return "SHOULDER", 6500


def minimum_stay_error(data):
    start, end = data["arrival"], data["departure"]
    occupied = {season_terms(day)[0] for day in range(start, end)}
    for season, minimum in MINIMUMS:
        if season in occupied and end - start < minimum:
            return error_result("MIN_STAY")
    return None


def availability_error(data):
    start, end = data["arrival"], data["departure"]
    for index, (prop, booked_start, booked_end) in enumerate(data["bookings"]):
        overlaps = start < booked_end and booked_start < end
        if prop == data["property_id"] and overlaps:
            return error_result("UNAVAILABLE", index)
    return None


def build_nights(data):
    rows = []
    for day in range(data["arrival"], data["departure"]):
        season, base = season_terms(day)
        weekend = 1500 if day % 7 in (4, 5) else 0
        rows.append(
            {
                "day": day,
                "season": season,
                "base_cents": base,
                "weekend_cents": weekend,
                "night_cents": base + weekend,
            }
        )
    return rows


def stay_charges(data, nights):
    return (
        (2000 * max(0, data["adults"] - 2) + 1000 * data["children"]) * nights,
        800 * (data["adults"] + data["children"]) * min(nights, 5),
        sum(1200 * nights if item == "PARKING" else 2500 for item in data["extras"]),
    )


def rounded_percent(amount, rate):
    whole, remainder = divmod(amount * rate, 100)
    return whole + int(remainder * 2 >= 100)


def promo_discount(promo, amount, rows):
    if promo == "PCT10":
        return rounded_percent(amount, 10)
    return (
        min(5000, amount)
        if promo == "FIXED5000"
        else min(item["night_cents"] for item in rows)
        if promo == "ONENIGHT"
        else 0
    )


def deposit_amount(total):
    percentage = rounded_percent(total, 30)
    minimum = max(10_000, percentage)
    deposit = min(total, minimum)
    return deposit


def collect_applied(data, rows, amounts):
    active = {label for key, label in APPLIED_AMOUNT_LABELS if amounts[key]}
    active.update({"cleaning", "tourist-tax"})
    active.update(extra.lower() for extra in data["extras"])
    if any(row["weekend_cents"] for row in rows):
        active.add("weekend")
    return [name for name in APPLIED_NAMES if name in active]


def price_components(data, rows):
    subtotal = sum(row["night_cents"] for row in rows)
    guests, tax, extras = stay_charges(data, len(rows))
    return (
        subtotal,
        subtotal + 4500 + guests + tax + extras,
        {"cleaning": 4500, "guests": guests, "tax": tax, "extras": extras},
    )


def price_quote(data, rows):
    subtotal, before, amounts = price_components(data, rows)
    nights = len(rows)
    rate = 15 if nights >= 14 else 10 if nights >= 7 else 0
    long_cut = rounded_percent(subtotal, rate)
    promo_cut = promo_discount(data["promo_code"], before - long_cut, rows)
    total = before - long_cut - promo_cut
    amounts.update(
        long_discount=long_cut,
        promo_discount=promo_cut,
        total=total,
        deposit=deposit_amount(total),
    )
    return amounts


def assemble_quote(data, rows, amounts):
    lead = data["arrival"]
    policy = "FLEX" if lead >= 30 else "STANDARD" if lead >= 7 else "FIRM"
    values = (
        len(rows),
        rows,
        *amounts.values(),
        amounts["total"] - amounts["deposit"],
        collect_applied(data, rows, amounts),
        policy,
    )
    return dict(zip(QUOTE_KEYS, values, strict=True))
