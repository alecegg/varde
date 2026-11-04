"""Contract cases and a deliberately brute-force scheduling oracle."""

import random
import re

import solution


def base(**updates):
    request = {
        "now_day": 100,
        "now_minute": 480,
        "requested_day": 100,
        "horizon_days": 2,
        "kind": "checkup",
        "urgent": False,
        "preferred_doctor": "",
        "holidays": [],
        "doctors": [
            {
                "name": "Ada",
                "windows": [
                    {"weekday": weekday, "open": 540, "close": 1020}
                    for weekday in range(5)
                ],
            }
        ],
        "bookings": [],
    }
    request.update(updates)
    return request


def result(day, start, end, doctor="Ada"):
    return {
        "day": day,
        "start": start,
        "end": end,
        "doctor": doctor,
        "trace": [
            "normalised",
            "validated",
            "holiday-filter",
            "hours-and-lunch",
            "notice",
            "doctor-availability",
            "daily-cap",
            "booking-conflicts",
            "urgent-priority",
            "earliest-grid-slot",
        ],
    }


WORKED = [
    (base(), result(100, 540, 560)),
    (base(kind="  CONSULTATION  "), result(100, 540, 570)),
    (base(now_minute=500), result(100, 560, 580)),
    (base(now_minute=1000), result(101, 540, 560)),
    (base(kind="consultation"), result(100, 540, 570)),
    (base(kind="procedure"), result(100, 540, 600)),
    (
        base(
            doctors=[
                {
                    "name": "  Ada  ",
                    "windows": [{"weekday": 2, "open": 600, "close": 660}],
                }
            ]
        ),
        result(100, 600, 620),
    ),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": [{"weekday": 2, "open": 700, "close": 840}]}
            ]
        ),
        result(100, 780, 800),
    ),
    (
        base(bookings=[{"day": 100, "start": 540, "end": 570, "doctor": "  ADA  "}]),
        result(100, 570, 590),
    ),
    (
        base(bookings=[{"day": 100, "start": 540, "end": 565, "doctor": "Ada"}]),
        result(100, 565, 585),
    ),
    (
        base(
            bookings=[
                {"day": 100, "start": a, "end": a + 10, "doctor": "Ada"}
                for a in (540, 560, 580, 600)
            ]
        ),
        result(101, 540, 560),
    ),
    (base(holidays=[100]), result(101, 540, 560)),
    (
        base(
            doctors=[
                {"name": n, "windows": [{"weekday": 2, "open": 540, "close": 1020}]}
                for n in ("Bo", "Ada")
            ]
        ),
        result(100, 540, 560),
    ),
]

ERRORS = [
    (base(now_day=-1), {"error": "BAD_REQUEST", "index": None}),
    (base(doctors=[]), {"error": "BAD_DOCTORS", "index": None}),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": [{"weekday": 7, "open": 540, "close": 600}]},
                {"name": " ada ", "windows": []},
            ]
        ),
        {"error": "BAD_DOCTORS", "index": 1},
    ),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": []},
                {"name": "Bo", "windows": []},
                {"name": "Cy", "windows": [{"weekday": 2, "open": 900, "close": 900}]},
            ]
        ),
        {"error": "BAD_WINDOW", "index": 2},
    ),
    (base(holidays=[100, 100]), {"error": "BAD_HOLIDAY", "index": 1}),
    (
        base(
            bookings=[
                {"day": 100, "start": 540, "end": 550, "doctor": "Ada"},
                {"day": 100, "start": 540, "end": 540, "doctor": "Ada"},
            ]
        ),
        {"error": "BAD_BOOKING", "index": 1},
    ),
    (
        base(
            bookings=[
                {"day": 100, "start": 540, "end": 550, "doctor": "Ada"},
                {"day": 100, "start": 550, "end": 560, "doctor": "Ada"},
                {"day": 100, "start": 560, "end": 560, "doctor": "Ada"},
            ]
        ),
        {"error": "BAD_BOOKING", "index": 2},
    ),
    (base(preferred_doctor="Bo"), {"error": "UNKNOWN_DOCTOR", "index": None}),
    (base(requested_day=99), {"error": "BAD_DAY_ORDER", "index": None}),
    (base(requested_day=109), {"error": "BAD_DAY_ORDER", "index": None}),
    (
        base(preferred_doctor="Bo", requested_day=109),
        {"error": "UNKNOWN_DOCTOR", "index": None},
    ),
    (base(kind="other", doctors=[]), {"error": "BAD_REQUEST", "index": None}),
    (
        base(
            doctors=[{"name": "Ada", "windows": []}, {"name": "ada", "windows": []}],
            holidays=[-1],
        ),
        {"error": "BAD_DOCTORS", "index": 1},
    ),
    (
        base(
            bookings=[{"day": 100, "start": 1, "end": 1, "doctor": "Ada"}],
            preferred_doctor="Bo",
        ),
        {"error": "BAD_BOOKING", "index": 0},
    ),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": [{"weekday": 1, "open": 540, "close": 1020}]}
            ]
        ),
        {"error": "NO_SLOT", "index": None},
    ),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": [{"weekday": 2, "open": 700, "close": 700}]}
            ],
            holidays=[-1],
        ),
        {"error": "BAD_WINDOW", "index": 0},
    ),
    (
        base(
            holidays=[-1],
            bookings=[{"day": 100, "start": 540, "end": 540, "doctor": "Ada"}],
        ),
        {"error": "BAD_HOLIDAY", "index": 0},
    ),
    (base(kind=42), {"error": "BAD_REQUEST", "index": None}),
    (base(urgent=1), {"error": "BAD_REQUEST", "index": None}),
    (base(preferred_doctor=None), {"error": "BAD_REQUEST", "index": None}),
    (
        base(doctors=[{"name": None, "windows": []}]),
        {"error": "BAD_DOCTORS", "index": 0},
    ),
    (
        base(bookings=[{"day": 100, "start": 540, "end": 550, "doctor": None}]),
        {"error": "BAD_BOOKING", "index": 0},
    ),
    (
        base(doctors=[{"name": "Ada@", "windows": []}]),
        {"error": "BAD_DOCTORS", "index": 0},
    ),
    (
        base(doctors=[{"name": f"D{n}", "windows": []} for n in range(13)]),
        {"error": "BAD_DOCTORS", "index": None},
    ),
    (base(horizon_days=15), {"error": "BAD_REQUEST", "index": None}),
    (base(now_minute=1440), {"error": "BAD_REQUEST", "index": None}),
    (base(requested_day=1_000_001), {"error": "BAD_REQUEST", "index": None}),
    (
        base(
            doctors=[
                {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 1441}]}
            ]
        ),
        {"error": "BAD_WINDOW", "index": 0},
    ),
    *[
        (base(**{field: value}), {"error": "BAD_REQUEST", "index": None})
        for field in ("now_day", "requested_day")
        for value in (None, "a", True)
    ],
    (base(holidays=list(range(61))), {"error": "BAD_HOLIDAY", "index": None}),
    (
        base(
            bookings=[
                {"day": 500 + n, "start": 0, "end": 1, "doctor": "Ada"}
                for n in range(201)
            ]
        ),
        {"error": "BAD_BOOKING", "index": None},
    ),
    (
        base(
            doctors=[
                {
                    "name": "Ada",
                    "windows": [{"weekday": 2, "open": 540, "close": 600}] * 9,
                }
            ]
        ),
        {"error": "BAD_WINDOW", "index": 0},
    ),
]


def oracle(request):  # noqa: C901, PLR0911, PLR0912
    """Validate then inspect every day, doctor and five-minute start."""
    raw_kind = request["kind"]
    raw_preferred = request.get("preferred_doctor", "")
    if not isinstance(raw_kind, str) or not isinstance(raw_preferred, str):
        return {"error": "BAD_REQUEST", "index": None}
    kind = raw_kind.strip(" ").lower()
    preferred = raw_preferred.strip(" ")
    doctors = [
        {
            "name": d["name"].strip(" ") if isinstance(d["name"], str) else d["name"],
            "windows": d["windows"],
        }
        for d in request["doctors"]
    ]
    if (
        type(request["now_day"]) is not int
        or type(request["now_minute"]) is not int
        or type(request["requested_day"]) is not int
        or type(request["horizon_days"]) is not int
        or type(request["urgent"]) is not bool
        or kind not in {"checkup", "consultation", "procedure"}
        or not 0 <= request["now_day"] <= 1_000_000
        or not 0 <= request["requested_day"] <= 1_000_000
        or not 0 <= request["now_minute"] <= 1439
        or not 0 <= request["horizon_days"] <= 14
    ):
        return {"error": "BAD_REQUEST", "index": None}
    if not 1 <= len(doctors) <= 12:
        return {"error": "BAD_DOCTORS", "index": None}
    seen = set()
    for i, d in enumerate(doctors):
        name = d["name"]
        if (
            not isinstance(name, str)
            or not name
            or not re.fullmatch(r"[A-Za-z0-9 -]+", name)
        ):
            return {"error": "BAD_DOCTORS", "index": i}
        key = name.lower()
        if key in seen:
            return {"error": "BAD_DOCTORS", "index": i}
        seen.add(key)
    for i, d in enumerate(doctors):
        if len(d["windows"]) > 8 or any(
            type(w["weekday"]) is not int
            or not 0 <= w["weekday"] <= 6
            or type(w["open"]) is not int
            or type(w["close"]) is not int
            or not 0 <= w["open"] < w["close"] <= 1440
            for w in d["windows"]
        ):
            return {"error": "BAD_WINDOW", "index": i}
    holidays = request["holidays"]
    if len(holidays) > 60:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen = set()
    for i, day in enumerate(holidays):
        if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
            return {"error": "BAD_HOLIDAY", "index": i}
        seen.add(day)
    bookings = request["bookings"]
    if len(bookings) > 200:
        return {"error": "BAD_BOOKING", "index": None}
    valid_names = {d["name"].lower() for d in doctors}
    for i, b in enumerate(bookings):
        if (
            type(b["day"]) is not int
            or not 0 <= b["day"] <= 1_000_000
            or type(b["start"]) is not int
            or type(b["end"]) is not int
            or not 0 <= b["start"] < b["end"] <= 1440
            or not isinstance(b["doctor"], str)
            or b["doctor"].strip(" ").lower() not in valid_names
        ):
            return {"error": "BAD_BOOKING", "index": i}
    if preferred and preferred.lower() not in valid_names:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    if not request["now_day"] <= request["requested_day"] <= request["now_day"] + 8:
        return {"error": "BAD_DAY_ORDER", "index": None}
    duration, buffer = {
        "checkup": (20, 5),
        "consultation": (30, 10),
        "procedure": (60, 15),
    }[kind]
    last = min(
        request["requested_day"] + request["horizon_days"],
        request["requested_day"] + 14,
        1_000_000,
    )
    candidates = []
    for day in range(request["requested_day"], last + 1):
        if day in holidays:
            continue
        weekday = day % 7
        open_start, open_end = (
            (540, 1020) if weekday < 5 else (600, 840) if weekday == 5 else (0, 0)
        )
        for doctor in doctors:
            key = doctor["name"].lower()
            if not request["urgent"] and preferred and key != preferred.lower():
                continue
            daily = [
                b
                for b in bookings
                if b["day"] == day and b["doctor"].strip().lower() == key
            ]
            if len(daily) >= 4:
                continue
            for start in range(0, 1436, 5):
                end, occupied_end = start + duration, start + duration + buffer
                if day == request["now_day"] and start < request["now_minute"] + 60:
                    continue
                if (
                    start < open_start
                    or occupied_end > open_end
                    or (start < 780 and occupied_end > 720)
                ):
                    continue
                if not any(
                    w["weekday"] == weekday
                    and w["open"] <= start
                    and occupied_end <= w["close"]
                    for w in doctor["windows"]
                ):
                    continue
                if any(start < b["end"] and b["start"] < occupied_end for b in daily):
                    continue
                candidates.append((day, start, key, doctor["name"], end))
    if not candidates:
        return {"error": "NO_SLOT", "index": None}
    day, start, _, doctor, end = min(candidates)
    return result(day, start, end, doctor)


def check(request, expected=None):
    wanted = oracle(request) if expected is None else expected
    actual = solution.solution(request)
    assert actual == wanted, (
        f"request={request!r}\nexpected={wanted!r}\nactual={actual!r}"
    )


for case, expected in WORKED + ERRORS:
    check(case, expected)

# Inclusive and exclusive boundaries for opening, window, lunch, horizon and notice.
for minute in (599, 600, 655):
    check(
        base(
            doctors=[
                {
                    "name": "Ada",
                    "windows": [{"weekday": 2, "open": minute, "close": 685}],
                }
            ]
        ),
        None,
    )
check(base(now_minute=480), result(100, 540, 560))
check(base(now_minute=481), result(100, 545, 565))
check(base(horizon_days=0), result(100, 540, 560))
check(base(horizon_days=0, holidays=[100]), {"error": "NO_SLOT", "index": None})
check(
    base(now_day=0, now_minute=0, requested_day=0, horizon_days=0), result(0, 540, 560)
)
check(
    base(doctors=[{"name": "Ada", "windows": []}]), {"error": "NO_SLOT", "index": None}
)
check(base(now_day=100, requested_day=108, horizon_days=0), result(108, 540, 560))
check(base(requested_day=102, horizon_days=0), result(102, 540, 560))
check(
    base(
        requested_day=103,
        horizon_days=0,
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 5, "open": 600, "close": 840}]}
        ],
    ),
    result(103, 600, 620),
)
check(
    base(
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 565}]}
        ]
    ),
    result(100, 540, 560),
)
check(
    base(
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 600, "close": 625}]}
        ]
    ),
    result(100, 600, 620),
)
check(
    base(
        horizon_days=0,
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 564}]}
        ],
    ),
    {"error": "NO_SLOT", "index": None},
)
check(
    base(
        horizon_days=0,
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 800, "close": 900}]}
        ],
        bookings=[
            {"day": 100, "start": start, "end": start + 10, "doctor": "Ada"}
            for start in (540, 560, 580, 600)
        ],
    ),
    {"error": "NO_SLOT", "index": None},
)
check(
    base(
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 995, "close": 1020}]}
        ]
    ),
    result(100, 995, 1015),
)
check(
    base(bookings=[{"day": 100, "start": 540, "end": 695, "doctor": "Ada"}]),
    result(100, 695, 715),
)
check(
    base(
        doctors=[
            {"name": name, "windows": [{"weekday": 2, "open": 540, "close": 1020}]}
            for name in ("Ada", "Bo")
        ],
        bookings=[
            {"day": 100, "start": start, "end": start + 10, "doctor": "Ada"}
            for start in (800, 820, 840, 860)
        ],
    ),
    result(100, 540, 560, "Bo"),
)
check(
    base(bookings=[{"day": 100, "start": 540, "end": 555, "doctor": "Ada"}]),
    result(100, 555, 575),
)
check(
    base(bookings=[{"day": 100, "start": 565, "end": 575, "doctor": "Ada"}]),
    result(100, 540, 560),
)
check(
    base(
        horizon_days=0,
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 575, "close": 600}]}
        ],
        bookings=[{"day": 100, "start": 550, "end": 575, "doctor": "Ada"}],
    ),
    result(100, 575, 595),
)
check(
    base(
        bookings=[
            {"day": 100, "start": a, "end": a + 10, "doctor": "Ada"}
            for a in (800, 850, 900)
        ]
    ),
    result(100, 540, 560),
)
check(
    base(
        doctors=[
            {"name": name, "windows": [{"weekday": 2, "open": 540, "close": 1020}]}
            for name in ("zoe", "ada")
        ]
    ),
    result(100, 540, 560, "ada"),
)
check(
    base(
        doctors=[
            {"name": name, "windows": [{"weekday": 2, "open": 540, "close": 1020}]}
            for name in ("BO", "ada")
        ]
    ),
    result(100, 540, 560, "ada"),
)
check(
    base(
        doctors=[
            {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 1020}] * 8}
        ]
    ),
    result(100, 540, 560),
)
check(base(holidays=list(range(200, 260))), result(100, 540, 560))
check(
    base(
        bookings=[
            {"day": 500 + n, "start": 0, "end": 1, "doctor": "Ada"} for n in range(200)
        ]
    ),
    result(100, 540, 560),
)
check(
    base(
        doctors=[
            {
                "name": f"Doc {n}",
                "windows": [{"weekday": 2, "open": 540, "close": 1020}],
            }
            for n in range(12)
        ]
    ),
    result(100, 540, 560, "Doc 0"),
)
check(base(horizon_days=14), result(100, 540, 560))
check(base(now_minute=1439), result(101, 540, 560))
check(base(holidays=[100, 101]), result(102, 540, 560))
check(
    base(bookings=[{"day": 100, "start": 0, "end": 1, "doctor": "ada"}]),
    result(100, 540, 560),
)
check(base(preferred_doctor=" ada "), result(100, 540, 560))
check(
    base(requested_day=1_000_000, now_day=999_992, horizon_days=14),
    result(1_000_000, 540, 560),
)

# Priority, preference, cap, end-touching overlap, late notice and horizon end.
check(
    base(
        preferred_doctor="Bo",
        urgent=False,
        doctors=[
            {"name": "Bo", "windows": [{"weekday": 2, "open": 540, "close": 1020}]},
            {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 1020}]},
        ],
    ),
    result(100, 540, 560, "Bo"),
)
check(
    base(
        preferred_doctor="Bo",
        urgent=True,
        doctors=[
            {"name": "Bo", "windows": [{"weekday": 2, "open": 540, "close": 1020}]},
            {"name": "Ada", "windows": [{"weekday": 2, "open": 540, "close": 1020}]},
        ],
    ),
    result(100, 540, 560, "Ada"),
)

# Thousands of deterministic in-domain requests, checked against full enumeration.
rng = random.Random(731904)
for _ in range(2000):
    day = rng.randint(20, 900)
    requested_offset = rng.randint(0, 8)
    horizon = rng.randint(0, 14)
    first_day = day + requested_offset
    last_day = first_day + horizon
    names = ["Ada", "Bo", "Cy"][: rng.randint(1, 3)]
    doctors = [
        {
            "name": name,
            "windows": [
                {
                    "weekday": weekday,
                    "open": 600 if weekday == 5 else 540,
                    "close": 840 if weekday == 5 else 1020,
                }
                for weekday in range(7)
                if rng.randrange(4) != 0
            ],
        }
        for name in names
    ]
    bookings = []
    for _ in range(rng.randint(0, 16)):
        name = rng.choice(names)
        start = rng.randrange(540, 960, 5)
        bookings.append(
            {
                "day": rng.randint(first_day, last_day),
                "start": start,
                "end": min(start + rng.choice((10, 20, 30, 60)), 1440),
                "doctor": name,
            }
        )
    if rng.randrange(3) == 0:
        capped_day, capped_name = rng.randint(first_day, last_day), rng.choice(names)
        bookings.extend(
            {"day": capped_day, "start": index, "end": index + 1, "doctor": capped_name}
            for index in range(4)
        )
    holidays = sorted(
        {rng.randint(first_day, last_day) for _ in range(rng.randrange(0, 4))}
    )
    check(
        base(
            now_day=day,
            now_minute=rng.randrange(0, 1440),
            requested_day=first_day,
            horizon_days=horizon,
            kind=rng.choice(("checkup", "consultation", "procedure")),
            urgent=bool(rng.randrange(2)),
            preferred_doctor=rng.choice(("", "Ada", "Bo")),
            holidays=holidays,
            doctors=doctors,
            bookings=bookings,
        )
    )
