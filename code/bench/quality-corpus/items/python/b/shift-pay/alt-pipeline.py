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
    context = {"role": role, "shifts": request["shifts"], "bonus": request["bonus"]}
    for action in (
        check_request,
        copy_shifts,
        check_shifts,
        check_overlaps,
        calculate_pay,
    ):
        context = action(context)
        if "error" in context:
            return context
    return context["result"]


def check_request(context):
    role, shifts, bonus = context["role"], context["shifts"], context["bonus"]
    checks = (
        (role in BASE_QUARTERS, "BAD_ROLE"),
        (bool(shifts), "EMPTY_WEEK"),
        (len(shifts) <= 14, "TOO_MANY_SHIFTS"),
        (type(bonus) is bool, "BAD_BONUS"),
    )
    for valid, code in checks:
        if not valid:
            return {"error": code, "index": None}
    return context


def copy_shifts(context):
    rows = []
    for index, shift in enumerate(context["shifts"]):
        row = dict(shift)
        row["index"] = index
        rows.append(row)
    return {**context, "rows": rows}


def check_shifts(context):
    rows = context["rows"]
    for row in rows:
        if error := check_fields(row):
            return error
        if error := check_span(row):
            return error
    return context


def check_fields(row):
    index = row["index"]
    for field, high, code in INTEGER_FIELDS:
        value = row[field]
        if type(value) is not int or not 0 <= value <= high:
            return {"error": code, "index": index}
    for field, code in FLAG_FIELDS:
        if type(row[field]) is not bool:
            return {"error": code, "index": index}


def check_span(row):
    duration = (row["end"] - row["start"]) % 1440 or 1440
    if not 1 <= duration <= 960:
        return {"error": "BAD_LENGTH", "index": row["index"]}
    if row["break"] > duration:
        return {"error": "BREAK_TOO_LONG", "index": row["index"]}
    row.update(
        duration=duration,
        paid=duration - (row["break"] if duration > 360 else 0),
        timeline=row["day"] * 1440 + row["start"],
    )


def check_overlaps(context):
    rows = context["rows"]
    conflicts = [
        (start, max(left["index"], right["index"]))
        for i, left in enumerate(rows)
        for right in rows[i + 1 :]
        for offset in WEEK_OFFSETS
        if (start := overlap_start(left, right, offset)) is not None
    ]
    if conflicts:
        return {"error": "OVERLAP", "index": min(conflicts)[1]}
    return context


def overlap_start(left, right, offset):
    begin = max(left["timeline"], right["timeline"] + offset)
    finish = min(
        left["timeline"] + left["duration"],
        right["timeline"] + offset + right["duration"],
    )
    return begin if begin < finish else None


def calculate_pay(context):
    priced, prior = [], 0
    for row in context["rows"]:
        values = minute_values(row, BASE_QUARTERS[context["role"]], prior)
        result = shift_record(row, values, BASE_QUARTERS[context["role"]])
        priced.append(result)
        prior += result["paid_minutes"]
    if context["bonus"] and prior >= 600:
        priced[-1]["bonus_cents"] = 500
        priced[-1]["cents"] = (priced[-1]["_amount"] + 2002) // 4
    return {"result": week_record(priced, prior)}


def minute_values(row, base, prior):
    counts = dict.fromkeys(("regular", "overtime", "night", "weekend", "holiday"), 0)
    amount = 0
    daily = weekly = False
    break_offset = row["break"] if row["duration"] > 360 else 0
    for offset in range(row["paid"]):
        flags = minute_flags(row, base, prior, offset, break_offset)
        amount += tally_minute(counts, flags)
        daily |= flags[5]
        weekly |= flags[6]
    return amount, counts, daily, weekly


def minute_flags(row, base, prior, offset, break_offset):
    absolute = row["timeline"] + offset + break_offset
    day, minute = divmod(absolute, 1440)
    day %= 7
    overtime = offset >= 480 or prior + offset >= 2400
    night, weekend, holiday = minute >= 1320 or minute < 360, day >= 5, row["holiday"]
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


def tally_minute(counts, flags):
    overtime, night, weekend, holiday, rate, _, _ = flags
    counts["overtime" if overtime else "regular"] += 1
    counts["night"] += night
    counts["weekend"] += weekend
    counts["holiday"] += holiday
    return rate


def shift_record(row, values, base):
    amount, counts, daily, weekly = values
    top_up = max(0, 180 - row["paid"]) if row["callout"] else 0
    amount += base * top_up
    data = (
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
    return dict(zip(ROW_FIELDS, data, strict=True))


def week_record(rows, prior):
    visible = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    return {
        "shifts": visible,
        "weekly_paid_minutes": prior,
        "weekly_cents": sum(row["cents"] for row in visible),
        "applied": active_rules(rows),
    }


def active_rules(rows):
    return [
        name for field, name in RULE_FIELDS if any(row[field] for row in rows) is True
    ]
