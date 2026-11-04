def solution(request):  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Return ordered shift pay rows or the first contract validation error."""
    role = request["role"].strip().lower()
    shifts = request["shifts"]
    bonus = request["bonus"]
    rates = {"helper": 120, "nurse": 160, "lead": 200}
    if role not in rates:
        return {"error": "BAD_ROLE", "index": None}
    if not shifts:
        return {"error": "EMPTY_WEEK", "index": None}
    if len(shifts) > 14:
        return {"error": "TOO_MANY_SHIFTS", "index": None}
    if type(bonus) is not bool:
        return {"error": "BAD_BONUS", "index": None}

    rows = []
    for index, source in enumerate(shifts):
        row = dict(source)
        day = row["day"]
        if type(day) is not int:
            return {"error": "BAD_DAY", "index": index}
        if day < 0 or day > 6:
            return {"error": "BAD_DAY", "index": index}
        start = row["start"]
        if type(start) is not int:
            return {"error": "BAD_START", "index": index}
        if start < 0 or start > 1439:
            return {"error": "BAD_START", "index": index}
        end = row["end"]
        if type(end) is not int:
            return {"error": "BAD_END", "index": index}
        if end < 0 or end > 1439:
            return {"error": "BAD_END", "index": index}
        break_minutes = row["break"]
        if type(break_minutes) is not int:
            return {"error": "BAD_BREAK", "index": index}
        if break_minutes < 0 or break_minutes > 240:
            return {"error": "BAD_BREAK", "index": index}
        if type(row["holiday"]) is not bool:
            return {"error": "BAD_HOLIDAY", "index": index}
        if type(row["callout"]) is not bool:
            return {"error": "BAD_CALLOUT", "index": index}
        duration = (row["end"] - row["start"]) % 1440
        if duration == 0:
            duration = 1440
        if duration < 1 or duration > 960:
            return {"error": "BAD_LENGTH", "index": index}
        if row["break"] > duration:
            return {"error": "BREAK_TOO_LONG", "index": index}
        unpaid = row["break"] if duration > 360 else 0
        row["index"] = index
        row["duration"] = duration
        row["paid"] = duration - unpaid
        row["timeline"] = row["day"] * 1440 + row["start"]
        rows.append(row)

    collisions = []
    for left_position, left in enumerate(rows):
        for right in rows[left_position + 1 :]:
            for shift_offset in (-10080, 0, 10080):
                later_start = right["timeline"] + shift_offset
                overlap_begin = max(left["timeline"], later_start)
                overlap_end = min(
                    left["timeline"] + left["duration"],
                    later_start + right["duration"],
                )
                if overlap_begin < overlap_end:
                    collisions.append(
                        (overlap_begin, max(left["index"], right["index"]))
                    )
    if collisions:
        return {"error": "OVERLAP", "index": min(collisions)[1]}

    priced = []
    prior = 0
    for row in rows:
        base = rates[role]
        amount = 0
        regular = overtime = night = weekend = holiday_minutes = 0
        daily_used = weekly_used = False
        break_offset = row["break"] if row["duration"] > 360 else 0
        for minute_offset in range(row["paid"]):
            absolute = row["timeline"] + break_offset + minute_offset
            day_number, local_minute = divmod(absolute, 1440)
            day_number %= 7
            daily_overtime = minute_offset >= 480
            weekly_overtime = prior + minute_offset >= 2400
            is_overtime = daily_overtime or weekly_overtime
            is_night = local_minute >= 1320 or local_minute < 360
            is_weekend = day_number >= 5
            is_holiday = row["holiday"]
            regular += not is_overtime
            overtime += is_overtime
            night += is_night
            weekend += is_weekend
            holiday_minutes += is_holiday
            daily_used |= daily_overtime
            weekly_used |= weekly_overtime
            minute_amount = base
            if is_overtime:
                overtime_addition = base // 2
                minute_amount += overtime_addition
            if is_night:
                night_addition = base // 5
                minute_amount += night_addition
            if is_weekend:
                weekend_addition = base // 4
                minute_amount += weekend_addition
            if is_holiday:
                holiday_addition = base
                minute_amount += holiday_addition
            amount += minute_amount
        callout_minutes = max(0, 180 - row["paid"]) if row["callout"] else 0
        amount += base * callout_minutes
        priced.append(
            {
                "day": row["day"],
                "start": row["start"],
                "end": row["end"],
                "paid_minutes": row["paid"],
                "regular_minutes": regular,
                "overtime_minutes": overtime,
                "night_minutes": night,
                "weekend_minutes": weekend,
                "holiday_minutes": holiday_minutes,
                "callout_minutes": callout_minutes,
                "bonus_cents": 0,
                "cents": (amount + 2) // 4,
                "_amount": amount,
                "_daily": daily_used,
                "_weekly": weekly_used,
            }
        )
        prior += row["paid"]
    if bonus and prior >= 600:
        priced[-1]["bonus_cents"] = 500
        priced[-1]["cents"] = (priced[-1]["_amount"] + 2002) // 4

    applied = []
    for field, name in (
        ("_daily", "daily-overtime"),
        ("_weekly", "weekly-overtime"),
        ("night_minutes", "night-premium"),
        ("weekend_minutes", "weekend-premium"),
        ("holiday_minutes", "holiday-rate"),
        ("callout_minutes", "callout-minimum"),
        ("bonus_cents", "bonus"),
    ):
        if any(row[field] for row in priced):
            applied.append(name)
    public_rows = []
    weekly_cents = 0
    visible_fields = (
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
    for row in priced:
        public_row = {}
        for field in visible_fields:
            public_row[field] = row[field]
        public_rows.append(public_row)
        weekly_cents += public_row["cents"]
    return {
        "shifts": public_rows,
        "weekly_paid_minutes": prior,
        "weekly_cents": weekly_cents,
        "applied": applied,
    }
