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
SOURCE, KIND, PREFERRED_KEY, PREFERRED, DOCTORS, BOOKINGS = range(6)
DOCTOR_KEY, DOCTOR_NAME, DOCTOR_WINDOWS = range(3)
BOOKING_DAY, BOOKING_START, BOOKING_END, BOOKING_KEY = range(4)
BAD_REQUEST = "BAD_REQUEST"
BAD_DOCTORS = "BAD_DOCTORS"
BAD_WINDOW = "BAD_WINDOW"
BAD_HOLIDAY = "BAD_HOLIDAY"
BAD_BOOKING = "BAD_BOOKING"
UNKNOWN_DOCTOR = "UNKNOWN_DOCTOR"
BAD_DAY_ORDER = "BAD_DAY_ORDER"
NO_SLOT = "NO_SLOT"


def solution(request):
    """Return the earliest valid appointment or the first validation error."""
    data = normalize_request(request)
    failure = validate_request(data)
    slots = collect_slots(data, failure)
    return finish_result(data, failure, slots)


def normalize_request(request):
    kind = request["kind"]
    if isinstance(kind, str):
        kind = kind.strip(" ").lower()
    return (
        request,
        kind,
        *normalize_name(request.get("preferred_doctor", "")),
        *normalize_records(request["doctors"], request["bookings"]),
    )


def normalize_name(value):
    if not isinstance(value, str):
        return None, value
    if not value.strip(" "):
        return None, value.strip(" ")
    return value.strip(" ").lower(), value.strip(" ")


def normalize_records(source_doctors, source_bookings):
    return (
        [
            (*normalize_name(source["name"]), source["windows"])
            for source in source_doctors
        ],
        [
            (
                source["day"],
                source["start"],
                source["end"],
                normalize_name(source["doctor"])[0],
            )
            for source in source_bookings
        ],
    )


def validate_request(data):
    checks = (
        check_scalars,
        check_doctors,
        check_windows,
        check_holidays,
        check_bookings,
        check_request_order,
    )
    for check in checks:
        failure = check(data)
        if failure is not None:
            return failure
    return None


def finish_result(data, failure, slots):
    if failure:
        return {"error": failure[0], "index": failure[1]}
    if not slots:
        return {"error": NO_SLOT, "index": None}
    return success_result(min(slots), data[KIND])


def check_scalars(data):
    source, kind, _, preferred = data[:4]
    if (
        not scalar_bounds_are_valid(source)
        or not isinstance(kind, str)
        or kind not in KINDS
        or not isinstance(preferred, str)
        or type(source["urgent"]) is not bool
    ):
        return BAD_REQUEST, None
    return None


def scalar_bounds_are_valid(source):
    return all(
        type(source[field]) is int and low <= source[field] <= high
        for field, (low, high) in BOUNDS.items()
    )


def check_doctors(data):
    doctors = data[DOCTORS]
    if not 0 < len(doctors) < 13:
        return BAD_DOCTORS, None
    names = set()
    for index, doctor in enumerate(doctors):
        key = doctor[DOCTOR_KEY]
        if not key or not NAME.fullmatch(doctor[DOCTOR_NAME]) or key in names:
            return BAD_DOCTORS, index
        names.add(key)
    return None


def check_windows(data):
    for doctor_index, doctor in enumerate(data[DOCTORS]):
        if len(doctor[DOCTOR_WINDOWS]) > 8:
            return BAD_WINDOW, doctor_index
        if any(not window_is_valid(window) for window in doctor[DOCTOR_WINDOWS]):
            return BAD_WINDOW, doctor_index
    return None


def window_is_valid(window):
    weekday = window["weekday"]
    opening, closing = window["open"], window["close"]
    day_is_valid = type(weekday) is int and 0 <= weekday <= 6
    time_is_valid = (
        type(opening) is int and type(closing) is int and 0 <= opening < closing <= 1440
    )
    return day_is_valid and time_is_valid


def check_holidays(data):
    holidays = data[SOURCE]["holidays"]
    if len(holidays) > 60:
        return BAD_HOLIDAY, None
    seen_days = set()
    for index, day in enumerate(holidays):
        if type(day) is not int or day not in range(1_000_001) or day in seen_days:
            return BAD_HOLIDAY, index
        seen_days.add(day)
    return None


def check_bookings(data):
    bookings = data[BOOKINGS]
    if len(bookings) > 200:
        return BAD_BOOKING, None
    known_doctors = {doctor[DOCTOR_KEY] for doctor in data[DOCTORS]}
    for index, booking in enumerate(bookings):
        if not booking_is_valid(booking, known_doctors):
            return BAD_BOOKING, index
    return None


def booking_is_valid(booking, known_doctors):
    day = booking[BOOKING_DAY]
    start = booking[BOOKING_START]
    end = booking[BOOKING_END]
    return (
        type(day) is int
        and 0 <= day <= 1_000_000
        and type(start) is type(end) is int
        and 0 <= start < end <= 1440
        and booking[BOOKING_KEY] in known_doctors
    )


def check_request_order(data):
    source = data[SOURCE]
    known_doctors = {doctor[DOCTOR_KEY] for doctor in data[DOCTORS]}
    if data[PREFERRED] and data[PREFERRED_KEY] not in known_doctors:
        return UNKNOWN_DOCTOR, None
    if not 0 <= source["requested_day"] - source["now_day"] <= 8:
        return BAD_DAY_ORDER, None
    return None


def candidate_days(data):
    source = data[SOURCE]
    first_day = source["requested_day"]
    holidays = set(source["holidays"])
    last_day = min(first_day + source["horizon_days"], first_day + 14, 1_000_000)
    return [day for day in range(first_day, last_day + 1) if day not in holidays]


def eligible_doctors(data):
    source, _, preferred_key, preferred, doctors = data[:5]
    if source["urgent"] or not preferred:
        return doctors
    return [doctor for doctor in doctors if doctor[DOCTOR_KEY] == preferred_key]


def opening_and_window(doctor, weekday, start, reserved_end):
    opens, closes = OPENING[weekday]
    if start < opens or reserved_end > closes or start < 780 and reserved_end > 720:
        return False
    return any(
        window["weekday"] == weekday
        and window["open"] <= start
        and reserved_end <= window["close"]
        for window in doctor[DOCTOR_WINDOWS]
    )


def booking_is_available(data, doctor, day, start, reserved_end):
    bookings = [
        booking
        for booking in data[BOOKINGS]
        if booking[BOOKING_DAY] == day and booking[BOOKING_KEY] == doctor[DOCTOR_KEY]
    ]
    return len(bookings) < 4 and all(
        start >= booking[BOOKING_END] or reserved_end <= booking[BOOKING_START]
        for booking in bookings
    )


def candidate_is_valid(data, doctor, day, start, reserved_length):
    source = data[SOURCE]
    reserved_end = start + reserved_length
    return (
        (day != source["now_day"] or start >= source["now_minute"] + 60)
        and opening_and_window(doctor, day % 7, start, reserved_end)
        and booking_is_available(data, doctor, day, start, reserved_end)
    )


def collect_slots(data, failure):
    return (
        []
        if failure
        else [
            (day, start, *doctor[:2])
            for day in candidate_days(data)
            for doctor in eligible_doctors(data)
            for start in range(0, 1440, 5)
            if candidate_is_valid(data, doctor, day, start, sum(KINDS[data[KIND]]))
        ]
    )


def success_result(slot, kind):
    return {
        "day": slot[0],
        "start": slot[1],
        "end": slot[1] + KINDS[kind][0],
        "doctor": slot[3],
        "trace": list(TRACE),
    }
