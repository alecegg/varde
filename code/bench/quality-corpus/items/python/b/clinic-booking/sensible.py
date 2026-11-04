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


def validate(data):
    for checker in (
        check_scalars,
        check_doctors,
        check_windows,
        check_holidays,
        check_bookings,
        check_request_order,
    ):
        error = checker(data)
        if error:
            return error
    return None


def check_scalars(data):
    if (
        any(
            type(data[k]) is not int or not lo <= data[k] <= hi
            for k, (lo, hi) in BOUNDS.items()
        )
        or not isinstance(data["kind"], str)
        or data["kind"] not in KINDS
        or not isinstance(data["preferred_doctor"], str)
        or type(data["urgent"]) is not bool
    ):
        return {"error": "BAD_REQUEST", "index": None}
    return None


def check_doctors(data):
    doctors = data["doctors"]
    if not 1 <= len(doctors) <= 12:
        return {"error": "BAD_DOCTORS", "index": None}
    names = set()
    for index, doctor in enumerate(doctors):
        key = doctor["key"]
        if key is None or key in names:
            return {"error": "BAD_DOCTORS", "index": index}
        names.add(key)
    return None


def check_windows(data):
    for index, doctor in enumerate(data["doctors"]):
        windows = doctor["windows"]
        if len(windows) > 8:
            return {"error": "BAD_WINDOW", "index": index}
        for window in windows:
            day, opening, closing = window["weekday"], window["open"], window["close"]
            if (
                type(day) is not int
                or not 0 <= day <= 6
                or type(opening) is not int
                or type(closing) is not int
                or not 0 <= opening < closing <= 1440
            ):
                return {"error": "BAD_WINDOW", "index": index}
    return None


def check_holidays(data):
    holidays = data["holidays"]
    if len(holidays) > 60:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen = set()
    for index, day in enumerate(holidays):
        if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
            return {"error": "BAD_HOLIDAY", "index": index}
        seen.add(day)
    return None


def check_bookings(data):
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


def check_request_order(data):
    preferred = data["preferred_doctor"]
    names = {doctor["key"] for doctor in data["doctors"]}
    if preferred and data["preferred_key"] not in names:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    if not data["now_day"] <= data["requested_day"] <= data["now_day"] + 8:
        return {"error": "BAD_DAY_ORDER", "index": None}
    return None


def find_slot(data):
    duration, buffer = KINDS[data["kind"]]
    doctors = data["doctors"]
    if not data["urgent"] and data["preferred_doctor"]:
        doctors = [d for d in doctors if d["key"] == data["preferred_key"]]
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
    return (
        any(
            window["weekday"] == weekday
            and window["open"] <= start
            and reserved_end <= window["close"]
            for window in doctor["windows"]
        )
        and opening[0] <= start
        and reserved_end <= opening[1]
        and not (start < 780 and reserved_end > 720)
    )


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
    return {
        "day": day,
        "start": start,
        "end": end,
        "doctor": doctor,
        "trace": list(TRACE),
    }


def name_key(name):
    if not isinstance(name, str):
        return None
    cleaned = name.strip(" ")
    if not cleaned or NAME.fullmatch(cleaned) is None:
        return None
    return cleaned.lower()
