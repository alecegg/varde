"""Return an integer-cent rental quote or the first contract error."""

NIGHT_KEYS = ("day", "season", "base_cents", "weekend_cents", "night_cents")
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
MINIMUMS = (("LOW", 1), ("PEAK", 3), ("SHOULDER", 2))
FIELD_CODES = ("BAD_PROPERTY", "BAD_ADULTS", "BAD_CHILDREN")


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    data = norm(request)
    if error := verify(data):
        return error
    lines = rows(data)
    return pack(data, lines, money(data, lines))


def norm(request):
    return shape(request)


def shape(request):
    data = dict(request)
    data.update(
        property_id=prop(request["property_id"]),
        extras=[exts(value) for value in request["extras"]],
        bookings=[booknorm(row) for row in request["bookings"]],
        promo_code=code(request["promo_code"]),
    )
    return data


def prop(value):
    return value.strip().upper()


def exts(value):
    return value.strip().upper()


def booknorm(row):
    return prop(row["property_id"]), row["arrival"], row["departure"]


def code(value):
    return value.strip().upper()


def verify(data):
    return checks(data)


def checks(data):
    return scalar(data) or list_errors(data) or rule_errors(data)


def list_errors(data):
    return exok(data["extras"]) or bookok(data["bookings"])


def rule_errors(data):
    return (
        stayok(data)
        or capacityok(data)
        or minimumok(data)
        or overlapok(data)
        or promo_ok(data)
    )


def scalar(data):
    return field_error(data) or day_error(data)


def field_error(data):
    return next(
        (fail(code, None) for valid, code in field_checks(data) if not valid), None
    )


def field_checks(data):
    return zip(field_flags(data), FIELD_CODES, strict=True)


def field_flags(data):
    return (
        data["property_id"] in ("CEDAR", "LAKE"),
        type(data["adults"]) is int and 1 <= data["adults"] <= 8,
        type(data["children"]) is int and 0 <= data["children"] <= 8,
    )


def day_error(data):
    return (
        None if daysok(data["arrival"], data["departure"]) else fail("BAD_DAYS", None)
    )


def daysok(start, end):
    return (
        type(start) is int
        and type(end) is int
        and 0 <= start <= 1_000_000
        and 0 <= end <= 1_000_000
        and end > start
    )


def exok(items):
    if len(items) > 4:
        return fail("BAD_EXTRA", None)
    seen = set()
    for index, value in enumerate(items):
        if value not in ("PARKING", "PET") or value in seen:
            return fail("BAD_EXTRA", index)
        seen.add(value)
    return None


def bookok(items):
    if len(items) > 100:
        return fail("BAD_BOOKING", None)
    for index, (name, start, end) in enumerate(items):
        if name not in ("CEDAR", "LAKE") or not daysok(start, end):
            return fail("BAD_BOOKING", index)
    return None


def stayok(data):
    if not 1 <= data["departure"] - data["arrival"] <= 30:
        return fail("BAD_STAY", None)
    return None


def capacityok(data):
    cap = 4 if data["property_id"] == "CEDAR" else 6
    if data["adults"] + data["children"] > cap:
        return fail("OVER_CAPACITY", None)
    return None


def minimumok(data):
    occupied = {season(day) for day in range(data["arrival"], data["departure"])}
    count = data["departure"] - data["arrival"]
    return fail("MIN_STAY", None) if short_season(occupied, count) else None


def short_season(occupied, count):
    return any(name in occupied and count < minimum for name, minimum in MINIMUMS)


def overlapok(data):
    index = next(
        (i for i, row in enumerate(data["bookings"]) if overlaps(data, row)), None
    )
    return fail("UNAVAILABLE", index) if index is not None else None


def overlaps(data, row):
    name, start, end = row
    return (
        name == data["property_id"]
        and data["arrival"] < end
        and start < data["departure"]
    )


def promo_ok(data):
    if data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return fail("BAD_PROMO", None)
    return None


def rows(data):
    return [line(day) for day in range(data["arrival"], data["departure"])]


def line(day):
    name = season(day)
    base = rate(name)
    extra = wknd(day)
    return dict(zip(NIGHT_KEYS, (day, name, base, extra, base + extra), strict=True))


def season(day):
    value = day % 365
    return "LOW" if value < 120 else "PEAK" if value < 240 else "SHOULDER"


def rate(name):
    return {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}[name]


def wknd(day):
    return 1500 if day % 7 in (4, 5) else 0


def money(data, lines):
    return amounts(data, lines)


def amounts(data, lines):
    return quote_amounts(data, lines)


def quote_amounts(data, lines):
    nights = data["departure"] - data["arrival"]
    subtotal = sum(row["night_cents"] for row in lines)
    fees = fee_parts(data, nights)
    pre = subtotal + sum(fees)
    long, promo, total = reductions(data, lines, subtotal, pre, nights)
    return (nights, *fees, long, promo, total, dep(total))


def fee_parts(data, nights):
    return (
        4500,
        guest(data, nights),
        tourist(data, nights),
        extras_fee(data["extras"], nights),
    )


def reductions(data, lines, subtotal, pre, nights):
    long = discount(subtotal, nights)
    promo = cut(data["promo_code"], pre - long, lines)
    return long, promo, pre - long - promo


def guest(data, nights):
    adults = max(0, data["adults"] - 2)
    return (2000 * adults + 1000 * data["children"]) * nights


def tourist(data, nights):
    return 800 * (data["adults"] + data["children"]) * min(nights, 5)


def extras_fee(items, nights):
    return sum(1200 * nights if item == "PARKING" else 2500 for item in items)


def discount(subtotal, nights):
    rate = 15 if nights >= 14 else 10 if nights >= 7 else 0
    return rhu(subtotal * rate, 100)


def cut(code, net, lines):
    return {
        "PCT10": lambda: rhu(net * 10, 100),
        "FIXED5000": lambda: min(5000, net),
        "ONENIGHT": lambda: min(row["night_cents"] for row in lines),
    }.get(code, lambda: 0)()


def rhu(value, divisor):
    return (2 * value + divisor) // (2 * divisor)


def dep(total):
    return min(total, max(10000, rhu(total * 30, 100)))


def applied(data, lines, values):
    flags = applied_flags(data, lines, values)
    return [name for enabled, name in zip(flags, APPLIED_NAMES, strict=True) if enabled]


def applied_flags(data, lines, values):
    return weekend_flags(lines, values) + other_flags(data, values)


def weekend_flags(lines, values):
    return (
        any(row["weekend_cents"] for row in lines),
        values[1] > 0,
        values[2] > 0,
        values[3] > 0,
    )


def other_flags(data, values):
    return (
        "PARKING" in data["extras"],
        "PET" in data["extras"],
        values[5] > 0,
        values[6] > 0,
        values[7] > 0,
    )


def pack(data, lines, values):
    record = dict(zip(QUOTE_KEYS, values[:1] + (lines,) + values[1:], strict=True))
    total, deposit = values[-2:]
    record.update(
        balance_due=total - deposit,
        applied=applied(data, lines, values),
        cancellation=cancel(data["arrival"]),
    )
    return record


def cancel(arrival):
    return "FLEX" if arrival >= 30 else "STANDARD" if arrival >= 7 else "FIRM"


def fail(code, index):
    return {"error": code, "index": index}
