def solution(request: dict) -> dict:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Quote a stay with seasonal rates, fees, discounts, and deposit."""
    property_id = request["property_id"].strip(" ").upper()
    arrival = request["arrival"]
    departure = request["departure"]
    adults = request["adults"]
    children = request["children"]
    extras = [value.strip(" ").upper() for value in request["extras"]]
    bookings = request["bookings"]
    promo = request["promo_code"].strip(" ").upper()
    property_is_supported = property_id in ("CEDAR", "LAKE")
    if not property_is_supported:
        return {"error": "BAD_PROPERTY", "index": None}
    adults_are_integer = type(adults) is int
    if not adults_are_integer:
        return {"error": "BAD_ADULTS", "index": None}
    adults_meet_lower_bound = adults >= 1
    if not adults_meet_lower_bound:
        return {"error": "BAD_ADULTS", "index": None}
    adults_meet_upper_bound = adults <= 8
    if not adults_meet_upper_bound:
        return {"error": "BAD_ADULTS", "index": None}
    children_are_integer = type(children) is int
    if not children_are_integer:
        return {"error": "BAD_CHILDREN", "index": None}
    children_meet_lower_bound = children >= 0
    if not children_meet_lower_bound:
        return {"error": "BAD_CHILDREN", "index": None}
    children_meet_upper_bound = children <= 8
    if not children_meet_upper_bound:
        return {"error": "BAD_CHILDREN", "index": None}
    arrival_is_integer = type(arrival) is int
    departure_is_integer = type(departure) is int
    arrival_is_in_range = arrival_is_integer and 0 <= arrival <= 1_000_000
    departure_is_in_range = departure_is_integer and 0 <= departure <= 1_000_000
    departure_follows_arrival = (
        arrival_is_integer and departure_is_integer and departure > arrival
    )
    if (
        not arrival_is_in_range
        or not departure_is_in_range
        or not departure_follows_arrival
    ):
        return {"error": "BAD_DAYS", "index": None}
    extras_count = len(extras)
    extras_count_is_valid = extras_count <= 4
    if not extras_count_is_valid:
        return {"error": "BAD_EXTRA", "index": None}
    seen_extras = set()
    for extra_index, extra in enumerate(extras):
        extra_is_supported = extra in ("PARKING", "PET")
        extra_is_duplicate = extra in seen_extras
        extra_is_valid = extra_is_supported and not extra_is_duplicate
        if not extra_is_valid:
            return {"error": "BAD_EXTRA", "index": extra_index}
        seen_extras.add(extra)
    booking_count = len(bookings)
    booking_count_is_valid = booking_count <= 100
    if not booking_count_is_valid:
        return {"error": "BAD_BOOKING", "index": None}
    normal_bookings = []
    for booking_index, booking in enumerate(bookings):
        booked_property = booking["property_id"].strip(" ").upper()
        booked_arrival = booking["arrival"]
        booked_departure = booking["departure"]
        if booked_property not in ("CEDAR", "LAKE"):
            return {"error": "BAD_BOOKING", "index": booking_index}
        booking_arrival_is_integer = type(booked_arrival) is int
        booking_departure_is_integer = type(booked_departure) is int
        booking_endpoints_are_integers = (
            booking_arrival_is_integer and booking_departure_is_integer
        )
        if not booking_endpoints_are_integers:
            return {"error": "BAD_BOOKING", "index": booking_index}
        booking_arrival_is_in_range = 0 <= booked_arrival <= 1_000_000
        booking_departure_is_in_range = 0 <= booked_departure <= 1_000_000
        if not booking_arrival_is_in_range or not booking_departure_is_in_range:
            return {"error": "BAD_BOOKING", "index": booking_index}
        if booked_departure <= booked_arrival:
            return {"error": "BAD_BOOKING", "index": booking_index}
        normal_bookings.append((booked_property, booked_arrival, booked_departure))
    night_count = departure - arrival
    stay_is_nonempty = night_count >= 1
    stay_is_within_limit = night_count <= 30
    stay_length_is_valid = stay_is_nonempty and stay_is_within_limit
    if not stay_length_is_valid:
        return {"error": "BAD_STAY", "index": None}
    cedar_capacity = 4
    lake_capacity = 6
    property_capacity = cedar_capacity if property_id == "CEDAR" else lake_capacity
    adult_guest_count = adults
    child_guest_count = children
    guest_count = adult_guest_count + child_guest_count
    guest_count_exceeds_capacity = guest_count > property_capacity
    capacity_is_sufficient = guest_count <= property_capacity
    if guest_count_exceeds_capacity or not capacity_is_sufficient:
        return {"error": "OVER_CAPACITY", "index": None}
    occupied_seasons = {"LOW": 0, "PEAK": 0, "SHOULDER": 0}
    for day in range(arrival, departure):
        season_position = day % 365
        season_is_low = season_position < 120
        season_is_peak = season_position >= 120 and season_position < 240
        season_is_shoulder = season_position >= 240
        if season_is_low:
            occupied_seasons["LOW"] += 1
        elif season_is_peak:
            occupied_seasons["PEAK"] += 1
        elif season_is_shoulder:
            occupied_seasons["SHOULDER"] += 1
    low_season_minimum = 1
    peak_season_minimum = 3
    shoulder_season_minimum = 2
    low_season_is_present = occupied_seasons["LOW"] > 0
    peak_season_is_present = occupied_seasons["PEAK"] > 0
    shoulder_season_is_present = occupied_seasons["SHOULDER"] > 0
    low_minimum_is_violated = low_season_is_present and night_count < low_season_minimum
    if low_minimum_is_violated:
        return {"error": "MIN_STAY", "index": None}
    peak_minimum_is_violated = (
        peak_season_is_present and night_count < peak_season_minimum
    )
    if peak_minimum_is_violated:
        return {"error": "MIN_STAY", "index": None}
    shoulder_minimum_is_violated = (
        shoulder_season_is_present and night_count < shoulder_season_minimum
    )
    if shoulder_minimum_is_violated:
        return {"error": "MIN_STAY", "index": None}
    for booking_index, (booked_property, booked_arrival, booked_departure) in enumerate(
        normal_bookings
    ):
        booking_is_for_requested_property = booked_property == property_id
        requested_stay_starts_before_booking_ends = arrival < booked_departure
        booking_starts_before_requested_stay_ends = booked_arrival < departure
        booking_overlaps_requested_stay = (
            requested_stay_starts_before_booking_ends
            and booking_starts_before_requested_stay_ends
        )
        if booking_is_for_requested_property and booking_overlaps_requested_stay:
            return {"error": "UNAVAILABLE", "index": booking_index}
    allowed_promos = ("", "PCT10", "FIXED5000", "ONENIGHT")
    promo_is_supported = promo in allowed_promos
    if not promo_is_supported:
        return {"error": "BAD_PROMO", "index": None}

    night_lines = []
    season_rates = {"LOW": 5000, "PEAK": 9000, "SHOULDER": 6500}
    has_weekend = False
    for day in range(arrival, departure):
        season_position = day % 365
        season_is_low = season_position < 120
        season_is_peak = season_position >= 120 and season_position < 240
        season_is_shoulder = season_position >= 240
        if season_is_low:
            season_name = "LOW"
        elif season_is_peak:
            season_name = "PEAK"
        elif season_is_shoulder:
            season_name = "SHOULDER"
        base_cents = season_rates[season_name]
        weekday = day % 7
        weekday_is_friday = weekday == 4
        weekday_is_saturday = weekday == 5
        has_weekend_surcharge = weekday_is_friday or weekday_is_saturday
        weekend_rate = 1500
        no_weekend_rate = 0
        weekend_cents = weekend_rate if has_weekend_surcharge else no_weekend_rate
        has_weekend = has_weekend or weekend_cents > 0
        night_cents = base_cents + weekend_cents
        night_line = {
            "day": day,
            "season": season_name,
            "base_cents": base_cents,
            "weekend_cents": weekend_cents,
            "night_cents": night_cents,
        }
        night_lines.append(night_line)
    night_subtotal = sum(line["night_cents"] for line in night_lines)
    cleaning_fee = 4500
    included_adult_count = 2
    extra_adult_rate = 2000
    child_rate = 1000
    extra_guest_fee = 0
    for adult_index in range(adults):
        adult_is_beyond_included_count = adult_index >= included_adult_count
        if adult_is_beyond_included_count:
            adult_stay_fee = extra_adult_rate * night_count
            extra_guest_fee += adult_stay_fee
    for _child_index in range(children):
        child_stay_fee = child_rate * night_count
        extra_guest_fee += child_stay_fee
    tourist_tax_rate = 800
    maximum_taxable_nights = 5
    taxable_nights = min(night_count, maximum_taxable_nights)
    tourist_tax = 0
    for _adult_index in range(adults):
        adult_tax_for_stay = tourist_tax_rate * taxable_nights
        tourist_tax += adult_tax_for_stay
    for _child_index in range(children):
        child_tax_for_stay = tourist_tax_rate * taxable_nights
        tourist_tax += child_tax_for_stay
    parking_fee = 0
    pet_fee = 0
    for extra in extras:
        if extra == "PARKING":
            parking_rate_per_night = 1200
            parking_fee_for_stay = parking_rate_per_night * night_count
            parking_fee += parking_fee_for_stay
        elif extra == "PET":
            pet_fee_per_stay = 2500
            pet_fee += pet_fee_per_stay
    extras_fee = parking_fee + pet_fee
    pre_discount_parts = (
        night_subtotal,
        cleaning_fee,
        extra_guest_fee,
        tourist_tax,
        extras_fee,
    )
    pre_discount_total = sum(pre_discount_parts)
    if night_count >= 14:
        long_stay_rate = 15
    elif night_count >= 7:
        long_stay_rate = 10
    else:
        long_stay_rate = 0
    discount_numerator = night_subtotal * long_stay_rate
    discount_denominator = 100
    doubled_discount_numerator = 2 * discount_numerator
    rounded_discount_numerator = doubled_discount_numerator + discount_denominator
    doubled_discount_denominator = 2 * discount_denominator
    long_stay_discount = rounded_discount_numerator // doubled_discount_denominator
    after_long_discount = pre_discount_total - long_stay_discount
    if promo == "PCT10":
        promo_rate = 10
        promo_basis = after_long_discount
        promo_numerator = promo_basis * promo_rate
        promo_denominator = 100
        promo_whole_cents = promo_numerator // promo_denominator
        promo_remainder = promo_numerator % promo_denominator
        promo_rounds_up = 2 * promo_remainder >= promo_denominator
        promo_rounding_cent = int(promo_rounds_up)
        promo_discount = promo_whole_cents + promo_rounding_cent
    elif promo == "FIXED5000":
        requested_fixed_discount = 5000
        remaining_amount = after_long_discount
        promo_discount = min(requested_fixed_discount, remaining_amount)
    elif promo == "ONENIGHT":
        nightly_amounts = [line["night_cents"] for line in night_lines]
        promo_discount = min(nightly_amounts)
    else:
        promo_discount = 0
    total = after_long_discount - promo_discount
    deposit_rate = 30
    deposit_numerator = total * deposit_rate
    deposit_denominator = 100
    doubled_deposit_numerator = 2 * deposit_numerator
    rounded_deposit_numerator = doubled_deposit_numerator + deposit_denominator
    deposit_percentage = rounded_deposit_numerator // (2 * deposit_denominator)
    minimum_deposit = 10000
    percentage_deposit_is_below_minimum = deposit_percentage < minimum_deposit
    deposit_is_raised_to_minimum = percentage_deposit_is_below_minimum
    if deposit_is_raised_to_minimum:
        uncapped_deposit = minimum_deposit
    else:
        uncapped_deposit = deposit_percentage
    deposit_is_capped = uncapped_deposit >= total
    deposit = total if deposit_is_capped else uncapped_deposit
    balance_due = total - deposit
    applied = []
    weekend_effect_applies = has_weekend
    cleaning_effect_applies = cleaning_fee > 0
    tax_effect_applies = tourist_tax > 0
    parking_effect_applies = "PARKING" in extras
    pet_effect_applies = "PET" in extras
    extra_guest_effect_applies = extra_guest_fee > 0
    long_stay_effect_applies = long_stay_discount > 0
    promo_effect_applies = promo_discount > 0
    deposit_effect_applies = total > 0
    effects = (
        (weekend_effect_applies, "weekend"),
        (cleaning_effect_applies, "cleaning"),
        (extra_guest_effect_applies, "extra-guests"),
        (tax_effect_applies, "tourist-tax"),
        (parking_effect_applies, "parking"),
        (pet_effect_applies, "pet"),
        (long_stay_effect_applies, "long-stay"),
        (promo_effect_applies, "promo"),
        (deposit_effect_applies, "deposit"),
    )
    for effect_applies, effect_name in effects:
        if effect_applies:
            applied.append(effect_name)
    epoch_day = 0
    arrival_lead_days = arrival - epoch_day
    flexible_lead_limit = 30
    standard_lead_limit = 7
    has_flexible_lead_time = arrival_lead_days >= flexible_lead_limit
    has_standard_lead_time = arrival_lead_days >= standard_lead_limit
    if has_flexible_lead_time:
        cancellation = "FLEX"
    elif has_standard_lead_time:
        cancellation = "STANDARD"
    else:
        cancellation = "FIRM"
    quote = {}
    quote["nights"] = night_count
    quote["night_lines"] = night_lines
    quote["cleaning_fee"] = cleaning_fee
    quote["extra_guest_fee"] = extra_guest_fee
    quote["tourist_tax"] = tourist_tax
    quote["extras_fee"] = extras_fee
    quote["long_stay_discount"] = long_stay_discount
    quote["promo_discount"] = promo_discount
    quote["total"] = total
    quote["deposit"] = deposit
    quote["balance_due"] = balance_due
    quote["applied"] = applied
    quote["cancellation"] = cancellation
    return quote
