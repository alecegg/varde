def solution(request: dict) -> dict:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    property_id = request["property_id"].strip().upper()
    arrival = request["arrival"]
    departure = request["departure"]
    adults = request["adults"]
    children = request["children"]
    extras = [value.strip().upper() for value in request["extras"]]
    bookings = request["bookings"]
    promo = request["promo_code"].strip().upper()
    capacity_by_property = {"CEDAR": 4, "LAKE": 6}
    season_rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
    season_minimums = {"LOW": 1, "PEAK": 3, "SHOULDER": 2}
    season_boundaries = (120, 240)
    days_per_season_year = 365
    days_per_week = 7
    weekend_days = {4, 5}
    weekend_surcharge = 1500
    minimum_adults = 1
    maximum_adults = 8
    minimum_children = 0
    maximum_children = 8
    allowed_extras = {"PARKING", "PET"}
    allowed_promos = {"", "PCT10", "FIXED5000", "ONENIGHT"}
    minimum_day = 0
    maximum_day = 1_000_000
    if property_id not in capacity_by_property:
        return {"error": "BAD_PROPERTY", "index": None}
    adults_are_integer = type(adults) is int
    adults_meet_minimum = adults_are_integer and adults >= minimum_adults
    adults_meet_maximum = adults_are_integer and adults <= maximum_adults
    adults_are_valid = adults_meet_minimum and adults_meet_maximum
    if not adults_are_valid:
        return {"error": "BAD_ADULTS", "index": None}
    children_are_integer = type(children) is int
    children_meet_minimum = children_are_integer and children >= minimum_children
    children_meet_maximum = children_are_integer and children <= maximum_children
    children_are_valid = children_meet_minimum and children_meet_maximum
    if not children_are_valid:
        return {"error": "BAD_CHILDREN", "index": None}
    arrival_is_integer = type(arrival) is int
    departure_is_integer = type(departure) is int
    arrival_is_nonnegative = arrival_is_integer and arrival >= minimum_day
    arrival_is_bounded = arrival_is_integer and arrival <= maximum_day
    departure_is_nonnegative = departure_is_integer and departure >= minimum_day
    departure_is_bounded = departure_is_integer and departure <= maximum_day
    arrival_is_valid = (
        arrival_is_integer and arrival_is_nonnegative and arrival_is_bounded
    )
    departure_is_valid = (
        departure_is_integer and departure_is_nonnegative and departure_is_bounded
    )
    arrival_in_range = arrival_is_nonnegative and arrival_is_bounded
    departure_in_range = departure_is_nonnegative and departure_is_bounded
    departure_follows_arrival = (
        arrival_is_integer and departure_is_integer and departure > arrival
    )
    days_are_valid = (
        arrival_is_valid
        and departure_is_valid
        and arrival_in_range
        and departure_in_range
        and departure_follows_arrival
    )
    if not days_are_valid:
        return {"error": "BAD_DAYS", "index": None}
    extras_count = len(extras)
    extras_count_is_valid = extras_count <= 4
    if not extras_count_is_valid:
        return {"error": "BAD_EXTRA", "index": None}
    seen = set()
    for index, extra in enumerate(extras):
        extra_is_allowed = extra in allowed_extras
        extra_was_seen = extra in seen
        if not extra_is_allowed or extra_was_seen:
            return {"error": "BAD_EXTRA", "index": index}
        seen.add(extra)
    booking_count = len(bookings)
    booking_count_is_valid = booking_count <= 100
    if not booking_count_is_valid:
        return {"error": "BAD_BOOKING", "index": None}
    normalized_bookings = []
    for index, booking in enumerate(bookings):
        booked_property = booking["property_id"].strip().upper()
        booked_arrival = booking["arrival"]
        booked_departure = booking["departure"]
        booking_days_are_integers = (
            type(booked_arrival) is int and type(booked_departure) is int
        )
        booking_arrival_is_nonnegative = (
            booking_days_are_integers and booked_arrival >= minimum_day
        )
        booking_arrival_is_bounded = (
            booking_days_are_integers and booked_arrival <= maximum_day
        )
        booking_departure_is_nonnegative = (
            booking_days_are_integers and booked_departure >= minimum_day
        )
        booking_departure_is_bounded = (
            booking_days_are_integers and booked_departure <= maximum_day
        )
        booking_days_are_in_range = (
            booking_arrival_is_nonnegative
            and booking_arrival_is_bounded
            and booking_departure_is_nonnegative
            and booking_departure_is_bounded
        )
        booking_has_positive_length = (
            booking_days_are_integers and booked_departure > booked_arrival
        )
        booking_property_is_known = booked_property in capacity_by_property
        if not booking_property_is_known:
            return {"error": "BAD_BOOKING", "index": index}
        if not booking_days_are_in_range:
            return {"error": "BAD_BOOKING", "index": index}
        if not booking_has_positive_length:
            return {"error": "BAD_BOOKING", "index": index}
        normalized_bookings.append((booked_property, booked_arrival, booked_departure))
    night_count = departure - arrival
    minimum_stay_nights = 1
    maximum_stay_nights = 30
    stay_meets_minimum = night_count >= minimum_stay_nights
    stay_meets_maximum = night_count <= maximum_stay_nights
    if not stay_meets_minimum or not stay_meets_maximum:
        return {"error": "BAD_STAY", "index": None}
    guest_count = adults + children
    property_capacity = capacity_by_property[property_id]
    guest_count_exceeds_capacity = guest_count > property_capacity
    remaining_guest_slots = property_capacity - guest_count
    capacity_is_sufficient = remaining_guest_slots >= 0
    if guest_count_exceeds_capacity or not capacity_is_sufficient:
        return {"error": "OVER_CAPACITY", "index": None}
    season_counts = {"LOW": 0, "PEAK": 0, "SHOULDER": 0}
    for day in range(arrival, departure):
        season_day = day % days_per_season_year
        if season_day < season_boundaries[0]:
            season = "LOW"
        elif season_day < season_boundaries[1]:
            season = "PEAK"
        else:
            season = "SHOULDER"
        season_counts[season] += 1
    for season in ("LOW", "PEAK", "SHOULDER"):
        season_is_occupied = season_counts[season] > 0
        minimum_nights = season_minimums[season]
        stay_is_too_short = night_count < minimum_nights
        minimum_is_violated = season_is_occupied and stay_is_too_short
        if minimum_is_violated:
            return {"error": "MIN_STAY", "index": None}
    for index, (booked_property, booked_arrival, booked_departure) in enumerate(
        normalized_bookings
    ):
        same_property = booked_property == property_id
        requested_starts_before_booking_ends = arrival < booked_departure
        booking_starts_before_requested_ends = booked_arrival < departure
        overlaps_requested_stay = (
            requested_starts_before_booking_ends
            and booking_starts_before_requested_ends
        )
        if same_property and overlaps_requested_stay:
            return {"error": "UNAVAILABLE", "index": index}
    promo_is_supported = promo in allowed_promos
    if not promo_is_supported:
        return {"error": "BAD_PROMO", "index": None}

    night_lines = []
    night_subtotal = 0
    for day in range(arrival, departure):
        season_day = day % days_per_season_year
        if season_day < season_boundaries[0]:
            season = "LOW"
        elif season_day < season_boundaries[1]:
            season = "PEAK"
        else:
            season = "SHOULDER"
        base_cents = season_rates[season]
        weekday = day % days_per_week
        is_weekend = weekday in weekend_days
        weekend_cents = weekend_surcharge if is_weekend else 0
        night_cents = base_cents + weekend_cents
        night_subtotal += night_cents
        night_lines.append(
            {
                "day": day,
                "season": season,
                "base_cents": base_cents,
                "weekend_cents": weekend_cents,
                "night_cents": night_cents,
            }
        )
    cleaning_fee = 4500
    extra_guest_fee = (2000 * max(0, adults - 2) + 1000 * children) * night_count
    tourist_tax = 800 * guest_count * min(night_count, 5)
    extras_fee = sum(
        1200 * night_count if extra == "PARKING" else 2500 for extra in extras
    )
    charge_lines = (
        night_subtotal,
        cleaning_fee,
        extra_guest_fee,
        tourist_tax,
        extras_fee,
    )
    pre_discount = sum(charge_lines)
    if night_count >= 14:
        discount_rate = 15
    elif night_count >= 7:
        discount_rate = 10
    else:
        discount_rate = 0
    discount_numerator = night_subtotal * discount_rate
    discount_denominator = 100
    discount_whole, discount_remainder = divmod(
        discount_numerator, discount_denominator
    )
    long_stay_discount = discount_whole + int(
        discount_remainder * 2 >= discount_denominator
    )
    after_long_stay = pre_discount - long_stay_discount
    if promo == "PCT10":
        promo_percent = 10
        promo_numerator = after_long_stay * promo_percent
        promo_denominator = 100
        promo_whole, promo_remainder = divmod(promo_numerator, promo_denominator)
        promo_discount = promo_whole + int(promo_remainder * 2 >= promo_denominator)
    elif promo == "FIXED5000":
        fixed_discount_cents = 5000
        promo_discount = min(fixed_discount_cents, after_long_stay)
    elif promo == "ONENIGHT":
        nightly_prices = [line["night_cents"] for line in night_lines]
        promo_discount = min(nightly_prices)
    else:
        promo_discount = 0
    total = after_long_stay - promo_discount
    deposit_numerator = total * 30
    deposit_denominator = 100
    deposit_whole, deposit_remainder = divmod(deposit_numerator, deposit_denominator)
    percentage_deposit = deposit_whole + int(
        deposit_remainder * 2 >= deposit_denominator
    )
    minimum_deposit = 10000
    deposit_before_cap = max(minimum_deposit, percentage_deposit)
    deposit = min(total, deposit_before_cap)
    weekend_applies = any(line["weekend_cents"] > 0 for line in night_lines)
    cleaning_applies = cleaning_fee > 0
    extra_guests_apply = extra_guest_fee > 0
    tourist_tax_applies = tourist_tax > 0
    parking_applies = "PARKING" in extras
    pet_applies = "PET" in extras
    long_stay_applies = long_stay_discount > 0
    promo_applies = promo_discount > 0
    deposit_applies = total > 0
    adjustments = (
        (weekend_applies, "weekend"),
        (cleaning_applies, "cleaning"),
        (extra_guests_apply, "extra-guests"),
        (tourist_tax_applies, "tourist-tax"),
        (parking_applies, "parking"),
        (pet_applies, "pet"),
        (long_stay_applies, "long-stay"),
        (promo_applies, "promo"),
        (deposit_applies, "deposit"),
    )
    applied = []
    for enabled, name in adjustments:
        if enabled:
            applied.append(name)
    epoch_day = 0
    arrival_lead_days = arrival - epoch_day
    flexible_cancellation_lead = 30
    standard_cancellation_lead = 7
    if arrival_lead_days >= flexible_cancellation_lead:
        cancellation = "FLEX"
    elif arrival_lead_days >= standard_cancellation_lead:
        cancellation = "STANDARD"
    else:
        cancellation = "FIRM"
    balance_due = total - deposit
    quote = {
        "nights": night_count,
        "night_lines": night_lines,
        "cleaning_fee": cleaning_fee,
        "extra_guest_fee": extra_guest_fee,
        "tourist_tax": tourist_tax,
        "extras_fee": extras_fee,
        "long_stay_discount": long_stay_discount,
        "promo_discount": promo_discount,
        "total": total,
        "deposit": deposit,
        "balance_due": balance_due,
        "applied": applied,
        "cancellation": cancellation,
    }
    return quote
