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
    return Booking(request).run()


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


class Booking:
    def __init__(self, request):
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
        self.data = data

    def run(self):
        error = self.check_scalars()
        if error:
            return error
        error = self.check_doctors()
        if error:
            return error
        error = self.check_windows()
        if error:
            return error
        error = self.check_holidays()
        if error:
            return error
        error = self.check_bookings()
        if error:
            return error
        error = self.check_order()
        if error:
            return error
        slot = self.next_slot()
        return self.assemble(slot) if slot else {"error": "NO_SLOT", "index": None}

    def check_scalars(self):
        data = self.data
        if (
            any(
                type(data[key]) is not int or not low <= data[key] <= high
                for key, (low, high) in BOUNDS.items()
            )
            or not isinstance(data["kind"], str)
            or data["kind"] not in KINDS
            or not isinstance(data["preferred_doctor"], str)
            or type(data["urgent"]) is not bool
        ):
            return {"error": "BAD_REQUEST", "index": None}
        return None

    def check_doctors(self):
        doctors = self.data["doctors"]
        if not 1 <= len(doctors) <= 12:
            return {"error": "BAD_DOCTORS", "index": None}
        names = set()
        for index, doctor in enumerate(doctors):
            key = doctor["key"]
            if key is None or key in names:
                return {"error": "BAD_DOCTORS", "index": index}
            names.add(key)
        return None

    def check_windows(self):
        for index, doctor in enumerate(self.data["doctors"]):
            windows = doctor["windows"]
            if len(windows) > 8:
                return {"error": "BAD_WINDOW", "index": index}
            for window in windows:
                day, opening, closing = (
                    window["weekday"],
                    window["open"],
                    window["close"],
                )
                if (
                    type(day) is not int
                    or not 0 <= day <= 6
                    or type(opening) is not int
                    or type(closing) is not int
                    or not 0 <= opening < closing <= 1440
                ):
                    return {"error": "BAD_WINDOW", "index": index}
        return None

    def check_holidays(self):
        holidays = self.data["holidays"]
        if len(holidays) > 60:
            return {"error": "BAD_HOLIDAY", "index": None}
        seen = set()
        for index, day in enumerate(holidays):
            if type(day) is not int or not 0 <= day <= 1_000_000 or day in seen:
                return {"error": "BAD_HOLIDAY", "index": index}
            seen.add(day)
        return None

    def check_bookings(self):
        bookings = self.data["bookings"]
        if len(bookings) > 200:
            return {"error": "BAD_BOOKING", "index": None}
        names = {doctor["key"] for doctor in self.data["doctors"]}
        for index, booking in enumerate(bookings):
            if not self.valid_booking(booking, names):
                return {"error": "BAD_BOOKING", "index": index}
        return None

    def valid_booking(self, booking, names):
        day, start, end = booking["day"], booking["start"], booking["end"]
        return (
            type(day) is int
            and 0 <= day <= 1_000_000
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= 1440
            and booking["key"] in names
        )

    def check_order(self):
        data = self.data
        preferred = data["preferred_doctor"]
        names = {doctor["key"] for doctor in data["doctors"]}
        if preferred and data["preferred_key"] not in names:
            return {"error": "UNKNOWN_DOCTOR", "index": None}
        if not data["now_day"] <= data["requested_day"] <= data["now_day"] + 8:
            return {"error": "BAD_DAY_ORDER", "index": None}
        return None

    def eligible_doctors(self):
        data = self.data
        if not data["urgent"] and data["preferred_doctor"]:
            return [
                doctor
                for doctor in data["doctors"]
                if doctor["key"] == data["preferred_key"]
            ]
        return data["doctors"]

    def next_slot(self):
        data = self.data
        duration, buffer = KINDS[data["kind"]]
        doctors = self.eligible_doctors()
        for day in self.candidate_days():
            weekday = day % 7
            for start in range(0, 1440, 5):
                reserved_end = start + duration + buffer
                choices = []
                for doctor in doctors:
                    bookings = self.bookings_for(day, doctor)
                    if self.valid_candidate(
                        doctor, weekday, start, reserved_end, day, bookings
                    ):
                        choices.append(
                            (
                                day,
                                start,
                                doctor["key"],
                                doctor["name"],
                                start + duration,
                            )
                        )
                if choices:
                    return self.select_slot(choices)
        return None

    def bookings_for(self, day, doctor):
        return [
            booking
            for booking in self.data["bookings"]
            if booking["day"] == day and booking["key"] == doctor["key"]
        ]

    def select_slot(self, choices):
        day, start, _, doctor, end = min(choices)
        return day, start, end, doctor

    def valid_candidate(self, doctor, weekday, start, reserved_end, day, bookings):
        opening = OPENING[weekday]
        matches_window = any(
            window["weekday"] == weekday
            and window["open"] <= start
            and reserved_end <= window["close"]
            for window in doctor["windows"]
        )
        return (
            matches_window
            and opening[0] <= start
            and reserved_end <= opening[1]
            and not (start < 780 and reserved_end > 720)
            and (day > self.data["now_day"] or start >= self.data["now_minute"] + 60)
            and len(bookings) < 4
            and all(
                start >= booking["end"] or reserved_end <= booking["start"]
                for booking in bookings
            )
        )

    def candidate_days(self):
        data = self.data
        first = data["requested_day"]
        last = min(first + data["horizon_days"], first + 14, 1_000_000)
        holidays = set(data["holidays"])
        return [day for day in range(first, last + 1) if day not in holidays]

    def assemble(self, slot):
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
