"""Return an integer-cent rental quote or the first contract error."""


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    data = normalize(request)
    for operation in (check, annotate, make_nights, price, finish):
        data = operation(data)
        if "error" in data:
            return data
    return data["result"]


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


def check(data):
    for validator in (
        identity,
        days,
        extras,
        bookings,
        capacity,
        minimums,
        availability,
    ):
        error = validator(data)
        if error:
            return error
    if data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return {"error": "BAD_PROMO", "index": None}
    return data


def identity(data):
    if data["property_id"] not in ("CEDAR", "LAKE"):
        return {"error": "BAD_PROPERTY", "index": None}
    if type(data["adults"]) is not int or not 1 <= data["adults"] <= 8:
        return {"error": "BAD_ADULTS", "index": None}
    if type(data["children"]) is not int or not 0 <= data["children"] <= 8:
        return {"error": "BAD_CHILDREN", "index": None}


def days(data):
    start, end = data["arrival"], data["departure"]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start <= 1_000_000
        or not 0 <= end <= 1_000_000
        or end <= start
    ):
        return {"error": "BAD_DAYS", "index": None}


def extras(data):
    values = data["extras"]
    if len(values) > 4:
        return {"error": "BAD_EXTRA", "index": None}
    used = set()
    for index, value in enumerate(values):
        if value not in ("PARKING", "PET") or value in used:
            return {"error": "BAD_EXTRA", "index": index}
        used.add(value)


def bookings(data):
    rows = data["bookings"]
    if len(rows) > 100:
        return {"error": "BAD_BOOKING", "index": None}
    for index, (prop, start, end) in enumerate(rows):
        if (
            prop not in ("CEDAR", "LAKE")
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        ):
            return {"error": "BAD_BOOKING", "index": index}


def capacity(data):
    count = data["departure"] - data["arrival"]
    if not 1 <= count <= 30:
        return {"error": "BAD_STAY", "index": None}
    limit = 4 if data["property_id"] == "CEDAR" else 6
    if data["adults"] + data["children"] > limit:
        return {"error": "OVER_CAPACITY", "index": None}


def minimums(data):
    count = data["departure"] - data["arrival"]
    present = set()
    for day in range(data["arrival"], data["departure"]):
        position = day % 365
        present.add(
            "LOW" if position < 120 else "PEAK" if position < 240 else "SHOULDER"
        )
    for name, minimum in (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2)):
        if name in present and count < minimum:
            return {"error": "MIN_STAY", "index": None}


def availability(data):
    start, end, prop = data["arrival"], data["departure"], data["property_id"]
    for index, (booked, first, last) in enumerate(data["bookings"]):
        if booked == prop and start < last and first < end:
            return {"error": "UNAVAILABLE", "index": index}


def annotate(data):
    data["cancellation"] = (
        "FLEX"
        if data["arrival"] >= 30
        else "STANDARD"
        if data["arrival"] >= 7
        else "FIRM"
    )
    return data


def make_nights(data):
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
    return {**data, "nights": rows}


def price(data):
    count = data["departure"] - data["arrival"]
    subtotal = sum(row["night_cents"] for row in data["nights"])
    guests = (2000 * max(0, data["adults"] - 2) + 1000 * data["children"]) * count
    tax = 800 * (data["adults"] + data["children"]) * min(count, 5)
    return {**data, "amounts": price_parts(data, count, subtotal, guests, tax)}


def price_parts(data, count, subtotal, guests, tax):
    extras_total = sum(
        1200 * count if item == "PARKING" else 2500 for item in data["extras"]
    )
    amounts = {
        "cleaning": 4500,
        "guests": guests,
        "tax": tax,
        "extras": extras_total,
        "subtotal": subtotal,
    }
    amounts["pre_discount"] = subtotal + 4500 + guests + tax + extras_total
    return amounts


def finish(data):
    amounts = data["amounts"]
    count = data["departure"] - data["arrival"]
    rate = 15 if count >= 14 else 10 if count >= 7 else 0
    long_cut = (2 * amounts["subtotal"] * rate + 100) // 200
    remaining = amounts["pre_discount"] - long_cut
    promo_cut = promo_amount(data["promo_code"], remaining, data["nights"])
    total = remaining - promo_cut
    amounts.update(
        long_cut=long_cut,
        promo_cut=promo_cut,
        total=total,
        deposit=min(total, max(10000, (2 * total * 30 + 100) // 200)),
    )
    return {"result": quote_fields(data, amounts)}


def quote_fields(data, amounts):
    return {
        "nights": len(data["nights"]),
        "night_lines": data["nights"],
        "applied": labels(data, amounts),
        **cash_fields(data, amounts),
    }


def cash_fields(data, amounts):
    total = amounts["total"]
    result = {
        "cleaning_fee": amounts["cleaning"],
        "extra_guest_fee": amounts["guests"],
        "tourist_tax": amounts["tax"],
        "extras_fee": amounts["extras"],
        "long_stay_discount": amounts["long_cut"],
        "promo_discount": amounts["promo_cut"],
        "total": total,
        "deposit": amounts["deposit"],
        "balance_due": total - amounts["deposit"],
        "cancellation": data["cancellation"],
    }
    return result


def promo_amount(code, remaining, nights):
    if code == "PCT10":
        return (2 * remaining * 10 + 100) // 200
    if code == "FIXED5000":
        return min(5000, remaining)
    if code == "ONENIGHT":
        return min(row["night_cents"] for row in nights)
    return 0


def labels(data, amounts):
    return [
        name
        for enabled, name in (
            (any(row["weekend_cents"] for row in data["nights"]), "weekend"),
            (True, "cleaning"),
            (amounts["guests"] > 0, "extra-guests"),
            (True, "tourist-tax"),
            ("PARKING" in data["extras"], "parking"),
            ("PET" in data["extras"], "pet"),
            (amounts["long_cut"], "long-stay"),
            (amounts["promo_cut"], "promo"),
            (amounts["total"], "deposit"),
        )
        if enabled
    ]
