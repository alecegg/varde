"""Calculate weekly shift pay using exact integer-minute arithmetic."""

RATES = {"helper": 120, "nurse": 160, "lead": 200}
RULES = (
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
    role, shifts, bonus = request_parts(request)
    rows = [dict(s, index=i) for i, s in enumerate(shifts)]
    return (
        request_error(role, shifts, bonus)
        or row_errors(rows)
        or overlap_error(rows)
        or price_week(role, rows, bonus)
    )


def request_parts(request):
    return request["role"].strip().lower(), request["shifts"], request["bonus"]


def request_error(role, rows, bonus):
    checks = (
        (role in RATES, "BAD_ROLE"),
        (bool(rows), "EMPTY_WEEK"),
        (len(rows) <= 14, "TOO_MANY_SHIFTS"),
        (type(bonus) is bool, "BAD_BONUS"),
    )
    return next((error_record(code, None) for valid, code in checks if not valid), None)


def error_record(code, index):
    return {"error": code, "index": index}


def integer(v, hi):
    return type(v) is int and 0 <= v <= hi


def duration(s):
    return (s["end"] - s["start"]) % 1440 or 1440


def timeline(s):
    return s["day"] * 1440 + s["start"]


def field_error(s, i):
    fields = (
        ("day", 6, "BAD_DAY"),
        ("start", 1439, "BAD_START"),
        ("end", 1439, "BAD_END"),
        ("break", 240, "BAD_BREAK"),
    )
    for f, h, c in fields:
        if not integer(s[f], h):
            return error_record(c, i)


def flag_error(s, i):
    for f, c in (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT")):
        if type(s[f]) is not bool:
            return error_record(c, i)


def length_error(s, i):
    d = duration(s)
    if e := length_failure(s, d, i):
        return e
    return store_shift_times(s, d)


def length_failure(s, d, i):
    if not 1 <= d <= 960:
        return error_record("BAD_LENGTH", i)
    if s["break"] > d:
        return error_record("BREAK_TOO_LONG", i)


def store_shift_times(s, d):
    s.update(
        {
            "duration": d,
            "paid": d - (s["break"] if d > 360 else 0),
            "timeline": timeline(s),
        }
    )


def row_errors(rows):
    for i, s in enumerate(rows):
        if e := field_error(s, i) or flag_error(s, i) or length_error(s, i):
            return e


def collision(a, b, shift):
    lo = max(a["timeline"], b["timeline"] + shift)
    hi = min(a["timeline"] + a["duration"], b["timeline"] + shift + b["duration"])
    return lo if lo < hi else None


def overlap_error(rows):
    hits = overlap_hits(rows)
    return error_record("OVERLAP", min(hits)[1]) if hits else None


def overlap_hits(rows):
    return [
        (t, max(a["index"], b["index"]))
        for i, a in enumerate(rows)
        for b in rows[i + 1 :]
        for d in (-10080, 0, 10080)
        if (t := collision(a, b, d)) is not None
    ]


def night(m):
    return m >= 1320 or m < 360


def overtime(k, prior):
    return k >= 480 or prior + k >= 2400


def rate(base, ot, ni, we, ho):
    return base + base // 2 * ot + base // 5 * ni + base // 4 * we + base * ho


def rounded(amount):
    return (amount + 2) // 4


def topup(s):
    return max(0, 180 - s["paid"]) if s["callout"] else 0


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def minute_flags(s, prior, k):
    day, clock = minute_clock(s, k)
    return (
        overtime(k, prior),
        night(clock),
        day % 7 >= 5,
        s["holiday"],
        k >= 480,
        prior + k >= 2400,
    )


def minute_clock(s, k):
    absolute = s["timeline"] + k + (s["break"] if s["duration"] > 360 else 0)
    return divmod(absolute, 1440)


def record_minute(counts, base, flags):
    ot, ni, we, ho, daily, weekly = flags
    counts["overtime" if ot else "regular"] += 1
    counts["night_minutes"] += ni
    counts["weekend_minutes"] += we
    counts["holiday_minutes"] += ho
    return rate(base, ot, ni, we, ho), daily, weekly


def shift_totals(s, base, prior):
    counts = dict.fromkeys(
        ("regular", "overtime", "night_minutes", "weekend_minutes", "holiday_minutes"),
        0,
    )
    amount, daily, weekly = total_shift_minutes(s, base, prior, counts)
    return counts, amount, daily, weekly


def total_shift_minutes(s, base, prior, counts):
    amount = 0
    daily = weekly = False
    for k in range(s["paid"]):
        cents, d, w = record_minute(counts, base, minute_flags(s, prior, k))
        amount += cents
        daily |= d
        weekly |= w
    return amount, daily, weekly


def shift_row(s, base, prior):
    counts, amount, daily, weekly = shift_totals(s, base, prior)
    extra = topup(s)
    amount += base * extra
    return row_record(s, counts, extra, amount, daily, weekly)


def row_record(s, counts, extra, amount, daily, weekly):
    return (
        shift_fields(s)
        | minute_fields(counts)
        | bonus_fields(extra, amount, daily, weekly)
    )


def bonus_fields(extra, amount, daily, weekly):
    return {
        "callout_minutes": extra,
        "bonus_cents": 0,
        "cents": rounded(amount),
        "_amount": amount,
        "_daily": daily,
        "_weekly": weekly,
    }


def shift_fields(s):
    return {
        "day": s["day"],
        "start": s["start"],
        "end": s["end"],
        "paid_minutes": s["paid"],
    }


def minute_fields(counts):
    return {
        "regular_minutes": counts["regular"],
        "overtime_minutes": counts["overtime"],
        "night_minutes": counts["night_minutes"],
        "weekend_minutes": counts["weekend_minutes"],
        "holiday_minutes": counts["holiday_minutes"],
    }


def price_week(role, shifts, bonus):
    rows, prior = price_rows(role, shifts)
    if bonus and prior >= 600:
        award_bonus(rows[-1])
    return weekly_record(rows, paid_total(rows))


def price_rows(role, shifts):
    rows, prior = [], 0
    base = RATES[role]
    for s in shifts:
        row = shift_row(s, base, prior)
        rows.append(row)
        prior += row["paid_minutes"]
    return rows, prior


def award_bonus(row):
    row["bonus_cents"] = 500
    row["cents"] = rounded(row["_amount"] + 2000)


def paid_total(rows):
    return sum(row["paid_minutes"] for row in rows)


def active(rows):
    return [name for key, name in RULES if any(r[key] for r in rows)]


def weekly_record(rows, paid):
    clean = [public(r) for r in rows]
    return {
        "shifts": clean,
        "weekly_paid_minutes": paid,
        "weekly_cents": sum(r["cents"] for r in clean),
        "applied": active(rows),
    }
