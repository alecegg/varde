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
    kind = request["kind"]
    preferred = request.get("preferred_doctor", "")
    kind = kind.strip(" ").lower() if isinstance(kind, str) else kind
    preferred = preferred.strip(" ") if isinstance(preferred, str) else preferred
    doctors = []
    for source in request["doctors"]:
        name = source["name"]
        name_is_text = isinstance(name, str)
        if name_is_text:
            name = name.strip(" ")
        key = name.lower() if name_is_text else None
        doctors.append({"name": name, "key": key, "windows": source["windows"]})
    preferred_key = preferred.lower() if isinstance(preferred, str) else None
    bookings = []
    for source in request["bookings"]:
        name = source["doctor"]
        name = name.strip(" ") if isinstance(name, str) else name
        key = name.lower() if isinstance(name, str) else None
        bookings.append(
            {
                "day": source["day"],
                "start": source["start"],
                "end": source["end"],
                "key": key,
            }
        )

    scalar_is_bad = False
    for field, (low, high) in BOUNDS.items():
        value = request[field]
        value_is_integer = type(value) is int
        value_is_in_range = value_is_integer and low <= value <= high
        if not value_is_in_range:
            scalar_is_bad = True
            break
    if (
        scalar_is_bad
        or not isinstance(kind, str)
        or kind not in KINDS
        or not isinstance(preferred, str)
        or type(request["urgent"]) is not bool
    ):
        return {"error": "BAD_REQUEST", "index": None}

    doctor_count = len(doctors)
    doctor_count_is_supported = 1 <= doctor_count <= 12
    if not doctor_count_is_supported:
        return {"error": "BAD_DOCTORS", "index": None}
    doctor_keys = set()
    for index, doctor in enumerate(doctors):
        name = doctor["name"]
        key = doctor["key"]
        name_is_text = isinstance(name, str)
        name_is_present = name_is_text and bool(name)
        name_has_allowed_characters = (
            name_is_present and NAME.fullmatch(name) is not None
        )
        name_is_duplicate = key in doctor_keys
        key_is_available = key is not None
        name_is_valid = name_has_allowed_characters and not name_is_duplicate
        if not key_is_available or not name_is_valid:
            return {"error": "BAD_DOCTORS", "index": index}
        doctor_keys.add(key)
    for index, doctor in enumerate(doctors):
        window_count = len(doctor["windows"])
        window_count_is_supported = window_count <= 8
        if not window_count_is_supported:
            return {"error": "BAD_WINDOW", "index": index}
        for window in doctor["windows"]:
            weekday = window["weekday"]
            opening = window["open"]
            closing = window["close"]
            weekday_has_integer_type = type(weekday) is int
            opening_has_integer_type = type(opening) is int
            closing_has_integer_type = type(closing) is int
            weekday_is_in_range = weekday_has_integer_type and 0 <= weekday <= 6
            window_times_are_integers = (
                opening_has_integer_type and closing_has_integer_type
            )
            opening_is_valid = window_times_are_integers and 0 <= opening < 1440
            closing_is_valid = window_times_are_integers and 0 < closing <= 1440
            interval_is_ordered = opening < closing
            interval_is_valid = (
                opening_is_valid and closing_is_valid and interval_is_ordered
            )
            if not weekday_is_in_range or not interval_is_valid:
                return {"error": "BAD_WINDOW", "index": index}

    holidays = request["holidays"]
    holiday_count = len(holidays)
    holiday_count_is_supported = holiday_count <= 60
    if not holiday_count_is_supported:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen_holidays = set()
    for index, day in enumerate(holidays):
        day_has_integer_type = type(day) is int
        day_is_in_range = day_has_integer_type and 0 <= day <= 1_000_000
        day_was_seen = day_has_integer_type and day in seen_holidays
        if not day_is_in_range or day_was_seen:
            return {"error": "BAD_HOLIDAY", "index": index}
        seen_holidays.add(day)
    booking_count = len(bookings)
    booking_count_is_supported = booking_count <= 200
    if not booking_count_is_supported:
        return {"error": "BAD_BOOKING", "index": None}
    bookings_by_day_and_doctor = {}
    for index, booking in enumerate(bookings):
        day, start, end, key = (
            booking["day"],
            booking["start"],
            booking["end"],
            booking["key"],
        )
        day_has_integer_type = type(day) is int
        start_has_integer_type = type(start) is int
        end_has_integer_type = type(end) is int
        day_is_valid = day_has_integer_type and 0 <= day <= 1_000_000
        start_is_valid = start_has_integer_type and 0 <= start < 1440
        end_is_valid = end_has_integer_type and 0 < end <= 1440
        interval_is_ordered = start < end
        interval_is_valid = start_is_valid and end_is_valid and interval_is_ordered
        booking_is_within_domain = day_is_valid and interval_is_valid
        booking_doctor_is_valid = key in doctor_keys
        if not booking_is_within_domain or not booking_doctor_is_valid:
            return {"error": "BAD_BOOKING", "index": index}
        booking_group = (day, key)
        if booking_group not in bookings_by_day_and_doctor:
            bookings_by_day_and_doctor[booking_group] = []
        bookings_by_day_and_doctor[booking_group].append(booking)
    preference_was_supplied = bool(preferred)
    preference_matches_a_doctor = preferred_key in doctor_keys
    if preference_was_supplied and not preference_matches_a_doctor:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    now_day = request["now_day"]
    now_minute = request["now_minute"]
    requested_day = request["requested_day"]
    requested_day_is_not_in_the_past = requested_day >= now_day
    days_until_requested_day = requested_day - now_day
    requested_day_is_close_enough = days_until_requested_day <= 8
    requested_day_is_valid = (
        requested_day_is_not_in_the_past and requested_day_is_close_enough
    )
    if not requested_day_is_valid:
        return {"error": "BAD_DAY_ORDER", "index": None}

    duration, buffer = KINDS[kind]
    reserved_length = duration + buffer
    eligible_doctors = doctors
    if not request["urgent"] and preferred:
        eligible_doctors = [
            doctor for doctor in doctors if doctor["key"] == preferred_key
        ]
    request_horizon_end = requested_day + request["horizon_days"]
    policy_horizon_end = requested_day + 14
    latest_supported_day = 1_000_000
    latest_day = min(request_horizon_end, policy_horizon_end, latest_supported_day)
    available_days = []
    for day in range(requested_day, latest_day + 1):
        day_has_integer_type = type(day) is int
        candidate_day_is_not_before_request = day >= requested_day
        candidate_day_is_within_horizon = day <= request_horizon_end
        candidate_day_is_supported = (
            day_has_integer_type
            and 0 <= day <= latest_supported_day
            and candidate_day_is_not_before_request
            and candidate_day_is_within_horizon
        )
        candidate_day_is_not_holiday = day not in seen_holidays
        if candidate_day_is_supported and candidate_day_is_not_holiday:
            available_days.append(day)

    slots = []
    first_grid_start = 0
    latest_grid_start = 1435
    grid_spacing = 5
    grid_stop = latest_grid_start + grid_spacing
    for day in available_days:
        weekday = day % 7
        clinic_open, clinic_close = OPENING[weekday]
        for start in range(first_grid_start, grid_stop, grid_spacing):
            start_is_within_day = 0 <= start <= latest_grid_start
            start_is_on_grid = start % grid_spacing == 0
            if not start_is_within_day or not start_is_on_grid:
                continue
            reserved_end = start + reserved_length
            reserved_interval_ends_within_day = reserved_end <= 1440
            if not reserved_interval_ends_within_day:
                continue
            starts_during_opening = start >= clinic_open
            ends_before_closing = reserved_end <= clinic_close
            reserved_interval_fits_opening = (
                starts_during_opening and ends_before_closing
            )
            if not reserved_interval_fits_opening:
                continue
            begins_before_lunch_ends = start < 780
            ends_after_lunch_starts = reserved_end > 720
            reserved_interval_intersects_lunch = (
                begins_before_lunch_ends and ends_after_lunch_starts
            )
            if reserved_interval_intersects_lunch:
                continue
            is_request_day = day == now_day
            notice_boundary = now_minute + 60
            candidate_misses_notice = is_request_day and start < notice_boundary
            if candidate_misses_notice:
                continue
            for doctor in eligible_doctors:
                in_doctor_window = False
                for window in doctor["windows"]:
                    window_matches_day = window["weekday"] == weekday
                    candidate_starts_in_window = window["open"] <= start
                    candidate_ends_in_window = reserved_end <= window["close"]
                    reserved_interval_fits_window = (
                        candidate_starts_in_window and candidate_ends_in_window
                    )
                    if window_matches_day and reserved_interval_fits_window:
                        in_doctor_window = True
                        break
                if not in_doctor_window:
                    continue
                matching_bookings = bookings_by_day_and_doctor.get(
                    (day, doctor["key"]), []
                )
                doctor_day_reached_daily_cap = len(matching_bookings) >= 4
                if doctor_day_reached_daily_cap:
                    continue
                overlaps_existing = False
                for booking in matching_bookings:
                    candidate_starts_before_booking_ends = start < booking["end"]
                    booking_starts_before_candidate_ends = (
                        booking["start"] < reserved_end
                    )
                    overlaps = (
                        candidate_starts_before_booking_ends
                        and booking_starts_before_candidate_ends
                    )
                    if overlaps:
                        overlaps_existing = True
                        break
                if overlaps_existing:
                    continue
                slots.append((day, start, doctor["key"], doctor["name"]))
    if not slots:
        return {"error": "NO_SLOT", "index": None}
    selected_slot = min(slots, key=lambda slot: (slot[0], slot[1], slot[2]))
    day, start, _, doctor = selected_slot
    appointment_end = start + duration
    trace = list(TRACE)
    success = {}
    success["day"] = day
    success["start"] = start
    success["end"] = appointment_end
    success["doctor"] = doctor
    success["trace"] = trace
    return success
