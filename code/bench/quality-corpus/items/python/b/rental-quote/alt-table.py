"""Return an integer-cent rental quote or the first contract error."""


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    data = normalize(request)
    error = validate(data)
    if error:
        return error
    nights = nightly_rows(data)
    return quote(data, nights)


def normalize(request):
    data = dict(request)
    data["property_id"] = request["property_id"].strip().upper()
    data["promo_code"] = request["promo_code"].strip().upper()
    data["extras"] = [value.strip().upper() for value in request["extras"]]
    data["bookings"] = [
        (row["property_id"].strip().upper(), row["arrival"], row["departure"])
        for row in request["bookings"]
    ]
    return data


def validate(data):
    validators = (
        identity_error,
        days_error,
        extras_error,
        bookings_error,
        stay_error,
        season_error,
        availability_error,
        promo_error,
    )
    for validator in validators:
        error = validator(data)
        if error:
            return error


def identity_error(data):
    checks = (
        (data["property_id"] not in ("CEDAR", "LAKE"), "BAD_PROPERTY"),
        (type(data["adults"]) is not int or not 1 <= data["adults"] <= 8, "BAD_ADULTS"),
        (
            type(data["children"]) is not int or not 0 <= data["children"] <= 8,
            "BAD_CHILDREN",
        ),
    )
    return next(({"error": code, "index": None} for bad, code in checks if bad), None)


def days_error(data):
    start, end = data["arrival"], data["departure"]
    invalid = (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start <= 1_000_000
        or not 0 <= end <= 1_000_000
        or end <= start
    )
    return {"error": "BAD_DAYS", "index": None} if invalid else None


def extras_error(data):
    values = data["extras"]
    if len(values) > 4:
        return {"error": "BAD_EXTRA", "index": None}
    return next(
        (
            {"error": "BAD_EXTRA", "index": index}
            for index, value in enumerate(values)
            if value not in ("PARKING", "PET") or value in values[:index]
        ),
        None,
    )


def bookings_error(data):
    rows = data["bookings"]
    if len(rows) > 100:
        return {"error": "BAD_BOOKING", "index": None}
    for index, (prop, start, end) in enumerate(rows):
        invalid = (
            prop not in ("CEDAR", "LAKE")
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        )
        if invalid:
            return {"error": "BAD_BOOKING", "index": index}


def stay_error(data):
    count = data["departure"] - data["arrival"]
    if not 1 <= count <= 30:
        return {"error": "BAD_STAY", "index": None}
    limit = 4 if data["property_id"] == "CEDAR" else 6
    if data["adults"] + data["children"] > limit:
        return {"error": "OVER_CAPACITY", "index": None}


def season_error(data):
    count = data["departure"] - data["arrival"]
    found = set()
    for day in range(data["arrival"], data["departure"]):
        position = day % 365
        found.add("LOW" if position < 120 else "PEAK" if position < 240 else "SHOULDER")
    minima = (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2))
    for name, minimum in minima:
        if name in found and count < minimum:
            return {"error": "MIN_STAY", "index": None}


def availability_error(data):
    start, end, prop = data["arrival"], data["departure"], data["property_id"]
    for index, (booked, first, last) in enumerate(data["bookings"]):
        if booked == prop and start < last and first < end:
            return {"error": "UNAVAILABLE", "index": index}


def promo_error(data):
    if data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return {"error": "BAD_PROMO", "index": None}


def nightly_rows(data):
    rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
    rows = []
    for day in range(data["arrival"], data["departure"]):
        position = day % 365
        name = "LOW" if position < 120 else "PEAK" if position < 240 else "SHOULDER"
        weekend = 1500 if day % 7 in (4, 5) else 0
        rows.append(
            {
                "day": day,
                "season": name,
                "base_cents": rates[name],
                "weekend_cents": weekend,
                "night_cents": rates[name] + weekend,
            }
        )
    return rows


def quote(data, nights):
    subtotal = sum(row["night_cents"] for row in nights)
    count = data["departure"] - data["arrival"]
    parts = fees(data, count, subtotal)
    amounts = quote_amounts(data, nights, subtotal, parts)
    effects = effect_flags(data, nights, amounts)
    return {
        "nights": len(nights),
        "night_lines": nights,
        **fee_fields(data, amounts),
        **discount_fields(amounts, effects),
    }


def quote_amounts(data, nights, subtotal, parts):
    count = data["departure"] - data["arrival"]
    discount = (
        2 * subtotal * (15 if count >= 14 else 10 if count >= 7 else 0) + 100
    ) // 200
    after_long = parts["before"] - discount
    promo = promo_cut(data["promo_code"], after_long, nights)
    total = after_long - promo
    deposit = min(total, max(10000, (2 * total * 30 + 100) // 200))
    amounts = {
        **parts,
        "long": discount,
        "promo": promo,
        "total": total,
        "deposit": deposit,
    }
    return amounts


def fees(data, count, subtotal):
    guests = (2000 * max(0, data["adults"] - 2) + 1000 * data["children"]) * count
    tax = 800 * (data["adults"] + data["children"]) * min(count, 5)
    extra_fees = sum(
        1200 * count if item == "PARKING" else 2500 for item in data["extras"]
    )
    parts = {
        "subtotal": subtotal,
        "cleaning": 4500,
        "guests": guests,
        "tax": tax,
        "extras": extra_fees,
    }
    parts["before"] = sum(parts.values())
    return parts


def promo_cut(code, remaining, nights):
    if code == "PCT10":
        return (2 * remaining * 10 + 100) // 200
    if code == "FIXED5000":
        return min(5000, remaining)
    if code == "ONENIGHT":
        return min(row["night_cents"] for row in nights)
    return 0


def effect_flags(data, nights, amounts):
    return (
        (any(row["weekend_cents"] for row in nights), "weekend"),
        (True, "cleaning"),
        (amounts["guests"] > 0, "extra-guests"),
        (True, "tourist-tax"),
        ("PARKING" in data["extras"], "parking"),
        ("PET" in data["extras"], "pet"),
        (amounts["long"] > 0, "long-stay"),
        (amounts["promo"] > 0, "promo"),
        (amounts["total"] > 0, "deposit"),
    )


def fee_fields(data, amounts):
    policy = (
        "FLEX"
        if data["arrival"] >= 30
        else "STANDARD"
        if data["arrival"] >= 7
        else "FIRM"
    )
    return {
        "cleaning_fee": amounts["cleaning"],
        "extra_guest_fee": amounts["guests"],
        "tourist_tax": amounts["tax"],
        "extras_fee": amounts["extras"],
        "cancellation": policy,
    }


def discount_fields(amounts, effects):
    return {
        "long_stay_discount": amounts["long"],
        "promo_discount": amounts["promo"],
        "total": amounts["total"],
        "deposit": amounts["deposit"],
        "balance_due": amounts["total"] - amounts["deposit"],
        "applied": [name for active, name in effects if active],
    }
