"""Return an integer-cent rental quote or the first contract error."""


def solution(request: dict) -> dict:
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    return Quote(request).run()


class Quote:
    def __init__(self, request):
        self.data = dict(request)
        self.data["property_id"] = request["property_id"].strip().upper()
        self.data["promo_code"] = request["promo_code"].strip().upper()
        self.data["extras"] = [value.strip().upper() for value in request["extras"]]
        self.data["bookings"] = [
            (row["property_id"].strip().upper(), row["arrival"], row["departure"])
            for row in request["bookings"]
        ]

    def run(self):
        error = self.check_all()
        if error:
            return error
        self.data["nights"] = self.make_nights()
        count = self.data["departure"] - self.data["arrival"]
        subtotal = sum(row["night_cents"] for row in self.data["nights"])
        base = self.quote_amounts(count, subtotal)
        reductions = self.discount_amounts(base)
        applied = self.service_names(base) + self.discount_names(reductions)
        return self.make_quote(base, reductions, applied)

    def check_all(self):
        error = self.check_identity()
        if error:
            return error
        error = self.check_days()
        if error:
            return error
        error = self.check_extras()
        if error:
            return error
        error = self.check_bookings()
        if error:
            return error
        error = self.check_stay()
        if error:
            return error
        data = self.data
        count = data["departure"] - data["arrival"]
        error = self.check_season(data, count)
        if error:
            return error
        return self.check_opening()

    def check_identity(self):
        data = self.data
        checks = (
            (data["property_id"] not in ("CEDAR", "LAKE"), "BAD_PROPERTY"),
            (
                type(data["adults"]) is not int or not 1 <= data["adults"] <= 8,
                "BAD_ADULTS",
            ),
            (
                type(data["children"]) is not int or not 0 <= data["children"] <= 8,
                "BAD_CHILDREN",
            ),
        )
        return next(
            ({"error": code, "index": None} for invalid, code in checks if invalid),
            None,
        )

    def check_days(self):
        start, end = self.data["arrival"], self.data["departure"]
        invalid = (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= 1_000_000
            or not 0 <= end <= 1_000_000
            or end <= start
        )
        return {"error": "BAD_DAYS", "index": None} if invalid else None

    def check_extras(self):
        values = self.data["extras"]
        if len(values) > 4:
            return {"error": "BAD_EXTRA", "index": None}
        seen = set()
        for index, value in enumerate(values):
            if value not in ("PARKING", "PET") or value in seen:
                return {"error": "BAD_EXTRA", "index": index}
            seen.add(value)

    def check_bookings(self):
        rows = self.data["bookings"]
        if len(rows) > 100:
            return {"error": "BAD_BOOKING", "index": None}
        for index, (prop, start, end) in enumerate(rows):
            invalid = (
                prop not in ("CEDAR", "LAKE")
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start <= 1_000_000
                or not 0 <= end <= 1_000_000
                or end <= start
            )
            if invalid:
                return {"error": "BAD_BOOKING", "index": index}

    def check_stay(self):
        data = self.data
        count = data["departure"] - data["arrival"]
        if not 1 <= count <= 30:
            return {"error": "BAD_STAY", "index": None}
        limit = 4 if data["property_id"] == "CEDAR" else 6
        if data["adults"] + data["children"] > limit:
            return {"error": "OVER_CAPACITY", "index": None}

    def check_season(self, data, count):
        seasons = ((0, 120, 1), (120, 240, 3), (240, 365, 2))
        for lower, upper, minimum in seasons:
            occurs = any(
                lower <= day % 365 < upper
                for day in range(data["arrival"], data["departure"])
            )
            if occurs and count < minimum:
                return {"error": "MIN_STAY", "index": None}

    def check_opening(self):
        data = self.data
        for index, (prop, start, end) in enumerate(data["bookings"]):
            if (
                prop == data["property_id"]
                and data["arrival"] < end
                and start < data["departure"]
            ):
                return {"error": "UNAVAILABLE", "index": index}
        if self.data["promo_code"] not in ("", "PCT10", "FIXED5000", "ONENIGHT"):
            return {"error": "BAD_PROMO", "index": None}

    def make_nights(self):
        rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
        rows = []
        for day in range(self.data["arrival"], self.data["departure"]):
            position = day % 365
            name = "LOW" if position < 120 else "PEAK" if position < 240 else "SHOULDER"
            weekend = 1500 if day % 7 in (4, 5) else 0
            rows.append(
                {
                    "day": day,
                    "season": name,
                    "base_cents": rates[name],
                    "weekend_cents": weekend,
                    "night_cents": rates[name] + weekend,
                }
            )
        return rows

    def quote_amounts(self, count, subtotal):
        data = self.data
        guests = (2000 * max(0, data["adults"] - 2) + 1000 * data["children"]) * count
        tax = 800 * (data["adults"] + data["children"]) * min(count, 5)
        extras = sum(
            1200 * count if item == "PARKING" else 2500 for item in data["extras"]
        )
        return {
            "count": count,
            "subtotal": subtotal,
            "guests": guests,
            "tax": tax,
            "extras": extras,
            "before": subtotal + 4500 + guests + tax + extras,
        }

    def discount_amounts(self, base):
        count, subtotal, before = base["count"], base["subtotal"], base["before"]
        rate = 15 if count >= 14 else 10 if count >= 7 else 0
        long_cut = (2 * subtotal * rate + 100) // 200
        remaining = before - long_cut
        promo = self.promo_amount(remaining)
        total = remaining - promo
        deposit = min(total, max(10000, (2 * total * 30 + 100) // 200))
        return {"long": long_cut, "promo": promo, "total": total, "deposit": deposit}

    def promo_amount(self, remaining):
        code = self.data["promo_code"]
        if code == "PCT10":
            return (2 * remaining * 10 + 100) // 200
        if code == "FIXED5000":
            return min(5000, remaining)
        if code == "ONENIGHT":
            return min(row["night_cents"] for row in self.data["nights"])
        return 0

    def make_quote(self, base, reductions, applied):
        nights = self.data["nights"]
        arrival = self.data["arrival"]
        cancellation = (
            "FLEX" if arrival >= 30 else "STANDARD" if arrival >= 7 else "FIRM"
        )
        fields = self.quote_fields(base, reductions, applied, nights)
        fields["cancellation"] = cancellation
        return fields

    def quote_fields(self, base, reductions, applied, nights):
        return {
            "nights": len(nights),
            "night_lines": nights,
            "cleaning_fee": 4500,
            "extra_guest_fee": base["guests"],
            "tourist_tax": base["tax"],
            "extras_fee": base["extras"],
            "long_stay_discount": reductions["long"],
            "promo_discount": reductions["promo"],
            "total": reductions["total"],
            "deposit": reductions["deposit"],
            "balance_due": reductions["total"] - reductions["deposit"],
            "applied": applied,
        }

    def service_names(self, base):
        data, nights = self.data, self.data["nights"]
        return [
            name
            for active, name in (
                (any(row["weekend_cents"] for row in nights), "weekend"),
                (True, "cleaning"),
                (base["guests"] > 0, "extra-guests"),
                (True, "tourist-tax"),
                ("PARKING" in data["extras"], "parking"),
                ("PET" in data["extras"], "pet"),
            )
            if active
        ]

    def discount_names(self, reductions):
        return [
            name
            for active, name in (
                (reductions["long"] > 0, "long-stay"),
                (reductions["promo"] > 0, "promo"),
                (reductions["total"] > 0, "deposit"),
            )
            if active
        ]
