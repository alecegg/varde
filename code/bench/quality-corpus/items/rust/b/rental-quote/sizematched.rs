#[derive(Debug, Clone, PartialEq)]
pub struct Request {
    pub property_id: String,
    pub arrival: i64,
    pub departure: i64,
    pub adults: i64,
    pub children: i64,
    pub extras: Vec<String>,
    pub bookings: Vec<Booking>,
    pub promo_code: String,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Booking {
    pub property_id: String,
    pub arrival: i64,
    pub departure: i64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct NightLine {
    pub day: i64,
    pub season: String,
    pub base_cents: i64,
    pub weekend_cents: i64,
    pub night_cents: i64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Quote {
    pub nights: i64,
    pub night_lines: Vec<NightLine>,
    pub cleaning_fee: i64,
    pub extra_guest_fee: i64,
    pub tourist_tax: i64,
    pub extras_fee: i64,
    pub long_stay_discount: i64,
    pub promo_discount: i64,
    pub total: i64,
    pub deposit: i64,
    pub balance_due: i64,
    pub applied: Vec<String>,
    pub cancellation: String,
}
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Quote(Quote),
    Error { code: String, index: Option<usize> },
}

/// Quote a stay with seasonal rates, fees, discounts, and deposit.
pub fn solution(request: &Request) -> Outcome {
    let property = request.property_id.trim_matches(' ').to_ascii_uppercase();
    let extras: Vec<String> = request
        .extras
        .iter()
        .map(|value| value.trim_matches(' ').to_ascii_uppercase())
        .collect();
    let bookings: Vec<Booking> = request
        .bookings
        .iter()
        .map(|booking| Booking {
            property_id: booking.property_id.trim_matches(' ').to_ascii_uppercase(),
            arrival: booking.arrival,
            departure: booking.departure,
        })
        .collect();
    let promo = request.promo_code.trim_matches(' ').to_ascii_uppercase();
    let property_is_cedar = property == "CEDAR";
    let property_is_lake = property == "LAKE";
    let known_property = property_is_cedar || property_is_lake;
    if !known_property {
        return Outcome::Error {
            code: "BAD_PROPERTY".into(),
            index: None,
        };
    }
    let minimum_adults = 1;
    let maximum_adults = 8;
    let adult_range = minimum_adults..=maximum_adults;
    let adult_count_valid = adult_range.contains(&request.adults);
    if !adult_count_valid {
        return Outcome::Error {
            code: "BAD_ADULTS".into(),
            index: None,
        };
    }
    let minimum_children = 0;
    let maximum_children = 8;
    let child_range = minimum_children..=maximum_children;
    let child_count_valid = child_range.contains(&request.children);
    if !child_count_valid {
        return Outcome::Error {
            code: "BAD_CHILDREN".into(),
            index: None,
        };
    }
    let arrival_in_range = (0..=1_000_000).contains(&request.arrival);
    let departure_in_range = (0..=1_000_000).contains(&request.departure);
    let departure_follows_arrival = request.departure > request.arrival;
    let day_range_valid = arrival_in_range && departure_in_range && departure_follows_arrival;
    if !day_range_valid {
        return Outcome::Error {
            code: "BAD_DAYS".into(),
            index: None,
        };
    }
    let extra_count = extras.len();
    let maximum_extra_count = 4;
    let extras_fit_request = extra_count <= maximum_extra_count;
    if !extras_fit_request {
        return Outcome::Error {
            code: "BAD_EXTRA".into(),
            index: None,
        };
    }
    for (index, extra) in extras.iter().enumerate() {
        let recognized_extra = extra == "PARKING" || extra == "PET";
        let already_seen = extras[..index].contains(extra);
        if !recognized_extra || already_seen {
            return Outcome::Error {
                code: "BAD_EXTRA".into(),
                index: Some(index),
            };
        }
    }
    let booking_count = bookings.len();
    let maximum_booking_count = 100;
    let bookings_fit_request = booking_count <= maximum_booking_count;
    if !bookings_fit_request {
        return Outcome::Error {
            code: "BAD_BOOKING".into(),
            index: None,
        };
    }
    for (index, booking) in bookings.iter().enumerate() {
        let booking_property_known =
            booking.property_id == "CEDAR" || booking.property_id == "LAKE";
        let booking_arrival_valid = (0..=1_000_000).contains(&booking.arrival);
        let booking_departure_valid = (0..=1_000_000).contains(&booking.departure);
        let booking_duration_valid = booking.departure > booking.arrival;
        if !booking_property_known
            || !booking_arrival_valid
            || !booking_departure_valid
            || !booking_duration_valid
        {
            return Outcome::Error {
                code: "BAD_BOOKING".into(),
                index: Some(index),
            };
        }
    }
    let nights = request.departure - request.arrival;
    let minimum_stay_length = 1;
    let maximum_stay_length = 30;
    let stay_length = minimum_stay_length..=maximum_stay_length;
    if !stay_length.contains(&nights) {
        return Outcome::Error {
            code: "BAD_STAY".into(),
            index: None,
        };
    }
    let guest_count = request.adults + request.children;
    let guest_capacity = if property_is_cedar { 4 } else { 6 };
    let within_capacity = guest_count <= guest_capacity;
    if !within_capacity {
        return Outcome::Error {
            code: "OVER_CAPACITY".into(),
            index: None,
        };
    }
    let mut seasons = [0; 3];
    for day in request.arrival..request.departure {
        let season_day = day.rem_euclid(365);
        let season_index = if season_day < 120 {
            0
        } else if season_day < 240 {
            1
        } else {
            2
        };
        seasons[season_index] += 1;
    }
    let minimums = [1, 3, 2];
    for season_index in 0..seasons.len() {
        let season_is_occupied = seasons[season_index] > 0;
        let required_nights = minimums[season_index];
        let stay_is_too_short = nights < required_nights;
        if season_is_occupied && stay_is_too_short {
            return Outcome::Error {
                code: "MIN_STAY".into(),
                index: None,
            };
        }
    }
    for (index, booking) in bookings.iter().enumerate() {
        let same_property = booking.property_id == property;
        let request_starts_before_booking_ends = request.arrival < booking.departure;
        let booking_starts_before_request_ends = booking.arrival < request.departure;
        let overlaps = request_starts_before_booking_ends && booking_starts_before_request_ends;
        if same_property && overlaps {
            return Outcome::Error {
                code: "UNAVAILABLE".into(),
                index: Some(index),
            };
        }
    }
    let percentage_promo = promo == "PCT10";
    let fixed_promo = promo == "FIXED5000";
    let one_night_promo = promo == "ONENIGHT";
    let no_promo = promo.is_empty();
    let valid_promo = percentage_promo || fixed_promo || one_night_promo || no_promo;
    if !valid_promo {
        return Outcome::Error {
            code: "BAD_PROMO".into(),
            index: None,
        };
    }
    let low_nightly_rate = 5000;
    let peak_nightly_rate = 9000;
    let shoulder_nightly_rate = 6500;
    let weekend_surcharge = 1500;
    let mut night_lines = Vec::with_capacity(nights as usize);
    let mut low_subtotal = 0;
    let mut peak_subtotal = 0;
    let mut shoulder_subtotal = 0;
    let mut weekend_subtotal = 0;
    let mut cheapest = i64::MAX;
    let mut weekend_count = 0;
    for day in request.arrival..request.departure {
        let season_day = day.rem_euclid(365);
        let low_season = season_day < 120;
        let peak_season = season_day >= 120 && season_day < 240;
        let (season, base_cents) = if low_season {
            ("LOW", 5000)
        } else if peak_season {
            ("PEAK", 9000)
        } else {
            ("SHOULDER", 6500)
        };
        let weekday = day.rem_euclid(7);
        let is_weekend_night = weekday == 4 || weekday == 5;
        let weekend_cents = if is_weekend_night {
            weekend_surcharge
        } else {
            0
        };
        let night_cents = base_cents + weekend_cents;
        match season {
            "LOW" => low_subtotal += base_cents,
            "PEAK" => peak_subtotal += base_cents,
            _ => shoulder_subtotal += base_cents,
        }
        weekend_subtotal += weekend_cents;
        if is_weekend_night {
            weekend_count += 1;
        }
        cheapest = cheapest.min(night_cents);
        night_lines.push(NightLine {
            day,
            season: season.into(),
            base_cents,
            weekend_cents,
            night_cents,
        });
    }
    let base_subtotal = low_subtotal + peak_subtotal + shoulder_subtotal;
    let subtotal = base_subtotal + weekend_subtotal;
    let cleaning_fee = 4500;
    let additional_adults = (request.adults - 2).max(0);
    let adult_guest_rate = 2000 * additional_adults;
    let child_guest_rate = 1000 * request.children;
    let guest_fee_per_night = adult_guest_rate + child_guest_rate;
    let extra_guest_fee = guest_fee_per_night * nights;
    let taxable_guest_count = request.adults + request.children;
    let taxable_nights = nights.min(5);
    let tax_rate_per_guest_night = 800;
    let tourist_tax_per_guest = tax_rate_per_guest_night * taxable_nights;
    let tourist_tax = tourist_tax_per_guest * taxable_guest_count;
    let parking_rate_per_night = 1200;
    let pet_rate_per_stay = 2500;
    let mut parking_fee = 0;
    let mut pet_fee = 0;
    for extra in &extras {
        match extra.as_str() {
            "PARKING" => {
                let parking_charge = parking_rate_per_night * nights;
                parking_fee += parking_charge;
            }
            "PET" => {
                pet_fee += pet_rate_per_stay;
            }
            _ => {}
        }
    }
    let extras_fee = parking_fee + pet_fee;
    let lodging_subtotal = subtotal + cleaning_fee;
    let guest_subtotal = lodging_subtotal + extra_guest_fee;
    let taxed_subtotal = guest_subtotal + tourist_tax;
    let before_discount = taxed_subtotal + extras_fee;
    let rate = match nights {
        14..=30 => 15,
        7..=13 => 10,
        _ => 0,
    };
    let long_discount_basis = subtotal * rate;
    let long_discount_numerator = 2 * long_discount_basis;
    let long_discount_rounding_bias = 100;
    let long_discount_denominator = 200;
    let long_stay_discount =
        (long_discount_numerator + long_discount_rounding_bias) / long_discount_denominator;
    let after_long = before_discount - long_stay_discount;
    let promo_discount = match promo.as_str() {
        "PCT10" => {
            let percentage_basis = after_long * 10;
            let percentage_numerator = 2 * percentage_basis;
            let rounding_bias = 100;
            let percentage_denominator = 200;
            (percentage_numerator + rounding_bias) / percentage_denominator
        }
        "FIXED5000" => {
            let fixed_discount = 5000;
            fixed_discount.min(after_long)
        }
        "ONENIGHT" => cheapest,
        _ => 0,
    };
    let total = after_long - promo_discount;
    let deposit_percentage_basis = total * 30;
    let deposit_numerator = 2 * deposit_percentage_basis;
    let deposit_rounding_bias = 100;
    let deposit_denominator = 200;
    let percentage_deposit = (deposit_numerator + deposit_rounding_bias) / deposit_denominator;
    let minimum_deposit = 10_000;
    let deposit_floor = minimum_deposit.max(percentage_deposit);
    let deposit = total.min(deposit_floor);
    let has_weekend = weekend_count > 0;
    let has_cleaning = cleaning_fee > 0;
    let has_extra_guests = extra_guest_fee > 0;
    let has_tourist_tax = tourist_tax > 0;
    let has_parking = parking_fee > 0;
    let has_pet = pet_fee > 0;
    let has_long_stay_discount = long_stay_discount > 0;
    let has_promo_discount = promo_discount > 0;
    let has_deposit = total > 0;
    let effect_flags = [
        has_weekend,
        has_cleaning,
        has_extra_guests,
        has_tourist_tax,
        has_parking,
        has_pet,
        has_long_stay_discount,
        has_promo_discount,
        has_deposit,
    ];
    let effect_names = [
        "weekend",
        "cleaning",
        "extra-guests",
        "tourist-tax",
        "parking",
        "pet",
        "long-stay",
        "promo",
        "deposit",
    ];
    let mut applied = Vec::new();
    for (is_applied, name) in effect_flags.into_iter().zip(effect_names) {
        if is_applied {
            applied.push(name.into());
        }
    }
    let lead_days = request.arrival;
    let flexible_notice = lead_days >= 30;
    let standard_notice = lead_days >= 7 && lead_days < 30;
    let cancellation = if flexible_notice {
        "FLEX"
    } else if standard_notice {
        "STANDARD"
    } else {
        "FIRM"
    };
    let balance_due = total - deposit;
    Outcome::Quote(Quote {
        nights: night_lines.len() as i64,
        night_lines,
        cleaning_fee,
        extra_guest_fee,
        tourist_tax,
        extras_fee,
        long_stay_discount,
        promo_discount,
        total,
        deposit,
        balance_due,
        applied,
        cancellation: cancellation.into(),
    })
}
