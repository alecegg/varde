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
    data = normalize_quote(request)
    if error := validate_quote(data):
        return error
    lines = quote_nights(data)
    return success_quote(data, lines, price_quote(data, lines))


def normalize_quote(request):
    return normalized_request(request)


def normalized_request(request):
    data = dict(request)
    data.update(
        property_id=normalize_property(request["property_id"]),
        extras=[normalize_extra(value) for value in request["extras"]],
        bookings=[normalize_booking(row) for row in request["bookings"]],
        promo_code=normalize_promo(request["promo_code"]),
    )
    return data


def normalize_property(value):
    return value.strip().upper()


def normalize_extra(value):
    return value.strip().upper()


def normalize_booking(row):
    return (normalize_property(row["property_id"]), row["arrival"], row["departure"])


def normalize_promo(value):
    return value.strip().upper()


def validate_quote(data):
    return validation_checks(data)


def validation_checks(data):
    return validate_scalar(data) or validate_lists(data) or validate_rules(data)


def validate_lists(data):
    return validate_extras(data["extras"]) or validate_bookings(data["bookings"])


def validate_rules(data):
    return (
        validate_stay_length(data)
        or validate_occupancy(data)
        or validate_season_minimums(data)
        or validate_availability(data)
        or validate_promo(data)
    )


def validate_scalar(data):
    return scalar_error(data) or validate_days_error(data)


def scalar_error(data):
    return next(
        (error_result(code, None) for valid, code in scalar_checks(data) if not valid),
        None,
    )


def scalar_checks(data):
    return zip(scalar_flags(data), FIELD_CODES, strict=True)


def scalar_flags(data):
    return (
        data["property_id"] in ("CEDAR", "LAKE"),
        type(data["adults"]) is int and 1 <= data["adults"] <= 8,
        type(data["children"]) is int and 0 <= data["children"] <= 8,
    )


def validate_days_error(data):
    return (
        None
        if valid_day_range(data["arrival"], data["departure"])
        else error_result("BAD_DAYS", None)
    )


def valid_day_range(start, end):
    return (
        type(start) is int
        and type(end) is int
        and (0 <= start <= 1000000)
        and (0 <= end <= 1000000)
        and (end > start)
    )


def validate_extras(items):
    if len(items) > 4:
        return error_result("BAD_EXTRA", None)
    seen = set()
    for index, value in enumerate(items):
        if value not in ("PARKING", "PET") or value in seen:
            return error_result("BAD_EXTRA", index)
        seen.add(value)
    return None


def validate_bookings(items):
    if len(items) > 100:
        return error_result("BAD_BOOKING", None)
    for index, (name, start, end) in enumerate(items):
        if name not in ("CEDAR", "LAKE") or not valid_day_range(start, end):
            return error_result("BAD_BOOKING", index)
    return None


def validate_stay_length(data):
    if not 1 <= data["departure"] - data["arrival"] <= 30:
        return error_result("BAD_STAY", None)
    return None


def validate_occupancy(data):
    cap = 4 if data["property_id"] == "CEDAR" else 6
    if data["adults"] + data["children"] > cap:
        return error_result("OVER_CAPACITY", None)
    return None


def validate_season_minimums(data):
    occupied = {
        season_for_day(day) for day in range(data["arrival"], data["departure"])
    }
    count = data["departure"] - data["arrival"]
    return error_result("MIN_STAY", None) if minimum_fails(occupied, count) else None


def minimum_fails(occupied, count):
    return any((name in occupied and count < minimum for name, minimum in MINIMUMS))


def validate_availability(data):
    index = next(
        (i for i, row in enumerate(data["bookings"]) if booking_overlaps(data, row)),
        None,
    )
    return error_result("UNAVAILABLE", index) if index is not None else None


def booking_overlaps(data, row):
    name, start, end = row
    return (
        name == data["property_id"]
        and data["arrival"] < end
        and (start < data["departure"])
    )


def validate_promo(data):
    if data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
        return error_result("BAD_PROMO", None)
    return None


def quote_nights(data):
    return [quote_night(day) for day in range(data["arrival"], data["departure"])]


def quote_night(day):
    name = season_for_day(day)
    base = base_rate_for_season(name)
    extra = weekend_surcharge(day)
    return dict(zip(NIGHT_KEYS, (day, name, base, extra, base + extra), strict=True))


def season_for_day(day):
    value = day % 365
    return "LOW" if value < 120 else "PEAK" if value < 240 else "SHOULDER"


def base_rate_for_season(name):
    return {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}[name]


def weekend_surcharge(day):
    return 1500 if day % 7 in (4, 5) else 0


def price_quote(data, lines):
    return price_amounts(data, lines)


def price_amounts(data, lines):
    return price_components(data, lines)


def price_components(data, lines):
    nights = data["departure"] - data["arrival"]
    subtotal = sum((row["night_cents"] for row in lines))
    fees = fee_amounts(data, nights)
    pre = subtotal + sum(fees)
    long, promo, total = discount_amounts(data, lines, subtotal, pre, nights)
    return nights, *fees, long, promo, total, deposit_amount(total)


def fee_amounts(data, nights):
    return (
        4500,
        extra_guest_fee(data, nights),
        tourist_tax(data, nights),
        extras_total(data["extras"], nights),
    )


def discount_amounts(data, lines, subtotal, pre, nights):
    long = long_stay_discount(subtotal, nights)
    promo = promo_discount(data["promo_code"], pre - long, lines)
    return (long, promo, pre - long - promo)


def extra_guest_fee(data, nights):
    adults = max(0, data["adults"] - 2)
    return (2000 * adults + 1000 * data["children"]) * nights


def tourist_tax(data, nights):
    return 800 * (data["adults"] + data["children"]) * min(nights, 5)


def extras_total(items, nights):
    return sum((1200 * nights if item == "PARKING" else 2500 for item in items))


def long_stay_discount(subtotal, nights):
    rate = 15 if nights >= 14 else 10 if nights >= 7 else 0
    return round_half_up(subtotal * rate, 100)


def promo_discount(code, net, lines):
    return {
        "PCT10": lambda: round_half_up(net * 10, 100),
        "FIXED5000": lambda: min(5000, net),
        "ONENIGHT": lambda: min((row["night_cents"] for row in lines)),
    }.get(code, lambda: 0)()


def round_half_up(value, divisor):
    return (2 * value + divisor) // (2 * divisor)


def deposit_amount(total):
    return min(total, max(10000, round_half_up(total * 30, 100)))


def applied_adjustments(data, lines, values):
    flags = adjustment_flags(data, lines, values)
    return [name for enabled, name in zip(flags, APPLIED_NAMES, strict=True) if enabled]


def adjustment_flags(data, lines, values):
    return night_flags(lines, values) + fee_flags(data, values)


def night_flags(lines, values):
    return (
        any((row["weekend_cents"] for row in lines)),
        values[1] > 0,
        values[2] > 0,
        values[3] > 0,
    )


def fee_flags(data, values):
    return (
        "PARKING" in data["extras"],
        "PET" in data["extras"],
        values[5] > 0,
        values[6] > 0,
        values[7] > 0,
    )


def success_quote(data, lines, values):
    record = dict(zip(QUOTE_KEYS, values[:1] + (lines,) + values[1:], strict=True))
    total, deposit = values[-2:]
    record.update(
        balance_due=total - deposit,
        applied=applied_adjustments(data, lines, values),
        cancellation=cancellation_policy(data["arrival"]),
    )
    return record


def cancellation_policy(arrival):
    return "FLEX" if arrival >= 30 else "STANDARD" if arrival >= 7 else "FIRM"


def error_result(code, index):
    return {"error": code, "index": index}
