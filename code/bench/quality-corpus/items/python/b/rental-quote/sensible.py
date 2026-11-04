"""Return an integer-cent rental quote or the first contract error."""


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    data = normalise(request)
    error = validate(data)
    if error:
        return error
    arrival = data["arrival"]
    data["cancellation"] = (
        "FLEX" if arrival >= 30 else "STANDARD" if arrival >= 7 else "FIRM"
    )
    nights = build_nights(data)
    amounts = price_stay(data, nights)
    return assemble(data, nights, amounts)


def normalise(request):
    data = dict(request)
    data["property_id"] = request["property_id"].strip().upper()
    data["promo_code"] = request["promo_code"].strip().upper()
    data["extras"] = [item.strip().upper() for item in request["extras"]]
    data["bookings"] = [
        (row["property_id"].strip().upper(), row["arrival"], row["departure"])
        for row in request["bookings"]
    ]
    return data


def validate(data):
    checks = (
        validate_identity,
        validate_days,
        validate_extras,
        validate_bookings,
        validate_stay_capacity,
        validate_minimums,
        validate_availability,
    )
    for check in checks:
        error = check(data)
        if error:
            return error
    if data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return {"error": "BAD_PROMO", "index": None}


def validate_identity(data):
    prop = data["property_id"]
    adults, children = data["adults"], data["children"]
    if prop not in ("CEDAR", "LAKE"):
        return {"error": "BAD_PROPERTY", "index": None}
    if type(adults) is not int or not 1 <= adults <= 8:
        return {"error": "BAD_ADULTS", "index": None}
    if type(children) is not int or not 0 <= children <= 8:
        return {"error": "BAD_CHILDREN", "index": None}


def validate_days(data):
    start, end = data["arrival"], data["departure"]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start <= 1_000_000
        or not 0 <= end <= 1_000_000
        or end <= start
    ):
        return {"error": "BAD_DAYS", "index": None}


def validate_extras(data):
    extras = data["extras"]
    if len(extras) > 4:
        return {"error": "BAD_EXTRA", "index": None}
    used = set()
    for index, item in enumerate(extras):
        if item not in ("PARKING", "PET") or item in used:
            return {"error": "BAD_EXTRA", "index": index}
        used.add(item)


def validate_bookings(data):
    bookings = data["bookings"]
    if len(bookings) > 100:
        return {"error": "BAD_BOOKING", "index": None}
    for index, (prop, start, end) in enumerate(bookings):
        if (
            prop not in ("CEDAR", "LAKE")
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        ):
            return {"error": "BAD_BOOKING", "index": index}


def validate_stay_capacity(data):
    nights = data["departure"] - data["arrival"]
    if not 1 <= nights <= 30:
        return {"error": "BAD_STAY", "index": None}
    capacity = 4 if data["property_id"] == "CEDAR" else 6
    guests = data["adults"] + data["children"]
    if guests > capacity:
        return {"error": "OVER_CAPACITY", "index": None}


def validate_minimums(data):
    nights = data["departure"] - data["arrival"]
    counts = {"LOW": 0, "PEAK": 0, "SHOULDER": 0}
    for day in range(data["arrival"], data["departure"]):
        counts[season_for(day)] += 1
    for season, minimum in (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2)):
        if counts[season] and nights < minimum:
            return {"error": "MIN_STAY", "index": None}


def validate_availability(data):
    prop, start, end = data["property_id"], data["arrival"], data["departure"]
    for index, (booked_prop, booked_start, booked_end) in enumerate(data["bookings"]):
        overlap = start < booked_end and booked_start < end
        if booked_prop == prop and overlap:
            return {"error": "UNAVAILABLE", "index": index}


def season_for(day):
    position = day % 365
    season = "LOW" if position < 120 else "PEAK" if position < 240 else "SHOULDER"
    return season


def build_nights(data):
    rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
    rows = []
    for day in range(data["arrival"], data["departure"]):
        season = season_for(day)
        weekend = 1500 if day % 7 in (4, 5) else 0
        base = rates[season]
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


def price_stay(data, nights):
    count = data["departure"] - data["arrival"]
    subtotal = sum(row["night_cents"] for row in nights)
    cleaning = 4500
    guests, tax = guest_charges(data, count)
    extras = sum(1200 * count if item == "PARKING" else 2500 for item in data["extras"])
    pre_discount = subtotal + cleaning + guests + tax + extras
    return {
        "cleaning": cleaning,
        "guests": guests,
        "tax": tax,
        "extras": extras,
        "pre_discount": pre_discount,
        "subtotal": subtotal,
    }


def guest_charges(data, count):
    extra_adults = max(0, data["adults"] - 2)
    guests = (2000 * extra_adults + 1000 * data["children"]) * count
    guest_count = data["adults"] + data["children"]
    taxed_nights = min(count, 5)
    tax = 800 * guest_count * taxed_nights
    return guests, tax


def discounts(data, nights, amounts):
    count = data["departure"] - data["arrival"]
    rate = 15 if count >= 14 else 10 if count >= 7 else 0
    long_cut = (2 * amounts["subtotal"] * rate + 100) // 200
    remaining = amounts["pre_discount"] - long_cut
    promo_cut = promo_amount(data["promo_code"], remaining, nights)
    total = remaining - promo_cut
    deposit = min(total, max(10000, (2 * total * 30 + 100) // 200))
    amounts.update(long_cut=long_cut, promo_cut=promo_cut, total=total, deposit=deposit)
    return amounts


def promo_amount(promo, remaining, nights):
    if promo == "PCT10":
        return (2 * remaining * 10 + 100) // 200
    if promo == "FIXED5000":
        return min(5000, remaining)
    if promo == "ONENIGHT":
        return min(row["night_cents"] for row in nights)
    return 0


def assemble(data, nights, amounts):
    amounts = discounts(data, nights, amounts)
    applied = applied_names(data, nights, amounts)
    return quote_result(data, nights, amounts, applied)


def quote_result(data, nights, amounts, applied):
    return {
        "nights": len(nights),
        "night_lines": nights,
        "cleaning_fee": amounts["cleaning"],
        "extra_guest_fee": amounts["guests"],
        "tourist_tax": amounts["tax"],
        "extras_fee": amounts["extras"],
        "long_stay_discount": amounts["long_cut"],
        "promo_discount": amounts["promo_cut"],
        "total": amounts["total"],
        "deposit": amounts["deposit"],
        "balance_due": amounts["total"] - amounts["deposit"],
        "applied": applied,
        "cancellation": data["cancellation"],
    }


def applied_names(data, nights, amounts):
    applied = []
    for enabled, label in applied_effects(data, nights, amounts):
        if enabled:
            applied.append(label)
    return applied


def applied_effects(data, nights, amounts):
    effects = (
        (any(row["weekend_cents"] for row in nights), "weekend"),
        (True, "cleaning"),
        (amounts["guests"] > 0, "extra-guests"),
        (True, "tourist-tax"),
        ("PARKING" in data["extras"], "parking"),
        ("PET" in data["extras"], "pet"),
        (amounts["long_cut"] > 0, "long-stay"),
        (amounts["promo_cut"] > 0, "promo"),
        (amounts["total"] > 0, "deposit"),
    )
    return effects
