"""Worked contract examples and seeded comparisons to a minute-level oracle."""

import os
import random

import solution


def shift(day, start, end, break_minutes=0, holiday=False, callout=False):
    return {
        "day": day,
        "start": start,
        "end": end,
        "break": break_minutes,
        "holiday": holiday,
        "callout": callout,
    }


def req(role="helper", shifts=None, bonus=False):
    return {"role": role, "shifts": [] if shifts is None else shifts, "bonus": bonus}


def rhu(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def oracle(request):  # noqa: C901, PLR0911, PLR0912, PLR0915
    role, rows, bonus = (
        request["role"].strip().lower(),
        request["shifts"],
        request["bonus"],
    )
    if role not in {"helper", "nurse", "lead"}:
        return {"error": "BAD_ROLE", "index": None}
    if not rows:
        return {"error": "EMPTY_WEEK", "index": None}
    if len(rows) > 14:
        return {"error": "TOO_MANY_SHIFTS", "index": None}
    if type(bonus) is not bool:
        return {"error": "BAD_BONUS", "index": None}
    spans = []
    for index, row in enumerate(rows):
        for field, low, high, code in (
            ("day", 0, 6, "BAD_DAY"),
            ("start", 0, 1439, "BAD_START"),
            ("end", 0, 1439, "BAD_END"),
            ("break", 0, 240, "BAD_BREAK"),
        ):
            value = row[field]
            if type(value) is not int or not low <= value <= high:
                return {"error": code, "index": index}
        for field, code in (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT")):
            if type(row[field]) is not bool:
                return {"error": code, "index": index}
        duration = (row["end"] - row["start"]) % 1440 or 1440
        if not 1 <= duration <= 960:
            return {"error": "BAD_LENGTH", "index": index}
        if row["break"] > duration:
            return {"error": "BREAK_TOO_LONG", "index": index}
        spans.append((row["day"] * 1440 + row["start"], duration, index))
    collisions = []
    for left_position, (left_start, left_length, left_index) in enumerate(spans):
        for right_start, right_length, right_index in spans[left_position + 1 :]:
            for offset in (-10080, 0, 10080):
                if max(left_start, right_start + offset) < min(
                    left_start + left_length, right_start + offset + right_length
                ):
                    collisions.append(
                        (
                            max(left_start, right_start + offset),
                            max(left_index, right_index),
                        )
                    )
    if collisions:
        return {"error": "OVERLAP", "index": min(collisions)[1]}
    rates = {"helper": 1800, "nurse": 2400, "lead": 3000}
    weekly_prior = 0
    priced = []
    for row, (start, duration, _) in zip(rows, spans, strict=True):
        unpaid = row["break"] if duration > 360 else 0
        worked = duration - unpaid
        minute_positions = [start + unpaid + offset for offset in range(worked)]
        exact_numerator = 0
        regular = overtime = night = weekend = holiday_minutes = 0
        daily_used = weekly_used = False
        for offset, absolute in enumerate(minute_positions):
            local_minute = absolute % 1440
            day = (absolute // 1440) % 7
            daily = offset >= 480
            weekly = weekly_prior + offset >= 2400
            daily_used |= daily
            weekly_used |= weekly
            overtime_minute = daily or weekly
            regular += not overtime_minute
            overtime += overtime_minute
            night += local_minute >= 1320 or local_minute < 360
            weekend += day in (5, 6)
            holiday_minutes += row["holiday"]
            numerator = rates[role] * (
                20
                + 10 * overtime_minute
                + 4 * (local_minute >= 1320 or local_minute < 360)
                + 5 * (day in (5, 6))
                + 20 * row["holiday"]
            )
            add_num = numerator
            exact_numerator += add_num
        top_up = max(0, 180 - worked) if row["callout"] else 0
        exact_numerator += rates[role] * top_up * 20
        exact_denominator = 1200
        bonus_cents = 0
        cents = rhu(exact_numerator, exact_denominator)
        priced.append(
            {
                "day": row["day"],
                "start": row["start"],
                "end": row["end"],
                "paid_minutes": worked,
                "regular_minutes": regular,
                "overtime_minutes": overtime,
                "night_minutes": night,
                "weekend_minutes": weekend,
                "holiday_minutes": holiday_minutes,
                "callout_minutes": top_up,
                "bonus_cents": bonus_cents,
                "cents": cents,
                "_exact": (exact_numerator, exact_denominator),
                "_daily": daily_used,
                "_weekly": weekly_used,
            }
        )
        weekly_prior += worked
    if bonus and weekly_prior >= 600:
        priced[-1]["bonus_cents"] = 500
        numerator, denominator = priced[-1]["_exact"]
        priced[-1]["cents"] = rhu(numerator + 500 * 1200, denominator)
    applied = []
    for field, label in (
        ("_daily", "daily-overtime"),
        ("_weekly", "weekly-overtime"),
        ("night_minutes", "night-premium"),
        ("weekend_minutes", "weekend-premium"),
        ("holiday_minutes", "holiday-rate"),
        ("callout_minutes", "callout-minimum"),
        ("bonus_cents", "bonus"),
    ):
        if any(row[field] for row in priced):
            applied.append(label)
    output_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in priced
    ]
    return {
        "shifts": output_rows,
        "weekly_paid_minutes": weekly_prior,
        "weekly_cents": sum(row["cents"] for row in output_rows),
        "applied": applied,
    }


def check(given, expected=None):
    wanted = oracle(given) if expected is None else expected
    actual = solution.solution(given)
    if actual != wanted:
        raise AssertionError(
            f"request={given!r}\nexpected={wanted!r}\nactual={actual!r}"
        )


# Worked examples from rich-shift-pay.md, with the stated amounts and counters.
WORKED = [
    (req("helper", [shift(0, 540, 1020, 30)]), (450, 13500)),
    (req("nurse", [shift(1, 1320, 360, 30)]), (450, 21600)),
    (req("helper", [shift(5, 540, 780)]), (240, 9000)),
    (req("lead", [shift(2, 540, 780, holiday=True)]), (240, 24000)),
    (req("helper", [shift(0, 540, 600, callout=True)]), (60, 5400)),
    (req("nurse", [shift(4, 480, 1080, 60)]), (540, 22800)),
    (req("helper", [shift(6, 1380, 180)]), (240, 9090)),
    (req("lead", [shift(5, 600, 1080, 30, True)], True), (450, 50625)),
    (req("helper", [shift(1, 360, 900, 60)]), (480, 14400)),
    (req("nurse", [shift(0, 720, 840, callout=True)], True), (120, 7200)),
    # Saturday's weekly overtime and weekend premiums both apply.
    (req("helper", [shift(day, 540, 1020) for day in range(6)]), (2880, 97200)),
    (req("helper", [shift(0, 1260, 300)]), (480, 16920)),
]
for given, (paid, cents) in WORKED:
    got = oracle(given)
    assert (got["weekly_paid_minutes"], got["weekly_cents"]) == (paid, cents), got
    check(given, got)

# Precedence examples from the contract, plus type and boundary failures.
ERRORS = [
    (req("unknown", []), "BAD_ROLE", None),
    (req("helper", [], None), "EMPTY_WEEK", None),
    (req("helper", [shift(0, 0, 60)] * 15, 1), "TOO_MANY_SHIFTS", None),
    (req("helper", [shift(7, 0, 60)], 1), "BAD_BONUS", None),
    (req("helper", [{**shift(0, 0, 60), "day": True}]), "BAD_DAY", 0),
    (req("helper", [{**shift(0, 0, 60), "start": True}]), "BAD_START", 0),
    (req("helper", [{**shift(0, 0, 60), "end": True}]), "BAD_END", 0),
    (req("helper", [{**shift(0, 0, 60), "break": True}]), "BAD_BREAK", 0),
    (
        req("helper", [{**shift(0, 0, 60), "day": 7, "start": 1440}]),
        "BAD_DAY",
        0,
    ),
    (
        req("helper", [{**shift(0, 0, 60), "start": 1440, "end": 1500}]),
        "BAD_START",
        0,
    ),
    (
        req("helper", [{**shift(0, 0, 60), "end": 1500, "break": 241}]),
        "BAD_END",
        0,
    ),
    (
        req("helper", [{**shift(0, 0, 60), "break": 241, "holiday": 1}]),
        "BAD_BREAK",
        0,
    ),
    (
        req("helper", [{**shift(0, 0, 60), "holiday": 1, "callout": 1}]),
        "BAD_HOLIDAY",
        0,
    ),
    (req("helper", [{**shift(0, 0, 961), "callout": 1}]), "BAD_CALLOUT", 0),
    (req("helper", [shift(0, 0, 961, 240)]), "BAD_LENGTH", 0),
    (req("helper", [shift(0, 540, 540)]), "BAD_LENGTH", 0),
    (req("helper", [shift(0, 0, 60, 61)]), "BREAK_TOO_LONG", 0),
    (req("helper", [shift(0, 0, 120), shift(0, 60, 180)]), "OVERLAP", 1),
    (
        req("helper", [shift(0, 0, 961), shift(0, 60, 180), shift(0, 90, 200)]),
        "BAD_LENGTH",
        0,
    ),
]
for given, code, index in ERRORS:
    check(given, {"error": code, "index": index})

# Numeric fields reject values outside the closed interval and reject coercion.
NUMERIC_INVALID = (
    ("day", "BAD_DAY", -1, 5.0, "5", None),
    ("start", "BAD_START", -1, 5.0, "5", None),
    ("end", "BAD_END", -1, 5.0, "5", None),
    ("break", "BAD_BREAK", -1, 5.0, "5", None),
)
for field, code, *bad_values in NUMERIC_INVALID:
    for bad_value in bad_values:
        for index in (1, 2):
            rows = [shift(0, 0, 30), shift(2, 0, 30), shift(4, 0, 30)][:index]
            invalid = {**shift(6, 0, 30), field: bad_value}
            rows.append(invalid)
            check(req(shifts=rows), {"error": code, "index": index})

# Each flag validation also reports the original index after preceding valid rows.
for field, code in (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT")):
    for index in (1, 2):
        rows = [shift(0, 0, 30), shift(2, 0, 30), shift(4, 0, 30)][:index]
        rows.append({**shift(6, 0, 30), field: 1})
        check(req(shifts=rows), {"error": code, "index": index})

# Length checks also retain the failing row's original index.
for invalid in (shift(6, 0, 961), shift(6, 0, 60, 61)):
    code = "BAD_LENGTH" if invalid["end"] == 961 else "BREAK_TOO_LONG"
    for index in (1, 2):
        rows = [shift(0, 0, 30), shift(2, 0, 30), shift(4, 0, 30)][:index]
        rows.append(invalid)
        check(req(shifts=rows), {"error": code, "index": index})

# Inclusive/exclusive rule boundaries and interactions.
for length, break_minutes, expected_paid in (
    (360, 60, 360),
    (361, 60, 301),
    (480, 0, 480),
    (481, 0, 481),
    (960, 240, 720),
):
    boundary = req(shifts=[shift(0, 0, length % 1440, break_minutes)])
    assert oracle(boundary)["weekly_paid_minutes"] == expected_paid
    check(boundary)
assert oracle(req(shifts=[shift(0, 0, 480)]))["shifts"][0]["overtime_minutes"] == 0
assert oracle(req(shifts=[shift(0, 0, 481)]))["shifts"][0]["overtime_minutes"] == 1
check(req(shifts=[shift(0, 0, 400, 400, callout=True)]))
check(req(shifts=[shift(0, 0, 60, 60)]))
for duration in (179, 180):
    check(req(shifts=[shift(0, 0, duration, callout=True)]))
valid_maximum = req(
    shifts=[shift(day, start, start + 30) for day in range(7) for start in (0, 100)]
)
check(valid_maximum)
overnight_holiday = req(shifts=[shift(5, 1439, 1, holiday=True)], role="lead")
assert oracle(overnight_holiday)["shifts"][0]["holiday_minutes"] == 2
check(overnight_holiday)
for start, expected_night in ((359, 1), (360, 0), (1319, 59), (1320, 60)):
    given = req(shifts=[shift(0, start, (start + 60) % 1440)])
    assert oracle(given)["shifts"][0]["night_minutes"] == expected_night
    check(given)
for spans in (
    [shift(0, 60, 120), shift(6, 1380, 180)],
    [shift(6, 1380, 180), shift(0, 60, 120)],
    [shift(0, 0, 60), shift(0, 60, 120)],
):
    check(req(shifts=spans))
weekly = req(shifts=[shift(day, 540, 1020) for day in range(5)] + [shift(5, 540, 1020)])
assert oracle(weekly)["shifts"][-1]["overtime_minutes"] == 480
check(weekly)
weekly_edge = req(
    shifts=[shift(day, 540, 1020) for day in (4, 3, 2, 1, 0)] + [shift(5, 540, 541)]
)
assert oracle(weekly_edge)["shifts"][-1]["overtime_minutes"] == 1
check(weekly_edge)
weekly_threshold_minute = req(
    shifts=[shift(day, 540, 1020) for day in range(4)]
    + [shift(4, 0, 479), shift(5, 0, 2)]
)
assert oracle(weekly_threshold_minute)["shifts"][-1]["overtime_minutes"] == 1
check(weekly_threshold_minute)
combined_overtime = req(
    shifts=[shift(day, 540, 1020) for day in range(5)] + [shift(5, 540, 1021)]
)
assert oracle(combined_overtime)["applied"][:2] == ["daily-overtime", "weekly-overtime"]
check(combined_overtime)
callout_threshold = req(
    shifts=[shift(day, 0, 478) for day in range(5)] + [shift(5, 0, 10, callout=True)]
)
assert oracle(callout_threshold)["shifts"][-1]["overtime_minutes"] == 0
check(callout_threshold)
topup_not_weekly = req(
    shifts=[shift(day, 0, 460) for day in range(5)]
    + [shift(5, 0, 10, callout=True), shift(6, 0, 1)]
)
assert oracle(topup_not_weekly)["shifts"][-1]["overtime_minutes"] == 0
check(topup_not_weekly)
for worked, bonus_cents in ((599, 0), (600, 500)):
    first = worked // 2
    given = req(shifts=[shift(0, 0, first), shift(1, 0, worked - first)], bonus=True)
    assert oracle(given)["shifts"][-1]["bonus_cents"] == bonus_cents
    check(given)
half_cent = req(shifts=[shift(5, 600, 601)])
assert oracle(half_cent)["shifts"][0]["cents"] == 38
check(half_cent)
per_shift_rounding = req(shifts=[shift(5, 600, 601), shift(6, 600, 601)])
assert oracle(per_shift_rounding)["weekly_cents"] == 76
check(per_shift_rounding)
break_at_night_edge = req(shifts=[shift(0, 330, 810, 30)])
assert oracle(break_at_night_edge)["shifts"][0]["night_minutes"] == 0
check(break_at_night_edge)
weekend_holiday = req(shifts=[shift(5, 600, 601, holiday=True)], role="lead")
assert oracle(weekend_holiday)["shifts"][0]["cents"] == 113
check(weekend_holiday)
assert (
    solution.solution(req(" Helper ", [shift(0, 600, 601)]))["weekly_paid_minutes"] == 1
)
check(req(" Helper ", [shift(0, 600, 601)]))
overlap_tie = req(shifts=[shift(0, 0, 120), shift(0, 60, 120), shift(0, 60, 120)])
check(overlap_tie, {"error": "OVERLAP", "index": 1})
check(req(shifts=[shift(0, 0, 960, callout=True)], bonus=True))


MUTATION_CASES = 12


def generated_requests():
    rng = random.Random(20261018)

    for _ in range(int(os.environ.get("SHIFT_PAY_RANDOM_CASES", "4000"))):
        role = rng.choice(("helper", "nurse", "lead"))
        count = rng.randint(1, 14)
        window = 10080 // count
        rows = []
        for slot in range(count):
            duration = rng.randint(1, min(960, window))
            timeline = slot * window + rng.randint(0, window - duration)
            start = timeline % 1440
            rows.append(
                shift(
                    timeline // 1440,
                    start,
                    (start + duration) % 1440,
                    rng.randint(0, min(240, duration)),
                    rng.choice((False, True)),
                    rng.choice((False, True)),
                )
            )
        rng.shuffle(rows)
        case = rng.randrange(MUTATION_CASES * 4)
        if case == 0:
            rows[0]["day"] = -1
        elif case == 1:
            rows[0]["start"] = 5.0
        elif case == 2:
            rows[0]["end"] = "5"
        elif case == 3:
            rows[0]["break"] = None
        elif case == 4:
            rows[0]["holiday"] = 1
        elif case == 5:
            rows[0]["callout"] = 1
        elif case == 6:
            rows[0]["day"] = 7
        elif case == 7:
            rows[0]["start"] = 1440
        elif case == 8:
            rows[0]["end"] = 1440
        elif case == 9:
            rows[0]["break"] = 241
        elif case == 10:
            rows[0]["end"] = (rows[0]["start"] + 961) % 1440
        elif case == 11:
            rows[0]["start"] = 0
            rows[0]["end"] = 1
            rows[0]["break"] = 2
        yield req(role, rows, rng.choice((False, True)))


generated_total = generated_valid = 0
for generated in generated_requests():
    check(generated)
    generated_total += 1
    generated_valid += "error" not in oracle(generated)
assert generated_valid * 2 >= generated_total, "random loop must mostly price"

print(
    "passed: 12 worked examples, 19 precedence errors, boundaries, "
    f"{generated_total} seeded requests ({generated_valid} valid, "
    f"{generated_total - generated_valid} invalid)"
)
