def solution(request):  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Return ordered shift pay rows or the first contract validation error."""
    role = request["role"].strip().lower()
    shifts = request["shifts"]
    bonus = request["bonus"]
    base_rates = {"helper": 120, "nurse": 160, "lead": 200}
    if role not in base_rates:
        return {"error": "BAD_ROLE", "index": None}
    if not shifts:
        return {"error": "EMPTY_WEEK", "index": None}
    if len(shifts) > 14:
        return {"error": "TOO_MANY_SHIFTS", "index": None}
    if type(bonus) is not bool:
        return {"error": "BAD_BONUS", "index": None}

    spans = []
    for index, shift in enumerate(shifts):
        day = shift["day"]
        if type(day) is not int:
            return {"error": "BAD_DAY", "index": index}
        if day < 0 or day > 6:
            return {"error": "BAD_DAY", "index": index}
        start = shift["start"]
        if type(start) is not int:
            return {"error": "BAD_START", "index": index}
        if start < 0 or start > 1439:
            return {"error": "BAD_START", "index": index}
        end = shift["end"]
        if type(end) is not int:
            return {"error": "BAD_END", "index": index}
        if end < 0 or end > 1439:
            return {"error": "BAD_END", "index": index}
        break_minutes = shift["break"]
        if type(break_minutes) is not int:
            return {"error": "BAD_BREAK", "index": index}
        if break_minutes < 0 or break_minutes > 240:
            return {"error": "BAD_BREAK", "index": index}
        if type(shift["holiday"]) is not bool:
            return {"error": "BAD_HOLIDAY", "index": index}
        if type(shift["callout"]) is not bool:
            return {"error": "BAD_CALLOUT", "index": index}
        duration = (end - start) % 1440 or 1440
        if not 1 <= duration <= 960:
            return {"error": "BAD_LENGTH", "index": index}
        if break_minutes > duration:
            return {"error": "BREAK_TOO_LONG", "index": index}
        paid_minutes = duration - (break_minutes if duration > 360 else 0)
        spans.append(
            {
                "day": day,
                "start": start,
                "end": end,
                "break": break_minutes,
                "holiday": shift["holiday"],
                "callout": shift["callout"],
                "index": index,
                "duration": duration,
                "paid": paid_minutes,
                "timeline": day * 1440 + start,
            }
        )

    collisions = []
    for left_position, left in enumerate(spans):
        for right in spans[left_position + 1 :]:
            for offset in (-10080, 0, 10080):
                start = max(left["timeline"], right["timeline"] + offset)
                end = min(
                    left["timeline"] + left["duration"],
                    right["timeline"] + offset + right["duration"],
                )
                if start < end:
                    collisions.append((start, max(left["index"], right["index"])))
    if collisions:
        return {"error": "OVERLAP", "index": min(collisions)[1]}

    output = []
    weekly_paid = 0
    for shift in spans:
        base = base_rates[role]
        counts = dict.fromkeys(
            ("regular", "overtime", "night", "weekend", "holiday"), 0
        )
        exact_amount = 0
        daily_applied = False
        weekly_applied = False
        break_offset = shift["break"] if shift["duration"] > 360 else 0
        for offset in range(shift["paid"]):
            absolute_minute = shift["timeline"] + break_offset + offset
            day_number, clock_minute = divmod(absolute_minute, 1440)
            day_number %= 7
            daily_overtime = offset >= 480
            weekly_overtime = weekly_paid + offset >= 2400
            overtime = daily_overtime or weekly_overtime
            night = clock_minute >= 1320 or clock_minute < 360
            weekend = day_number >= 5
            holiday = shift["holiday"]
            counts["overtime" if overtime else "regular"] += 1
            counts["night"] += night
            counts["weekend"] += weekend
            counts["holiday"] += holiday
            daily_applied |= daily_overtime
            weekly_applied |= weekly_overtime
            minute_amount = base
            if overtime:
                minute_amount += base // 2
            if night:
                minute_amount += base // 5
            if weekend:
                minute_amount += base // 4
            if holiday:
                minute_amount += base
            exact_amount += minute_amount
        callout_minutes = max(0, 180 - shift["paid"]) if shift["callout"] else 0
        exact_amount += base * callout_minutes
        output.append(
            {
                "day": shift["day"],
                "start": shift["start"],
                "end": shift["end"],
                "paid_minutes": shift["paid"],
                "regular_minutes": counts["regular"],
                "overtime_minutes": counts["overtime"],
                "night_minutes": counts["night"],
                "weekend_minutes": counts["weekend"],
                "holiday_minutes": counts["holiday"],
                "callout_minutes": callout_minutes,
                "bonus_cents": 0,
                "cents": (exact_amount + 2) // 4,
                "_amount": exact_amount,
                "_daily": daily_applied,
                "_weekly": weekly_applied,
            }
        )
        weekly_paid += shift["paid"]

    if bonus and weekly_paid >= 600:
        output[-1]["bonus_cents"] = 500
        output[-1]["cents"] = (output[-1]["_amount"] + 2002) // 4
    rule_names = (
        ("_daily", "daily-overtime"),
        ("_weekly", "weekly-overtime"),
        ("night_minutes", "night-premium"),
        ("weekend_minutes", "weekend-premium"),
        ("holiday_minutes", "holiday-rate"),
        ("callout_minutes", "callout-minimum"),
        ("bonus_cents", "bonus"),
    )
    applied = []
    for field, name in rule_names:
        active = False
        for row in output:
            if row[field]:
                active = True
                break
        if active:
            applied.append(name)
    public_fields = (
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
    public_rows = [{field: row[field] for field in public_fields} for row in output]
    weekly_cents = 0
    for row in public_rows:
        weekly_cents += row["cents"]
    return {
        "shifts": public_rows,
        "weekly_paid_minutes": weekly_paid,
        "weekly_cents": weekly_cents,
        "applied": applied,
    }
