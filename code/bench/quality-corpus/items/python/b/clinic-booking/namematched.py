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
    data = normalise(request)
    issue = validate(data)
    if issue:
        return issue
    slot = find_slot(data)
    return assemble(slot) if slot else error("NO_SLOT", None)


def normalise(request):
    data = normalised_fields(request)
    data["doctors"] = normalised_doctors(request["doctors"])
    data["bookings"] = normalised_bookings(request["bookings"])
    data["preferred_key"] = normalised_name_key(data["preferred_doctor"])
    return data


def normalised_fields(request):
    data = dict(request)
    data["kind"] = normalised_kind(request["kind"])
    data["preferred_doctor"] = normalised_name(request.get("preferred_doctor", ""))
    return data


def normalised_kind(value):
    return value.strip(" ").lower() if isinstance(value, str) else value


def normalised_name(value):
    return value.strip(" ") if isinstance(value, str) else value


def normalised_doctors(rows):
    return [
        dict(
            row, name=normalised_name(row["name"]), key=normalised_name_key(row["name"])
        )
        for row in rows
    ]


def normalised_bookings(rows):
    return [
        dict(
            row,
            doctor=normalised_name(row["doctor"]),
            key=normalised_name_key(row["doctor"]),
        )
        for row in rows
    ]


def normalised_name_key(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip(" ")
    return cleaned.lower() if cleaned and NAME.fullmatch(cleaned) else None


def validate(data):
    for check in validation_checks():
        issue = check(data)
        if issue:
            return issue
    return None


def validation_checks():
    return (
        validate_scalars,
        validate_doctors,
        validate_windows,
        validate_holidays,
        validate_bookings,
        check_request_order,
    )


def validate_scalars(data):
    if not scalar_bounds_ok(data) or not request_flags_ok(data):
        return error("BAD_REQUEST", None)
    return None


def scalar_bounds_ok(data):
    return all(
        type(data[key]) is int and low <= data[key] <= high
        for key, (low, high) in BOUNDS.items()
    )


def request_flags_ok(data):
    return (
        isinstance(data["kind"], str)
        and data["kind"] in KINDS
        and isinstance(data["preferred_doctor"], str)
        and type(data["urgent"]) is bool
    )


def validate_doctors(data):
    rows = data["doctors"]
    if not 1 <= len(rows) <= 12:
        return error("BAD_DOCTORS", None)
    return unique_doctor_names(rows)


def unique_doctor_names(rows):
    keys = set()
    for index, row in enumerate(rows):
        key = row["key"]
        if key is None or key in keys:
            return error("BAD_DOCTORS", index)
        keys.add(key)
    return None


def validate_windows(data):
    for index, row in enumerate(data["doctors"]):
        if len(row["windows"]) > 8 or not valid_windows(row["windows"]):
            return error("BAD_WINDOW", index)
    return None


def valid_windows(rows):
    return all(valid_window(row) for row in rows)


def valid_window(row):
    day, opening, closing = row["weekday"], row["open"], row["close"]
    return (
        type(day) is int
        and 0 <= day <= 6
        and type(opening) is int
        and type(closing) is int
        and 0 <= opening < closing <= 1440
    )


def validate_holidays(data):
    rows = data["holidays"]
    if len(rows) > 60:
        return error("BAD_HOLIDAY", None)
    seen = set()
    for index, day in enumerate(rows):
        if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
            return error("BAD_HOLIDAY", index)
        seen.add(day)
    return None


def validate_bookings(data):
    rows = data["bookings"]
    if len(rows) > 200:
        return error("BAD_BOOKING", None)
    keys = {row["key"] for row in data["doctors"]}
    for index, row in enumerate(rows):
        if not valid_booking(row, keys):
            return error("BAD_BOOKING", index)
    return None


def valid_booking(row, keys):
    day, start, end = row["day"], row["start"], row["end"]
    return (
        type(day) is int
        and 0 <= day <= 1_000_000
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= 1440
        and row["key"] in keys
    )


def check_request_order(data):
    issue = preferred_doctor_error(data)
    if issue:
        return issue
    if not day_order_valid(data):
        return error("BAD_DAY_ORDER", None)
    return None


def preferred_doctor_error(data):
    keys = {row["key"] for row in data["doctors"]}
    preferred = data["preferred_doctor"]
    if preferred and data["preferred_key"] not in keys:
        return error("UNKNOWN_DOCTOR", None)
    return None


def day_order_valid(data):
    return data["now_day"] <= data["requested_day"] <= data["now_day"] + 8


def find_slot(data):
    doctors = eligible_doctors(data)
    slots = valid_candidates(data, doctors)
    return select_first(slots)


def eligible_doctors(data):
    if not data["urgent"] and data["preferred_doctor"]:
        return [row for row in data["doctors"] if row["key"] == data["preferred_key"]]
    return data["doctors"]


def valid_candidates(data, doctors):
    return [
        slot
        for day in candidate_days(data)
        for start in grid_starts()
        for doctor in doctors
        if (slot := valid_slot(data, day, start, doctor))
    ]


def candidate_days(data):
    first = data["requested_day"]
    last = min(first + data["horizon_days"], first + 14, 1_000_000)
    return [day for day in range(first, last + 1) if day not in data["holidays"]]


def grid_starts():
    return range(0, 1440, 5)


def valid_slot(data, day, start, doctor):
    end = reserved_interval_end(data, start)
    bookings = matching_bookings(data["bookings"], day, doctor["key"])
    if not slot_available(data, day, start, end, bookings, doctor):
        return None
    return appointment_candidate(data, day, start, doctor)


def reserved_interval_end(data, start):
    duration, buffer = KINDS[data["kind"]]
    return start + duration + buffer


def slot_available(data, day, start, end, bookings, doctor):
    return (
        within_hours(doctor, day % 7, start, end)
        and meets_notice(data, day, start)
        and under_cap(bookings)
        and no_conflicts(start, end, bookings)
    )


def appointment_candidate(data, day, start, doctor):
    duration = KINDS[data["kind"]][0]
    return day, start, doctor["key"], doctor["name"], start + duration


def matching_bookings(rows, day, key):
    return [row for row in rows if row["day"] == day and row["key"] == key]


def within_hours(doctor, weekday, start, end):
    window_match = matches_doctor_window(doctor, weekday, start, end)
    opening_match = fits_opening(weekday, start, end)
    lunch_overlap = intersects_lunch(start, end)
    return window_match and opening_match and not lunch_overlap


def matches_doctor_window(doctor, weekday, start, end):
    return any(
        window["weekday"] == weekday
        and window["open"] <= start
        and end <= window["close"]
        for window in doctor["windows"]
    )


def fits_opening(weekday, start, end):
    opening, closing = OPENING[weekday]
    return opening <= start and end <= closing


def intersects_lunch(start, end):
    return start < 780 and end > 720


def meets_notice(data, day, start):
    return day > data["now_day"] or start >= data["now_minute"] + 60


def under_cap(rows):
    return len(rows) < 4


def no_conflicts(start, end, rows):
    return all(start >= row["end"] or end <= row["start"] for row in rows)


def select_first(slots):
    slot = min(slots, default=None, key=slot_order)
    return slot


def slot_order(slot):
    return slot[:3]


def assemble(slot):
    day, start, _, doctor, end = slot
    return {
        "day": day,
        "start": start,
        "end": end,
        "doctor": doctor,
        "trace": trace_for(),
    }


def trace_for():
    return list(TRACE)


def error(code, index):
    return {"error": code, "index": index}
