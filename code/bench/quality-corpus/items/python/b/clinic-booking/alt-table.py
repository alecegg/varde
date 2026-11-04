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
SCALAR_RULES = (
    (
        lambda data: any(
            type(data[key]) is not int or not low <= data[key] <= high
            for key, (low, high) in BOUNDS.items()
        ),
        "BAD_REQUEST",
    ),
    (
        lambda data: not isinstance(data["kind"], str) or data["kind"] not in KINDS,
        "BAD_REQUEST",
    ),
    (lambda data: not isinstance(data["preferred_doctor"], str), "BAD_REQUEST"),
    (lambda data: type(data["urgent"]) is not bool, "BAD_REQUEST"),
)
WINDOW_RULES = (
    (lambda window: type(window["weekday"]) is not int, "BAD_WINDOW"),
    (lambda window: not 0 <= window["weekday"] <= 6, "BAD_WINDOW"),
    (lambda window: type(window["open"]) is not int, "BAD_WINDOW"),
    (lambda window: type(window["close"]) is not int, "BAD_WINDOW"),
    (lambda window: not 0 <= window["open"] < window["close"] <= 1440, "BAD_WINDOW"),
)


def solution(request):
    """Return the earliest valid appointment or the first validation error."""
    data = normalise(request)
    error = validate(data)
    if error:
        return error
    slot = find_slot(data)
    return assemble(slot) if slot else {"error": "NO_SLOT", "index": None}


def normalise(request):
    data = dict(request)
    kind = request["kind"]
    preferred = request.get("preferred_doctor", "")
    data["kind"] = kind.strip(" ").lower() if isinstance(kind, str) else kind
    data["preferred_doctor"] = (
        preferred.strip(" ") if isinstance(preferred, str) else preferred
    )
    data["doctors"] = normalise_doctors(request["doctors"])
    data["bookings"] = normalise_bookings(request["bookings"])
    data["preferred_key"] = name_key(data["preferred_doctor"])
    return data


def normalise_doctors(doctors):
    return [
        dict(
            doctor,
            name=(
                name := doctor["name"].strip(" ")
                if isinstance(doctor["name"], str)
                else doctor["name"]
            ),
            key=name_key(name),
        )
        for doctor in doctors
    ]


def normalise_bookings(bookings):
    return [
        dict(
            booking,
            doctor=(
                name := booking["doctor"].strip(" ")
                if isinstance(booking["doctor"], str)
                else booking["doctor"]
            ),
            key=name_key(name),
        )
        for booking in bookings
    ]


def first_error(rules, subject, index):
    for invalid, code in rules:
        if invalid(subject):
            return {"error": code, "index": index}
    return None


def validate(data):
    error = first_error(SCALAR_RULES, data, None)
    if error:
        return error
    error = validate_doctors(data["doctors"])
    if error:
        return error
    error = validate_windows(data["doctors"])
    if error:
        return error
    error = validate_holidays(data["holidays"])
    if error:
        return error
    error = validate_bookings(data)
    if error:
        return error
    return validate_request(data)


def validate_doctors(doctors):
    if not 1 <= len(doctors) <= 12:
        return {"error": "BAD_DOCTORS", "index": None}
    seen = set()
    for index, doctor in enumerate(doctors):
        key = doctor["key"]
        if key is None or key in seen:
            return {"error": "BAD_DOCTORS", "index": index}
        seen.add(key)
    return None


def validate_windows(doctors):
    for index, doctor in enumerate(doctors):
        windows = doctor["windows"]
        if len(windows) > 8:
            return {"error": "BAD_WINDOW", "index": index}
        for window in windows:
            error = first_error(WINDOW_RULES, window, index)
            if error:
                return error
    return None


def validate_holidays(holidays):
    if len(holidays) > 60:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen = set()
    for index, day in enumerate(holidays):
        invalid = type(day) is not int or not 0 <= day <= 1_000_000 or day in seen
        if invalid:
            return {"error": "BAD_HOLIDAY", "index": index}
        seen.add(day)
    return None


def validate_bookings(data):
    bookings = data["bookings"]
    if len(bookings) > 200:
        return {"error": "BAD_BOOKING", "index": None}
    names = {doctor["key"] for doctor in data["doctors"]}
    for index, booking in enumerate(bookings):
        if not valid_booking(booking, names):
            return {"error": "BAD_BOOKING", "index": index}
    return None


def valid_booking(booking, names):
    day, start, end = booking["day"], booking["start"], booking["end"]
    return (
        type(day) is int
        and 0 <= day <= 1_000_000
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= 1440
        and booking["key"] in names
    )


def validate_request(data):
    names = {doctor["key"] for doctor in data["doctors"]}
    preferred = data["preferred_doctor"]
    if preferred and data["preferred_key"] not in names:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    if not data["now_day"] <= data["requested_day"] <= data["now_day"] + 8:
        return {"error": "BAD_DAY_ORDER", "index": None}
    return None


def find_slot(data):
    duration, buffer = KINDS[data["kind"]]
    doctors = data["doctors"]
    if not data["urgent"] and data["preferred_doctor"]:
        doctors = [
            doctor for doctor in doctors if doctor["key"] == data["preferred_key"]
        ]
    slots = slot_candidates(data, doctors, duration, buffer)
    day, start, _, doctor, end = min(slots, default=(None, None, None, None, None))
    return (day, start, end, doctor) if day is not None else None


def slot_candidates(data, doctors, duration, buffer):
    for day in candidate_days(data):
        weekday = day % 7
        for start in range(0, 1440, 5):
            reserved_end = start + duration + buffer
            for doctor in doctors:
                bookings = [
                    booking
                    for booking in data["bookings"]
                    if booking["day"] == day and booking["key"] == doctor["key"]
                ]
                if within_hours(
                    doctor, weekday, start, reserved_end
                ) and schedule_clear(data, day, start, reserved_end, bookings):
                    yield (day, start, doctor["key"], doctor["name"], start + duration)


def candidate_days(data):
    first = data["requested_day"]
    last = min(first + data["horizon_days"], first + 14, 1_000_000)
    holidays = set(data["holidays"])
    return [day for day in range(first, last + 1) if day not in holidays]


def within_hours(doctor, weekday, start, reserved_end):
    opening = OPENING[weekday]
    matching = any(
        window["weekday"] == weekday
        and window["open"] <= start
        and reserved_end <= window["close"]
        for window in doctor["windows"]
    )
    office_open = opening[0] <= start and reserved_end <= opening[1]
    lunch_clear = not (start < 780 and reserved_end > 720)
    return matching and office_open and lunch_clear


def schedule_clear(data, day, start, reserved_end, bookings):
    notice_ok = day > data["now_day"] or start >= data["now_minute"] + 60
    below_daily_cap = len(bookings) < 4
    no_overlap = all(
        start >= booking["end"] or reserved_end <= booking["start"]
        for booking in bookings
    )
    return notice_ok and below_daily_cap and no_overlap


def assemble(slot):
    day, start, end, doctor = slot
    result = {"day": day, "start": start, "end": end, "doctor": doctor}
    result["trace"] = list(TRACE)
    return result


def name_key(name):
    if not isinstance(name, str):
        return None
    cleaned = name.strip(" ")
    if not cleaned or NAME.fullmatch(cleaned) is None:
        return None
    return cleaned.lower()
