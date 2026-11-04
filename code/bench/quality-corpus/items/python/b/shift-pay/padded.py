"""Calculate weekly shift pay using exact integer-minute arithmetic."""

from collections import defaultdict
from itertools import combinations

BASE_RATES = {"helper": 120, "nurse": 160, "lead": 200}
REQUEST_CHECKS = ("BAD_ROLE", "EMPTY_WEEK", "TOO_MANY_SHIFTS", "BAD_BONUS")
INTEGER_FIELDS = (
    ("day", 6, "BAD_DAY"),
    ("start", 1439, "BAD_START"),
    ("end", 1439, "BAD_END"),
    ("break", 240, "BAD_BREAK"),
)
FLAG_FIELDS = (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT"))
WEEK_OFFSETS = (-10080, 0, 10080)
COUNT_FIELDS = ("regular", "overtime", "night", "weekend", "holiday")
ADD_FIELDS = (("night", 3), ("weekend", 4), ("holiday", 5))
ROW_FIELDS = (
    "day",
    "start",
    "end",
    "paid_minutes",
    "regular_minutes",
    "overtime_minutes",
    "night_minutes",
    "weekend_minutes",
    "holiday_minutes",
    "callout_minutes",
    "bonus_cents",
    "cents",
)
RULE_FIELDS = (
    ("daily", "daily-overtime"),
    ("weekly", "weekly-overtime"),
    ("night", "night-premium"),
    ("weekend", "weekend-premium"),
    ("holiday", "holiday-rate"),
    ("callout", "callout-minimum"),
    ("bonus", "bonus"),
)


def solution(request):
    """Return ordered shift pay rows or the first contract validation error."""
    context = normalize_input(request)
    return (
        check_request(context)
        or validate_week(context["rows"])
        or assemble_result(price_week(context))
    )


def normalize_input(request):
    rows = [{**shift, "index": index} for index, shift in enumerate(request["shifts"])]
    return {
        "role": request["role"].strip().lower(),
        "rows": rows,
        "bonus": request["bonus"],
    }


def check_request(context):
    rows = context["rows"]
    checks = (
        context["role"] in BASE_RATES,
        bool(rows),
        len(rows) <= 14,
        type(context["bonus"]) is bool,
    )
    for valid, code in zip(checks, REQUEST_CHECKS, strict=True):
        if not valid:
            return error_record(code, None)


def error_record(code, index):
    fields = (("error", code), ("index", index))
    return dict(fields)


def validate_week(rows):
    for row in rows:
        failure = check_row_fields(row)
        if failure:
            return failure
        failure = check_duration(row)
        if failure:
            return failure
        failure = set_shift_times(row)
        if failure:
            return failure
    return overlap_error(rows)


def check_row_fields(row):
    index = row["index"]
    for field, maximum, code in INTEGER_FIELDS:
        if type(row[field]) is not int or not 0 <= row[field] <= maximum:
            return error_record(code, index)
    for field, code in FLAG_FIELDS:
        if type(row[field]) is not bool:
            return error_record(code, index)


def check_duration(row):
    duration = (row["end"] - row["start"]) % 1440 or 1440
    if not 1 <= duration <= 960:
        return error_record("BAD_LENGTH", row["index"])
    row["duration"] = duration


def set_shift_times(row):
    duration = row["duration"]
    if row["break"] > duration:
        return error_record("BREAK_TOO_LONG", row["index"])
    return store_shift_times(row, duration)


def store_shift_times(row, duration):
    timeline = row["day"] * 1440 + row["start"]
    unpaid = row["break"] if duration > 360 else 0
    row.update(
        paid=duration - unpaid,
        timeline=timeline,
        paid_start=timeline + unpaid,
    )


def overlap_error(rows):
    collisions = [
        (start, max(left["index"], right["index"]))
        for left, right in combinations(rows, 2)
        for offset in WEEK_OFFSETS
        if (start := overlap_start(left, right, offset)) is not None
    ]
    if collisions:
        return error_record("OVERLAP", min(collisions)[1])


def overlap_start(left, right, offset):
    left_start = left["timeline"]
    right_start = right["timeline"] + offset
    shared_start = max(left_start, right_start)
    shared_end = min(left_start + left["duration"], right_start + right["duration"])
    if shared_start >= shared_end:
        return None
    return shared_start


def price_week(context):
    base = BASE_RATES[context["role"]]
    prior = 0
    rows = []
    for row in context["rows"]:
        rows.append(price_shift(row, base, prior))
        prior += row["paid"]
    apply_bonus(rows, prior, context["bonus"])
    return rows, prior


def minute_totals(row, base, prior):
    totals = defaultdict(int)
    for offset in range(row["paid"]):
        terms = minute_terms(row, row["paid_start"] + offset, offset, prior)
        count_minute(totals, terms, base)
        for field, position in ADD_FIELDS:
            totals[field] += terms[position]
    return totals


def count_minute(totals, terms, base):
    totals["overtime" if terms[2] else "regular"] += 1
    totals["amount"] += minute_amount(base, terms)
    totals["daily"] |= terms[0]
    totals["weekly"] |= terms[1]


def minute_terms(row, absolute, offset, prior):
    day, minute = divmod(absolute, 1440)
    daily = offset >= 480
    weekly = prior + offset >= 2400
    overtime = daily or weekly
    night = minute >= 1320 or minute < 360
    weekend = day % 7 >= 5
    holiday = row["holiday"]
    return daily, weekly, overtime, night, weekend, holiday


def minute_amount(base, terms):
    overtime_amount = base // 2 if terms[2] else 0
    night_amount = base // 5 if terms[3] else 0
    weekend_amount = base // 4 if terms[4] else 0
    holiday_amount = base if terms[5] else 0
    return base + overtime_amount + night_amount + weekend_amount + holiday_amount


def price_shift(row, base, prior):
    totals = minute_totals(row, base, prior)
    missing = 180 - row["paid"]
    top_up = missing if row["callout"] and missing > 0 else 0
    totals["amount"] += base * top_up
    totals["callout"] = top_up
    totals["bonus"] = 0
    return row, totals


def apply_bonus(rows, weekly_paid, requested):
    if requested and weekly_paid >= 600:
        totals = rows[-1][1]
        totals["amount"] += 2000
        totals["bonus"] = 500


def pay_values(totals):
    cents = (totals["amount"] + 2) // 4
    counts = tuple(totals[field] for field in COUNT_FIELDS)
    return counts + (totals["callout"], totals["bonus"], cents)


def public_shift(priced):
    row = priced[0]
    totals = priced[1]
    identity = (row["day"], row["start"], row["end"], row["paid"])
    return dict(zip(ROW_FIELDS, identity + pay_values(totals), strict=True))


def applied_rules(priced_rows):
    applied = []
    for field, name in RULE_FIELDS:
        active = any(totals[field] for _, totals in priced_rows)
        if active:
            applied.append(name)
    return applied


def assemble_result(pricing):
    priced = pricing[0]
    shifts = [public_shift(row) for row in priced]
    return {
        "shifts": shifts,
        "weekly_paid_minutes": pricing[1],
        "weekly_cents": sum(row["cents"] for row in shifts),
        "applied": applied_rules(priced),
    }
