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


def solution(request):
    """Return ordered shift pay rows or the first contract validation error."""
    role = request["role"].strip().lower()
    return PayWeek(role, request["shifts"], request["bonus"]).calculate()


def request_error(role, shifts, bonus):
    checks = (
        (role in BASE_QUARTERS, "BAD_ROLE"),
        (bool(shifts), "EMPTY_WEEK"),
        (len(shifts) <= 14, "TOO_MANY_SHIFTS"),
        (type(bonus) is bool, "BAD_BONUS"),
    )
    for valid, code in checks:
        if not valid:
            return {"error": code, "index": None}


def integer_error(row, index):
    for field, high, code in INTEGER_FIELDS:
        value = row[field]
        if type(value) is not int or not 0 <= value <= high:
            return {"error": code, "index": index}
    for field, code in FLAG_FIELDS:
        if type(row[field]) is not bool:
            return {"error": code, "index": index}


def duration_error(row, index):
    length = (row["end"] - row["start"]) % 1440 or 1440
    rules = (
        (not 1 <= length <= 960, "BAD_LENGTH"),
        (row["break"] > length, "BREAK_TOO_LONG"),
    )
    for invalid, code in rules:
        if invalid:
            return {"error": code, "index": index}
    return length


def overlap_start(left, right, offset):
    begin = max(left["timeline"], right["timeline"] + offset)
    finish = min(
        left["timeline"] + left["duration"],
        right["timeline"] + offset + right["duration"],
    )
    return begin if begin < finish else None


def find_overlap(rows):
    hits = [
        (start, max(left["index"], right["index"]))
        for position, left in enumerate(rows)
        for right in rows[position + 1 :]
        for offset in WEEK_OFFSETS
        if (start := overlap_start(left, right, offset)) is not None
    ]
    return {"error": "OVERLAP", "index": min(hits)[1]} if hits else None


def minute_rate(row, base, prior, offset, break_offset):
    absolute = row["timeline"] + offset + break_offset
    day, minute = divmod(absolute, 1440)
    day %= 7
    overtime = offset >= 480 or prior + offset >= 2400
    night, weekend, holiday = minute >= 1320 or minute < 360, day >= 5, row["holiday"]
    rate = (
        base
        + base // 2 * overtime
        + base // 5 * night
        + base // 4 * weekend
        + base * holiday
    )
    return overtime, night, weekend, holiday, rate


def shift_values(row, base, prior):
    counts = [0] * 5
    amount = 0
    paid = row["paid"]
    daily, weekly = paid > 480, prior + paid > 2400
    unpaid = row["break"] * (row["duration"] > 360)
    for offset in range(paid):
        overtime, night, weekend, holiday, rate = minute_rate(
            row, base, prior, offset, unpaid
        )
        counts[int(overtime)] += 1
        counts[2] += night
        counts[3] += weekend
        counts[4] += holiday
        amount += rate
    return amount, counts, daily, weekly


def shift_record(row, totals, base):
    amount, counts, daily, weekly = totals
    callout = max(0, 180 - row["paid"]) if row["callout"] else 0
    amount += base * callout
    data = (
        row["day"],
        row["start"],
        row["end"],
        row["paid"],
        *counts,
        callout,
        0,
        (amount + 2) // 4,
        amount,
        daily,
        weekly,
    )
    return dict(zip(ROW_FIELDS, data, strict=True))


def output_record(rows, paid):
    public = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    applied = rule_names(rows)
    return {
        "shifts": public,
        "weekly_paid_minutes": paid,
        "weekly_cents": sum(row["cents"] for row in public),
        "applied": applied,
    }


def rule_names(rows):
    labels = (
        ("_daily", "daily-overtime"),
        ("_weekly", "weekly-overtime"),
        ("night_minutes", "night-premium"),
        ("weekend_minutes", "weekend-premium"),
        ("holiday_minutes", "holiday-rate"),
        ("callout_minutes", "callout-minimum"),
        ("bonus_cents", "bonus"),
    )
    return [label for field, label in labels if any(row[field] for row in rows)]


class PayWeek:
    def __init__(self, role, shifts, bonus):
        self.role = role
        self.shifts = shifts
        self.bonus = bonus
        self.rows = []
        self.failure = request_error(role, shifts, bonus)
        if self.failure is None:
            self.failure = self.check_shifts() or find_overlap(self.rows)

    def check_shifts(self):
        for index, shift in enumerate(self.shifts):
            row = dict(shift)
            row["index"] = index
            if failure := integer_error(row, index):
                return failure
            length = duration_error(row, index)
            if isinstance(length, dict):
                return length
            unpaid = row["break"] if length > 360 else 0
            row.update(
                duration=length,
                paid=length - unpaid,
                timeline=row["day"] * 1440 + row["start"],
            )
            self.rows.append(row)

    def calculate(self):
        if self.failure:
            return self.failure
        priced, prior = [], 0
        base = BASE_QUARTERS[self.role]
        for row in self.rows:
            totals = shift_values(row, base, prior)
            result = shift_record(row, totals, base)
            priced.append(result)
            prior += result["paid_minutes"]
        if self.bonus and prior >= 600:
            priced[-1]["bonus_cents"] = 500
            priced[-1]["cents"] = (priced[-1]["_amount"] + 2002) // 4
        return output_record(priced, prior)
