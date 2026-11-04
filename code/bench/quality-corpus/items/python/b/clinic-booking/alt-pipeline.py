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
    context = normalise(request)
    for operation in (validate, select_doctors, locate, present):
        context = operation(context)
        if "error" in context:
            return context
    return context["answer"]


def normalise(request):
    context = dict(request)
    kind = request["kind"]
    preferred = request.get("preferred_doctor", "")
    context["kind"] = kind.strip(" ").lower() if isinstance(kind, str) else kind
    context["preferred_doctor"] = (
        preferred.strip(" ") if isinstance(preferred, str) else preferred
    )
    context["doctors"] = doctor_rows(request["doctors"])
    context["bookings"] = booking_rows(request["bookings"])
    context["preferred_key"] = name_key(context["preferred_doctor"])
    return context


def doctor_rows(doctors):
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


def booking_rows(bookings):
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


def validate(context):
    for check in (
        validate_scalars,
        validate_doctors,
        validate_windows,
        validate_holidays,
        validate_bookings,
        validate_request,
    ):
        error = check(context)
        if error:
            return {"error": error["error"], "index": error["index"]}
    return context


def validate_scalars(context):
    if (
        any(
            type(context[key]) is not int or not low <= context[key] <= high
            for key, (low, high) in BOUNDS.items()
        )
        or not isinstance(context["kind"], str)
        or context["kind"] not in KINDS
        or not isinstance(context["preferred_doctor"], str)
        or type(context["urgent"]) is not bool
    ):
        return {"error": "BAD_REQUEST", "index": None}
    return None


def validate_doctors(context):
    doctors = context["doctors"]
    if not 1 <= len(doctors) <= 12:
        return {"error": "BAD_DOCTORS", "index": None}
    keys = set()
    for index, doctor in enumerate(doctors):
        key = doctor["key"]
        if key is None or key in keys:
            return {"error": "BAD_DOCTORS", "index": index}
        keys.add(key)
    return None


def validate_windows(context):
    for index, doctor in enumerate(context["doctors"]):
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


def validate_holidays(context):
    holidays = context["holidays"]
    if len(holidays) > 60:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen = set()
    for index, day in enumerate(holidays):
        if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
            return {"error": "BAD_HOLIDAY", "index": index}
        seen.add(day)
    return None


def validate_bookings(context):
    bookings = context["bookings"]
    if len(bookings) > 200:
        return {"error": "BAD_BOOKING", "index": None}
    keys = {doctor["key"] for doctor in context["doctors"]}
    for index, booking in enumerate(bookings):
        if not valid_booking(booking, keys):
            return {"error": "BAD_BOOKING", "index": index}
    return None


def valid_booking(booking, keys):
    day, start, end = booking["day"], booking["start"], booking["end"]
    return (
        type(day) is int
        and 0 <= day <= 1_000_000
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= 1440
        and booking["key"] in keys
    )


def validate_request(context):
    preferred = context["preferred_doctor"]
    keys = {doctor["key"] for doctor in context["doctors"]}
    if preferred and context["preferred_key"] not in keys:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    if not context["now_day"] <= context["requested_day"] <= context["now_day"] + 8:
        return {"error": "BAD_DAY_ORDER", "index": None}
    return None


def select_doctors(context):
    duration, buffer = KINDS[context["kind"]]
    doctors = context["doctors"]
    if not context["urgent"] and context["preferred_doctor"]:
        doctors = [
            doctor for doctor in doctors if doctor["key"] == context["preferred_key"]
        ]
    return {**context, "duration": duration, "buffer": buffer, "available": doctors}


def locate(context):
    slots = candidates(context)
    day, start, _, doctor, end = min(slots, default=(None, None, None, None, None))
    slot = (day, start, end, doctor) if day is not None else None
    if slot is None:
        return {"error": "NO_SLOT", "index": None}
    return {**context, "slot": slot}


def candidates(context):
    duration, buffer = context["duration"], context["buffer"]
    for day in candidate_days(context):
        weekday = day % 7
        for start in range(0, 1440, 5):
            reserved_end = start + duration + buffer
            for doctor in context["available"]:
                bookings = [
                    booking
                    for booking in context["bookings"]
                    if booking["day"] == day and booking["key"] == doctor["key"]
                ]
                if within_hours(
                    doctor, weekday, start, reserved_end
                ) and schedule_clear(context, day, start, reserved_end, bookings):
                    yield (day, start, doctor["key"], doctor["name"], start + duration)


def candidate_days(context):
    first = context["requested_day"]
    last = min(first + context["horizon_days"], first + 14, 1_000_000)
    holidays = set(context["holidays"])
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


def schedule_clear(context, day, start, reserved_end, bookings):
    notice_ok = day > context["now_day"] or start >= context["now_minute"] + 60
    below_daily_cap = len(bookings) < 4
    no_overlap = all(
        start >= booking["end"] or reserved_end <= booking["start"]
        for booking in bookings
    )
    return notice_ok and below_daily_cap and no_overlap


def present(context):
    day, start, end, doctor = context["slot"]
    return {
        "answer": {
            "day": day,
            "start": start,
            "end": end,
            "doctor": doctor,
            "trace": list(TRACE),
        }
    }


def name_key(name):
    if not isinstance(name, str):
        return None
    cleaned = name.strip(" ")
    if not cleaned or NAME.fullmatch(cleaned) is None:
        return None
    return cleaned.lower()
