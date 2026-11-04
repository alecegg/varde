"""Natural layered clinic appointment scheduler."""

import re


def solution(request):
    """Return the earliest valid appointment or the first validation error."""
    kind_value = request["kind"]
    preferred_value = request.get("preferred_doctor", "")
    kind = kind_value.strip(" ").lower() if isinstance(kind_value, str) else kind_value
    preferred = (
        preferred_value.strip(" ")
        if isinstance(preferred_value, str)
        else preferred_value
    )
    doctors = []
    doctor_keys = set()
    for source in request["doctors"]:
        raw_name = source["name"]
        name = raw_name.strip(" ") if isinstance(raw_name, str) else raw_name
        name_is_text = isinstance(name, str)
        name_is_not_empty = name_is_text and bool(name)
        name_matches_allowed_characters = (
            name_is_not_empty and re.fullmatch(r"[A-Za-z0-9 -]+", name) is not None
        )
        key = name.lower() if isinstance(name, str) else None
        doctors.append(
            {
                "name": name,
                "key": key,
                "windows": source["windows"],
                "valid_name": name_matches_allowed_characters,
            }
        )

    bounds = {
        "now_day": (0, 1_000_000),
        "now_minute": (0, 1439),
        "requested_day": (0, 1_000_000),
        "horizon_days": (0, 14),
    }
    scalar_bad = False
    for field, (low, high) in bounds.items():
        value = request[field]
        has_integer_type = type(value) is int
        is_in_range = has_integer_type and low <= value <= high
        if not is_in_range:
            scalar_bad = True
    if (
        scalar_bad
        or not isinstance(kind, str)
        or kind not in {"checkup", "consultation", "procedure"}
        or not isinstance(preferred, str)
        or type(request["urgent"]) is not bool
    ):
        return {"error": "BAD_REQUEST", "index": None}

    doctor_count = len(doctors)
    has_allowed_doctor_count = 1 <= doctor_count <= 12
    if not has_allowed_doctor_count:
        return {"error": "BAD_DOCTORS", "index": None}
    for index, doctor in enumerate(doctors):
        name = doctor["name"]
        key = doctor["key"]
        name_is_allowed = doctor["valid_name"]
        name_is_duplicate = key in doctor_keys
        if not name_is_allowed or not isinstance(name, str) or name_is_duplicate:
            return {"error": "BAD_DOCTORS", "index": index}
        doctor_keys.add(key)
    for index, doctor in enumerate(doctors):
        windows = doctor["windows"]
        if len(windows) > 8:
            return {"error": "BAD_WINDOW", "index": index}
        for window in windows:
            weekday = window["weekday"]
            opening = window["open"]
            closing = window["close"]
            weekday_is_integer = type(weekday) is int
            opening_is_integer = type(opening) is int
            closing_is_integer = type(closing) is int
            weekday_is_known = weekday_is_integer and 0 <= weekday <= 6
            times_have_integer_types = opening_is_integer and closing_is_integer
            opening_is_valid = times_have_integer_types and 0 <= opening < closing
            closing_is_valid = times_have_integer_types and closing <= 1440
            if not weekday_is_known or not opening_is_valid or not closing_is_valid:
                return {"error": "BAD_WINDOW", "index": index}

    holidays = request["holidays"]
    holiday_count = len(holidays)
    has_allowed_holiday_count = holiday_count <= 60
    if not has_allowed_holiday_count:
        return {"error": "BAD_HOLIDAY", "index": None}
    seen_holidays = set()
    for index, day in enumerate(holidays):
        day_is_integer = type(day) is int
        day_is_in_range = day_is_integer and 0 <= day <= 1_000_000
        day_is_repeated = day_is_integer and day in seen_holidays
        if not day_is_in_range or day_is_repeated:
            return {"error": "BAD_HOLIDAY", "index": index}
        seen_holidays.add(day)

    source_bookings = request["bookings"]
    if len(source_bookings) > 200:
        return {"error": "BAD_BOOKING", "index": None}
    bookings = []
    for index, booking in enumerate(source_bookings):
        raw_doctor = booking["doctor"]
        booking_name = (
            raw_doctor.strip(" ") if isinstance(raw_doctor, str) else raw_doctor
        )
        booking_key = booking_name.lower() if isinstance(booking_name, str) else None
        day, start, end = booking["day"], booking["start"], booking["end"]
        day_has_integer_type = type(day) is int
        day_is_valid = day_has_integer_type and 0 <= day <= 1_000_000
        start_has_integer_type = type(start) is int
        end_has_integer_type = type(end) is int
        times_are_integers = start_has_integer_type and end_has_integer_type
        start_is_valid = times_are_integers and 0 <= start < 1440
        end_is_valid = times_are_integers and 0 < end <= 1440
        interval_is_ordered = times_are_integers and start < end
        interval_is_valid = start_is_valid and end_is_valid and interval_is_ordered
        doctor_is_known = booking_key in doctor_keys
        if not day_is_valid or not interval_is_valid or not doctor_is_known:
            return {"error": "BAD_BOOKING", "index": index}
        bookings.append({"day": day, "start": start, "end": end, "key": booking_key})

    preferred_key = preferred.strip(" ").lower()
    if preferred and preferred_key not in doctor_keys:
        return {"error": "UNKNOWN_DOCTOR", "index": None}
    now_day = request["now_day"]
    now_minute = request["now_minute"]
    requested_day = request["requested_day"]
    if not now_day <= requested_day <= now_day + 8:
        return {"error": "BAD_DAY_ORDER", "index": None}

    durations = {"checkup": (20, 5), "consultation": (30, 10), "procedure": (60, 15)}
    duration, buffer = durations[kind]
    if not request["urgent"] and preferred:
        doctors = [doctor for doctor in doctors if doctor["key"] == preferred_key]
    last_day = min(
        requested_day + request["horizon_days"], requested_day + 14, 1_000_000
    )
    eligible_days = []
    for day_number in range(requested_day, last_day + 1):
        is_listed_holiday = day_number in seen_holidays
        if not is_listed_holiday:
            eligible_days.append(day_number)
    candidates = []
    for day in eligible_days:
        weekday = day % 7
        if weekday < 5:
            clinic_open, clinic_close = 540, 1020
        elif weekday == 5:
            clinic_open, clinic_close = 600, 840
        else:
            clinic_open, clinic_close = 0, 0
        for start in range(0, 1440, 5):
            reserved_end = start + duration + buffer
            intersects_lunch = start < 780 and reserved_end > 720
            if intersects_lunch:
                continue
            begins_before_open = start < clinic_open
            ends_after_close = reserved_end > clinic_close
            if begins_before_open or ends_after_close:
                continue
            is_today = day == now_day
            notice_boundary = now_minute + 60
            if is_today and start < notice_boundary:
                continue
            for doctor in doctors:
                window_match = False
                for window in doctor["windows"]:
                    window_is_for_weekday = window["weekday"] == weekday
                    candidate_is_after_window_open = window["open"] <= start
                    candidate_is_before_window_close = reserved_end <= window["close"]
                    fits_configured_interval = (
                        window_is_for_weekday
                        and candidate_is_after_window_open
                        and candidate_is_before_window_close
                    )
                    if fits_configured_interval:
                        window_match = True
                        break
                if not window_match:
                    continue
                day_bookings = []
                for booking in bookings:
                    booking_is_for_day = booking["day"] == day
                    booking_is_for_doctor = booking["key"] == doctor["key"]
                    if booking_is_for_day and booking_is_for_doctor:
                        day_bookings.append(booking)
                daily_booking_count = len(day_bookings)
                daily_limit_reached = daily_booking_count >= 4
                if daily_limit_reached:
                    continue
                conflict = False
                for booking in day_bookings:
                    candidate_starts_before_booking_ends = start < booking["end"]
                    booking_starts_before_candidate_ends = (
                        booking["start"] < reserved_end
                    )
                    intervals_intersect = (
                        candidate_starts_before_booking_ends
                        and booking_starts_before_candidate_ends
                    )
                    if intervals_intersect:
                        conflict = True
                        break
                if conflict:
                    continue
                candidates.append((day, start, doctor["key"], doctor["name"]))

    if not candidates:
        return {"error": "NO_SLOT", "index": None}
    chosen_day, chosen_start, _, chosen_name = min(
        candidates, key=lambda candidate: (candidate[0], candidate[1], candidate[2])
    )
    appointment_end = chosen_start + duration
    chosen_trace = [
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
    ]
    success = {}
    success["day"] = chosen_day
    success["start"] = chosen_start
    success["end"] = appointment_end
    success["doctor"] = chosen_name
    success["trace"] = chosen_trace
    return success
