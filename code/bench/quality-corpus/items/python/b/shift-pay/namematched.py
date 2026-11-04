"""Calculate weekly shift pay using exact integer-minute arithmetic."""

ROLE_RATE_QUARTERS = {"helper": 120, "nurse": 160, "lead": 200}
APPLIED_RULES = (
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
    role, shifts, bonus = normalized_request_parts(request)
    rows = [dict(s, index=i) for i, s in enumerate(shifts)]
    return (
        request_validation_error(role, shifts, bonus)
        or validate_shifts(rows)
        or find_overlap_error(rows)
        or calculate_week_pay(role, rows, bonus)
    )


def normalized_request_parts(request):
    return request["role"].strip().lower(), request["shifts"], request["bonus"]


def request_validation_error(role, rows, bonus):
    checks = (
        (role in ROLE_RATE_QUARTERS, "BAD_ROLE"),
        (bool(rows), "EMPTY_WEEK"),
        (len(rows) <= 14, "TOO_MANY_SHIFTS"),
        (type(bonus) is bool, "BAD_BONUS"),
    )
    return next(
        (error_record_for(code, None) for valid, code in checks if not valid), None
    )


def error_record_for(code, index):
    return {"error": code, "index": index}


def bounded_integer(v, hi):
    return type(v) is int and 0 <= v <= hi


def shift_duration(s):
    return (s["end"] - s["start"]) % 1440 or 1440


def timeline_start(s):
    return s["day"] * 1440 + s["start"]


def validate_integer_fields(s, i):
    fields = (
        ("day", 6, "BAD_DAY"),
        ("start", 1439, "BAD_START"),
        ("end", 1439, "BAD_END"),
        ("break", 240, "BAD_BREAK"),
    )
    for f, h, c in fields:
        if not bounded_integer(s[f], h):
            return error_record_for(c, i)


def validate_boolean_fields(s, i):
    for f, c in (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT")):
        if type(s[f]) is not bool:
            return error_record_for(c, i)


def validate_shift_length(s, i):
    d = shift_duration(s)
    if e := shift_length_failure(s, d, i):
        return e
    return store_normalized_shift_times(s, d)


def shift_length_failure(s, d, i):
    if not 1 <= d <= 960:
        return error_record_for("BAD_LENGTH", i)
    if s["break"] > d:
        return error_record_for("BREAK_TOO_LONG", i)


def store_normalized_shift_times(s, d):
    s.update(
        {
            "duration": d,
            "paid": d - (s["break"] if d > 360 else 0),
            "timeline": timeline_start(s),
        }
    )


def validate_shifts(rows):
    for i, s in enumerate(rows):
        if (
            e := validate_integer_fields(s, i)
            or validate_boolean_fields(s, i)
            or validate_shift_length(s, i)
        ):
            return e


def overlap_start(a, b, shift):
    lo = max(a["timeline"], b["timeline"] + shift)
    hi = min(a["timeline"] + a["duration"], b["timeline"] + shift + b["duration"])
    return lo if lo < hi else None


def find_overlap_error(rows):
    hits = overlap_intervals(rows)
    return error_record_for("OVERLAP", min(hits)[1]) if hits else None


def overlap_intervals(rows):
    return [
        (t, max(a["index"], b["index"]))
        for i, a in enumerate(rows)
        for b in rows[i + 1 :]
        for d in (-10080, 0, 10080)
        if (t := overlap_start(a, b, d)) is not None
    ]


def is_night_minute(m):
    return m >= 1320 or m < 360


def is_overtime_minute(k, prior):
    return k >= 480 or prior + k >= 2400


def minute_rate_quarters(base, ot, ni, we, ho):
    return base + base // 2 * ot + base // 5 * ni + base // 4 * we + base * ho


def cents_rounded_half_up(amount):
    return (amount + 2) // 4


def callout_extra_minutes(s):
    return max(0, 180 - s["paid"]) if s["callout"] else 0


def public_shift_fields(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def worked_minute_flags(s, prior, k):
    day, clock = worked_minute_clock(s, k)
    return (
        is_overtime_minute(k, prior),
        is_night_minute(clock),
        day % 7 >= 5,
        s["holiday"],
        k >= 480,
        prior + k >= 2400,
    )


def worked_minute_clock(s, k):
    absolute = s["timeline"] + k + (s["break"] if s["duration"] > 360 else 0)
    return divmod(absolute, 1440)


def record_minute_pay(counts, base, flags):
    ot, ni, we, ho, daily, weekly = flags
    counts["overtime" if ot else "regular"] += 1
    counts["night_minutes"] += ni
    counts["weekend_minutes"] += we
    counts["holiday_minutes"] += ho
    return minute_rate_quarters(base, ot, ni, we, ho), daily, weekly


def calculate_shift_totals(s, base, prior):
    counts = dict.fromkeys(
        ("regular", "overtime", "night_minutes", "weekend_minutes", "holiday_minutes"),
        0,
    )
    amount, daily, weekly = sum_shift_minutes(s, base, prior, counts)
    return counts, amount, daily, weekly


def sum_shift_minutes(s, base, prior, counts):
    amount = 0
    daily = weekly = False
    for k in range(s["paid"]):
        cents, d, w = record_minute_pay(counts, base, worked_minute_flags(s, prior, k))
        amount += cents
        daily |= d
        weekly |= w
    return amount, daily, weekly


def assemble_shift_row(s, base, prior):
    counts, amount, daily, weekly = calculate_shift_totals(s, base, prior)
    extra = callout_extra_minutes(s)
    amount += base * extra
    return shift_output_record(s, counts, extra, amount, daily, weekly)


def shift_output_record(s, counts, extra, amount, daily, weekly):
    return (
        shift_identity_fields(s)
        | worked_minute_fields(counts)
        | bonus_amount_fields(extra, amount, daily, weekly)
    )


def bonus_amount_fields(extra, amount, daily, weekly):
    return {
        "callout_minutes": extra,
        "bonus_cents": 0,
        "cents": cents_rounded_half_up(amount),
        "_amount": amount,
        "_daily": daily,
        "_weekly": weekly,
    }


def shift_identity_fields(s):
    return {
        "day": s["day"],
        "start": s["start"],
        "end": s["end"],
        "paid_minutes": s["paid"],
    }


def worked_minute_fields(counts):
    return {
        "regular_minutes": counts["regular"],
        "overtime_minutes": counts["overtime"],
        "night_minutes": counts["night_minutes"],
        "weekend_minutes": counts["weekend_minutes"],
        "holiday_minutes": counts["holiday_minutes"],
    }


def calculate_week_pay(role, shifts, bonus):
    rows, prior = calculate_shift_rows(role, shifts)
    if bonus and prior >= 600:
        apply_weekly_bonus(rows[-1])
    return assemble_week_record(rows, weekly_paid_minutes(rows))


def calculate_shift_rows(role, shifts):
    rows, prior = [], 0
    base = ROLE_RATE_QUARTERS[role]
    for s in shifts:
        row = assemble_shift_row(s, base, prior)
        rows.append(row)
        prior += row["paid_minutes"]
    return rows, prior


def apply_weekly_bonus(row):
    row["bonus_cents"] = 500
    row["cents"] = cents_rounded_half_up(row["_amount"] + 2000)


def weekly_paid_minutes(rows):
    return sum(row["paid_minutes"] for row in rows)


def applied_rule_names(rows):
    return [name for key, name in APPLIED_RULES if any(r[key] for r in rows)]


def assemble_week_record(rows, paid):
    clean = [public_shift_fields(r) for r in rows]
    return {
        "shifts": clean,
        "weekly_paid_minutes": paid,
        "weekly_cents": sum(r["cents"] for r in clean),
        "applied": applied_rule_names(rows),
    }
