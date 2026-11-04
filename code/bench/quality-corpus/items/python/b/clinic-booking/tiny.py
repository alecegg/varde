"""Natural layered clinic appointment scheduler."""

import re

KINDS = {"checkup": (20, 5), "consultation": (30, 10), "procedure": (60, 15)}
NAME = re.compile(r"[A-Za-z0-9 -]+")
BOUNDS = {
    "now_day": (0, 1_000_000),
    "now_minute": (0, 1439),
    "requested_day": (0, 1_000_000),
    "horizon_days": (0, 14),
}
OPENING = ((540, 1020),) * 5 + ((600, 840), (0, 0))
TRACE = (
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
)


def solution(request):
    """Return the earliest valid appointment or the first validation error."""
    data = prep(request)
    issue = check_all(data)
    if issue:
        return issue
    slot = schedule(data)
    return pack(slot) if slot else fail("NO_SLOT", None)


def prep(request):
    data = base_data(request)
    data["doctors"] = clean_doctors(request["doctors"])
    data["bookings"] = clean_bookings(request["bookings"])
    data["preferred_key"] = name_key(data["preferred_doctor"])
    return data


def base_data(request):
    data = dict(request)
    data["kind"] = clean_kind(request["kind"])
    data["preferred_doctor"] = clean_name(request.get("preferred_doctor", ""))
    return data


def clean_kind(value):
    return value.strip(" ").lower() if isinstance(value, str) else value


def clean_name(value):
    return value.strip(" ") if isinstance(value, str) else value


def clean_doctors(rows):
    return [
        dict(row, name=clean_name(row["name"]), key=name_key(row["name"]))
        for row in rows
    ]


def clean_bookings(rows):
    return [
        dict(row, doctor=clean_name(row["doctor"]), key=name_key(row["doctor"]))
        for row in rows
    ]


def name_key(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip(" ")
    return cleaned.lower() if cleaned and NAME.fullmatch(cleaned) else None


def check_all(data):
    for check in checks():
        issue = check(data)
        if issue:
            return issue
    return None


def checks():
    return (
        check_scalars,
        check_doctors,
        check_windows,
        check_holidays,
        check_bookings,
        check_order,
    )


def check_scalars(data):
    if not bounds_ok(data) or not flags_ok(data):
        return fail("BAD_REQUEST", None)
    return None


def bounds_ok(data):
    return all(
        type(data[key]) is int and low <= data[key] <= high
        for key, (low, high) in BOUNDS.items()
    )


def flags_ok(data):
    return (
        isinstance(data["kind"], str)
        and data["kind"] in KINDS
        and isinstance(data["preferred_doctor"], str)
        and type(data["urgent"]) is bool
    )


def check_doctors(data):
    rows = data["doctors"]
    if not 1 <= len(rows) <= 12:
        return fail("BAD_DOCTORS", None)
    return unique_doctors(rows)


def unique_doctors(rows):
    keys = set()
    for index, row in enumerate(rows):
        key = row["key"]
        if key is None or key in keys:
            return fail("BAD_DOCTORS", index)
        keys.add(key)
    return None


def check_windows(data):
    for index, row in enumerate(data["doctors"]):
        if len(row["windows"]) > 8 or not windows_ok(row["windows"]):
            return fail("BAD_WINDOW", index)
    return None


def windows_ok(rows):
    return all(window_ok(row) for row in rows)


def window_ok(row):
    day, opening, closing = row["weekday"], row["open"], row["close"]
    return (
        type(day) is int
        and 0 <= day <= 6
        and type(opening) is int
        and type(closing) is int
        and 0 <= opening < closing <= 1440
    )


def check_holidays(data):
    rows = data["holidays"]
    if len(rows) > 60:
        return fail("BAD_HOLIDAY", None)
    seen = set()
    for index, day in enumerate(rows):
        if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
            return fail("BAD_HOLIDAY", index)
        seen.add(day)
    return None


def check_bookings(data):
    rows = data["bookings"]
    if len(rows) > 200:
        return fail("BAD_BOOKING", None)
    keys = {row["key"] for row in data["doctors"]}
    for index, row in enumerate(rows):
        if not booking_ok(row, keys):
            return fail("BAD_BOOKING", index)
    return None


def booking_ok(row, keys):
    day, start, end = row["day"], row["start"], row["end"]
    return (
        type(day) is int
        and 0 <= day <= 1_000_000
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= 1440
        and row["key"] in keys
    )


def check_order(data):
    issue = preferred_error(data)
    if issue:
        return issue
    if not day_order_ok(data):
        return fail("BAD_DAY_ORDER", None)
    return None


def preferred_error(data):
    keys = {row["key"] for row in data["doctors"]}
    preferred = data["preferred_doctor"]
    if preferred and data["preferred_key"] not in keys:
        return fail("UNKNOWN_DOCTOR", None)
    return None


def day_order_ok(data):
    return data["now_day"] <= data["requested_day"] <= data["now_day"] + 8


def schedule(data):
    doctors = eligible(data)
    slots = candidates(data, doctors)
    return choose(slots)


def eligible(data):
    if not data["urgent"] and data["preferred_doctor"]:
        return [row for row in data["doctors"] if row["key"] == data["preferred_key"]]
    return data["doctors"]


def candidates(data, doctors):
    return [
        slot
        for day in days(data)
        for start in starts()
        for doctor in doctors
        if (slot := valid(data, day, start, doctor))
    ]


def days(data):
    first = data["requested_day"]
    last = min(first + data["horizon_days"], first + 14, 1_000_000)
    return [day for day in range(first, last + 1) if day not in data["holidays"]]


def starts():
    return range(0, 1440, 5)


def valid(data, day, start, doctor):
    end = reserved_end(data, start)
    bookings = matching(data["bookings"], day, doctor["key"])
    if not available(data, day, start, end, bookings, doctor):
        return None
    return slot_of(data, day, start, doctor)


def reserved_end(data, start):
    duration, buffer = KINDS[data["kind"]]
    return start + duration + buffer


def available(data, day, start, end, bookings, doctor):
    return (
        fits(doctor, day % 7, start, end)
        and notice(data, day, start)
        and cap(bookings)
        and clear(start, end, bookings)
    )


def slot_of(data, day, start, doctor):
    duration = KINDS[data["kind"]][0]
    return day, start, doctor["key"], doctor["name"], start + duration


def matching(rows, day, key):
    return [row for row in rows if row["day"] == day and row["key"] == key]


def fits(doctor, weekday, start, end):
    window_match = window_matches(doctor, weekday, start, end)
    opening_match = opening_ok(weekday, start, end)
    lunch_overlap = lunch(start, end)
    return window_match and opening_match and not lunch_overlap


def window_matches(doctor, weekday, start, end):
    return any(
        window["weekday"] == weekday
        and window["open"] <= start
        and end <= window["close"]
        for window in doctor["windows"]
    )


def opening_ok(weekday, start, end):
    opening, closing = OPENING[weekday]
    return opening <= start and end <= closing


def lunch(start, end):
    return start < 780 and end > 720


def notice(data, day, start):
    return day > data["now_day"] or start >= data["now_minute"] + 60


def cap(rows):
    return len(rows) < 4


def clear(start, end, rows):
    return all(start >= row["end"] or end <= row["start"] for row in rows)


def choose(slots):
    slot = min(slots, default=None, key=order)
    return slot


def order(slot):
    return slot[:3]


def pack(slot):
    day, start, _, doctor, end = slot
    return {"day": day, "start": start, "end": end, "doctor": doctor, "trace": trace()}


def trace():
    return list(TRACE)


def fail(code, index):
    return {"error": code, "index": index}
