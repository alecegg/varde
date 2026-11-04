"""Calculate weekly shift pay using exact integer-minute arithmetic."""

BASE_QUARTERS = {"helper": 120, "nurse": 160, "lead": 200}
INTEGER_FIELDS = (
    ("day", 6, "BAD_DAY"),
    ("start", 1439, "BAD_START"),
    ("end", 1439, "BAD_END"),
    ("break", 240, "BAD_BREAK"),
)
FLAG_FIELDS = (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT"))
WEEK_OFFSETS = (-10080, 0, 10080)
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
    "_amount",
    "_daily",
    "_weekly",
)
RULE_FIELDS = (
    ("_daily", "daily-overtime"),
    ("_weekly", "weekly-overtime"),
    ("night_minutes", "night-premium"),
    ("weekend_minutes", "weekend-premium"),
    ("holiday_minutes", "holiday-rate"),
    ("callout_minutes", "callout-minimum"),
    ("bonus_cents", "bonus"),
)


def solution(request):
    """Return ordered shift pay rows or the first contract validation error."""
    role = request["role"].strip().lower()
    shifts, bonus = request["shifts"], request["bonus"]
    if failure := validate_request(role, shifts, bonus):
        return failure
    rows = normalize_shifts(shifts)
    if failure := validate_rows(rows):
        return failure
    if failure := overlap_error(rows):
        return failure
    return price_week(role, rows, bonus)


def validate_request(role, shifts, bonus):
    for valid, code in (
        (role in BASE_QUARTERS, "BAD_ROLE"),
        (bool(shifts), "EMPTY_WEEK"),
        (len(shifts) <= 14, "TOO_MANY_SHIFTS"),
        (type(bonus) is bool, "BAD_BONUS"),
    ):
        if not valid:
            return {"error": code, "index": None}


def normalize_shifts(shifts):
    rows = []
    for index, shift in enumerate(shifts):
        row = dict(shift)
        row["index"] = index
        rows.append(row)
    return rows


def validate_rows(shifts):
    for row in shifts:
        if failure := validate_fields(row):
            return failure
        if failure := validate_duration(row):
            return failure


def validate_fields(row):
    index = row["index"]
    for field, high, code in INTEGER_FIELDS:
        value = row[field]
        if type(value) is not int or not 0 <= value <= high:
            return {"error": code, "index": index}
    for field, code in FLAG_FIELDS:
        if type(row[field]) is not bool:
            return {"error": code, "index": index}


def validate_duration(row):
    duration = (row["end"] - row["start"]) % 1440 or 1440
    if not 1 <= duration <= 960:
        return {"error": "BAD_LENGTH", "index": row["index"]}
    if row["break"] > duration:
        return {"error": "BREAK_TOO_LONG", "index": row["index"]}
    unpaid = row["break"] if duration > 360 else 0
    row.update(
        duration=duration,
        paid=duration - unpaid,
        timeline=row["day"] * 1440 + row["start"],
    )


def overlap_error(shifts):
    collisions = [
        (start, max(left["index"], right["index"]))
        for i, left in enumerate(shifts)
        for right in shifts[i + 1 :]
        for offset in WEEK_OFFSETS
        if (start := overlap_start(left, right, offset)) is not None
    ]
    if collisions:
        return {"error": "OVERLAP", "index": min(collisions)[1]}


def overlap_start(left, right, offset):
    start = max(left["timeline"], right["timeline"] + offset)
    end = min(
        left["timeline"] + left["duration"],
        right["timeline"] + offset + right["duration"],
    )
    return start if start < end else None


def price_week(role, shifts, bonus):
    rows, prior = [], 0
    for row in shifts:
        totals = minute_totals(row, BASE_QUARTERS[role], prior)
        priced = price_shift(row, totals, BASE_QUARTERS[role])
        rows.append(priced)
        prior += priced["paid_minutes"]
    if bonus and prior >= 600:
        rows[-1]["bonus_cents"] = 500
        rows[-1]["cents"] = (rows[-1]["_amount"] + 2002) // 4
    return weekly_record(rows, prior)


def weekly_record(rows, prior):
    active = applied_rules(rows)
    public_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    return {
        "shifts": public_rows,
        "weekly_paid_minutes": prior,
        "weekly_cents": sum(row["cents"] for row in public_rows),
        "applied": active,
    }


def price_shift(row, totals, base):
    amount, counts, daily, weekly = totals
    top_up = max(0, 180 - row["paid"]) if row["callout"] else 0
    amount += base * top_up
    values = (
        row["day"],
        row["start"],
        row["end"],
        row["paid"],
        counts["regular"],
        counts["overtime"],
        counts["night"],
        counts["weekend"],
        counts["holiday"],
        top_up,
        0,
        (amount + 2) // 4,
        amount,
        daily,
        weekly,
    )
    return dict(zip(ROW_FIELDS, values, strict=True))


def minute_totals(row, base, prior):
    amount = 0
    counts = dict.fromkeys(("regular", "overtime", "night", "weekend", "holiday"), 0)
    daily = weekly = False
    break_offset = row["break"] if row["duration"] > 360 else 0
    for offset in range(row["paid"]):
        flags = minute_flags(row, base, prior, offset, break_offset)
        amount += count_minute(counts, flags)
        daily |= flags[5]
        weekly |= flags[6]
    return amount, counts, daily, weekly


def minute_flags(row, base, prior, offset, break_offset):
    absolute = row["timeline"] + offset + break_offset
    day, minute = divmod(absolute, 1440)
    day %= 7
    overtime = offset >= 480 or prior + offset >= 2400
    night = minute >= 1320 or minute < 360
    weekend = day >= 5
    holiday = row["holiday"]
    rate = (
        base
        + base // 2 * overtime
        + base // 5 * night
        + base // 4 * weekend
        + base * holiday
    )
    return (
        overtime,
        night,
        weekend,
        holiday,
        rate,
        offset >= 480,
        prior + offset >= 2400,
    )


def count_minute(counts, flags):
    overtime, night, weekend, holiday, rate, _, _ = flags
    counts["overtime" if overtime else "regular"] += 1
    counts["night"] += night
    counts["weekend"] += weekend
    counts["holiday"] += holiday
    return rate


def applied_rules(rows):
    return [
        name for field, name in RULE_FIELDS if any(row[field] for row in rows) is True
    ]
