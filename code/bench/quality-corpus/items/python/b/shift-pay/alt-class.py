"""Calculate weekly shift pay using exact integer-minute arithmetic."""

BASE_QUARTERS = {"helper": 120, "nurse": 160, "lead": 200}
INTEGER_FIELDS = (
    ("day", 6, "BAD_DAY"),
    ("start", 1439, "BAD_START"),
    ("end", 1439, "BAD_END"),
    ("break", 240, "BAD_BREAK"),
)
FLAG_FIELDS = (("holiday", "BAD_HOLIDAY"), ("callout", "BAD_CALLOUT"))
WEEK_OFFSETS = (-10080, 0, 10080)
ROW_FIELDS = (
    "day",
    "start",
    "end",
    "paid_minutes",
    "regular_minutes",
    "overtime_minutes",
    "night_minutes",
    "weekend_minutes",
    "holiday_minutes",
    "callout_minutes",
    "bonus_cents",
    "cents",
    "_amount",
    "_daily",
    "_weekly",
)
RULE_FIELDS = (
    ("_daily", "daily-overtime"),
    ("_weekly", "weekly-overtime"),
    ("night_minutes", "night-premium"),
    ("weekend_minutes", "weekend-premium"),
    ("holiday_minutes", "holiday-rate"),
    ("callout_minutes", "callout-minimum"),
    ("bonus_cents", "bonus"),
)


def solution(request):
    """Return ordered shift pay rows or the first contract validation error."""
    return ShiftPay(request).price_week()


class ShiftPay:
    def __init__(self, request):
        self.role = request["role"].strip().lower()
        self.shifts = request["shifts"]
        self.bonus = request["bonus"]
        self.rows = []
        self.failure = self.check_request()
        if self.failure is None:
            self.failure = self.read_shifts() or self.check_overlap()

    def check_request(self):
        rules = (
            (self.role in BASE_QUARTERS, "BAD_ROLE"),
            (bool(self.shifts), "EMPTY_WEEK"),
            (len(self.shifts) <= 14, "TOO_MANY_SHIFTS"),
            (type(self.bonus) is bool, "BAD_BONUS"),
        )
        for valid, code in rules:
            if not valid:
                return {"error": code, "index": None}

    def read_shifts(self):
        for index, source in enumerate(self.shifts):
            row = dict(source)
            row["index"] = index
            if error := self.check_fields(row):
                return error
            if error := self.check_duration(row):
                return error
            self.rows.append(row)

    def check_fields(self, row):
        index = row["index"]
        for field, high, code in INTEGER_FIELDS:
            value = row[field]
            if type(value) is not int or not 0 <= value <= high:
                return {"error": code, "index": index}
        for field, code in FLAG_FIELDS:
            if type(row[field]) is not bool:
                return {"error": code, "index": index}

    def check_duration(self, row):
        length = (row["end"] - row["start"]) % 1440 or 1440
        if not 1 <= length <= 960:
            return {"error": "BAD_LENGTH", "index": row["index"]}
        if row["break"] > length:
            return {"error": "BREAK_TOO_LONG", "index": row["index"]}
        unpaid = row["break"] if length > 360 else 0
        row.update(
            duration=length,
            paid=length - unpaid,
            timeline=row["day"] * 1440 + row["start"],
        )

    def check_overlap(self):
        overlaps = [
            (start, max(left["index"], right["index"]))
            for place, left in enumerate(self.rows)
            for right in self.rows[place + 1 :]
            for offset in WEEK_OFFSETS
            if (start := self.overlap_start(left, right, offset)) is not None
        ]
        if overlaps:
            return {"error": "OVERLAP", "index": min(overlaps)[1]}

    def overlap_start(self, left, right, offset):
        begin = max(left["timeline"], right["timeline"] + offset)
        finish = min(
            left["timeline"] + left["duration"],
            right["timeline"] + offset + right["duration"],
        )
        return begin if begin < finish else None

    def minute_rate(self, row, base, prior, offset, unpaid):
        absolute = row["timeline"] + offset + unpaid
        day, minute = divmod(absolute, 1440)
        day %= 7
        overtime = offset >= 480 or prior + offset >= 2400
        night, weekend, holiday = (
            minute >= 1320 or minute < 360,
            day >= 5,
            row["holiday"],
        )
        rate = (
            base
            + base // 2 * overtime
            + base // 5 * night
            + base // 4 * weekend
            + base * holiday
        )
        return (
            overtime,
            night,
            weekend,
            holiday,
            rate,
            offset >= 480,
            prior + offset >= 2400,
        )

    def shift_totals(self, row, base, prior):
        counts = dict.fromkeys(
            ("regular", "overtime", "night", "weekend", "holiday"), 0
        )
        amount = 0
        daily = weekly = False
        unpaid = row["break"] if row["duration"] > 360 else 0
        for offset in range(row["paid"]):
            flags = self.minute_rate(row, base, prior, offset, unpaid)
            amount, daily, weekly = self.record_minute(
                counts, flags, amount, daily, weekly
            )
        return amount, counts, daily, weekly

    def record_minute(self, counts, flags, amount, daily, weekly):
        overtime, night, weekend, holiday, rate, daily_flag, weekly_flag = flags
        counts["overtime" if overtime else "regular"] += 1
        counts["night"] += night
        counts["weekend"] += weekend
        counts["holiday"] += holiday
        return amount + rate, daily or daily_flag, weekly or weekly_flag

    def shift_record(self, row, totals, base):
        amount, counts, daily, weekly = totals
        callout = max(0, 180 - row["paid"]) if row["callout"] else 0
        amount += base * callout
        fields = (
            row["day"],
            row["start"],
            row["end"],
            row["paid"],
            counts["regular"],
            counts["overtime"],
            counts["night"],
            counts["weekend"],
            counts["holiday"],
            callout,
            0,
            (amount + 2) // 4,
            amount,
            daily,
            weekly,
        )
        return dict(zip(ROW_FIELDS, fields, strict=True))

    def price_week(self):
        if self.failure:
            return self.failure
        priced, prior = [], 0
        base = BASE_QUARTERS[self.role]
        for row in self.rows:
            result = self.shift_record(row, self.shift_totals(row, base, prior), base)
            priced.append(result)
            prior += result["paid_minutes"]
        if self.bonus and prior >= 600:
            priced[-1]["bonus_cents"] = 500
            priced[-1]["cents"] = (priced[-1]["_amount"] + 2002) // 4
        return self.week_record(priced, prior)

    def week_record(self, rows, paid):
        public = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in rows
        ]
        applied = [
            name
            for field, name in RULE_FIELDS
            if any(row[field] for row in rows) is True
        ]
        return {
            "shifts": public,
            "weekly_paid_minutes": paid,
            "weekly_cents": sum(row["cents"] for row in public),
            "applied": applied,
        }
