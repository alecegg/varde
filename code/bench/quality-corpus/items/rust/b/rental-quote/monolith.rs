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
    let promo = request.promo_code.trim_matches(' ').to_ascii_uppercase();
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
    let is_cedar = property == "CEDAR";
    let is_lake = property == "LAKE";
    let is_supported_property = is_cedar || is_lake;
    if !is_supported_property {
        return Outcome::Error {
            code: "BAD_PROPERTY".into(),
            index: None,
        };
    }
    let adults_in_domain = (1..=8).contains(&request.adults);
    if !adults_in_domain {
        return Outcome::Error {
            code: "BAD_ADULTS".into(),
            index: None,
        };
    }
    let children_in_domain = (0..=8).contains(&request.children);
    if !children_in_domain {
        return Outcome::Error {
            code: "BAD_CHILDREN".into(),
            index: None,
        };
    }
    let arrival_is_bounded = (0..=1_000_000).contains(&request.arrival);
    let departure_is_bounded = (0..=1_000_000).contains(&request.departure);
    let date_order_is_valid = request.departure > request.arrival;
    if !arrival_is_bounded || !departure_is_bounded || !date_order_is_valid {
        return Outcome::Error {
            code: "BAD_DAYS".into(),
            index: None,
        };
    }
    if extras.len() > 4 {
        return Outcome::Error {
            code: "BAD_EXTRA".into(),
            index: None,
        };
    }
    let mut seen: Vec<&String> = Vec::new();
    for (index, extra) in extras.iter().enumerate() {
        let is_known_extra = extra == "PARKING" || extra == "PET";
        let is_duplicate_extra = seen.iter().any(|seen_extra| *seen_extra == extra);
        if !is_known_extra || is_duplicate_extra {
            return Outcome::Error {
                code: "BAD_EXTRA".into(),
                index: Some(index),
            };
        }
        seen.push(extra);
    }
    if bookings.len() > 100 {
        return Outcome::Error {
            code: "BAD_BOOKING".into(),
            index: None,
        };
    }
    for (index, booking) in bookings.iter().enumerate() {
        if (booking.property_id != "CEDAR" && booking.property_id != "LAKE")
            || !(0..=1_000_000).contains(&booking.arrival)
            || !(0..=1_000_000).contains(&booking.departure)
            || booking.departure <= booking.arrival
        {
            return Outcome::Error {
                code: "BAD_BOOKING".into(),
                index: Some(index),
            };
        }
    }
    let nights = request.departure - request.arrival;
    if !(1..=30).contains(&nights) {
        return Outcome::Error {
            code: "BAD_STAY".into(),
            index: None,
        };
    }
    let guest_count = request.adults + request.children;
    let capacity = if is_cedar { 4 } else { 6 };
    let guest_count_exceeds_capacity = guest_count > capacity;
    if guest_count_exceeds_capacity {
        return Outcome::Error {
            code: "OVER_CAPACITY".into(),
            index: None,
        };
    }
    let mut occupied = [false; 3];
    let mut day = request.arrival;
    while day < request.departure {
        let season_index = match day.rem_euclid(365) {
            0..=119 => 0,
            120..=239 => 1,
            _ => 2,
        };
        occupied[season_index] = true;
        day += 1;
    }
    if (occupied[0] && nights < 1) || (occupied[1] && nights < 3) || (occupied[2] && nights < 2) {
        return Outcome::Error {
            code: "MIN_STAY".into(),
            index: None,
        };
    }
    for (index, booking) in bookings.iter().enumerate() {
        let same_property = booking.property_id == property;
        let overlaps_by_start = request.arrival < booking.departure;
        let overlaps_by_end = booking.arrival < request.departure;
        if same_property && overlaps_by_start && overlaps_by_end {
            return Outcome::Error {
                code: "UNAVAILABLE".into(),
                index: Some(index),
            };
        }
    }
    if promo != "" && promo != "PCT10" && promo != "FIXED5000" && promo != "ONENIGHT" {
        return Outcome::Error {
            code: "BAD_PROMO".into(),
            index: None,
        };
    }
    let mut night_lines = Vec::new();
    let mut base_subtotal = 0;
    let mut weekend_subtotal = 0;
    let mut cheapest_night = i64::MAX;
    let mut has_weekend = false;
    for day in request.arrival..request.departure {
        let (season_name, base_cents) = match day.rem_euclid(365) {
            0..=119 => ("LOW", 5000),
            120..=239 => ("PEAK", 9000),
            _ => ("SHOULDER", 6500),
        };
        let weekday = day.rem_euclid(7);
        let is_weekend_night = weekday == 4 || weekday == 5;
        let weekend_rate = 1500;
        let weekend_cents = if is_weekend_night { weekend_rate } else { 0 };
        let night_cents = base_cents + weekend_cents;
        has_weekend |= is_weekend_night;
        base_subtotal += base_cents;
        weekend_subtotal += weekend_cents;
        cheapest_night = cheapest_night.min(night_cents);
        night_lines.push(NightLine {
            day,
            season: season_name.into(),
            base_cents,
            weekend_cents,
            night_cents,
        });
    }
    let night_subtotal = base_subtotal + weekend_subtotal;
    let cleaning_fee = 4500;
    let billable_adults = (request.adults - 2).max(0);
    let adult_guest_rate = 2000 * billable_adults;
    let child_guest_rate = 1000 * request.children;
    let guest_rate_per_night = adult_guest_rate + child_guest_rate;
    let extra_guest_fee = guest_rate_per_night * nights;
    let tourist_tax_guest_count = request.adults + request.children;
    let tourist_tax_nights = nights.min(5);
    let tourist_tax_per_guest = 800 * tourist_tax_nights;
    let tourist_tax = tourist_tax_per_guest * tourist_tax_guest_count;
    let mut extras_fee = 0;
    let mut has_parking = false;
    let mut has_pet = false;
    for extra in &extras {
        if extra == "PARKING" {
            extras_fee += 1200 * nights;
            has_parking = true;
        } else {
            extras_fee += 2500;
            has_pet = true;
        }
    }
    let accommodation_total = night_subtotal + cleaning_fee;
    let guest_total = accommodation_total + extra_guest_fee;
    let taxed_total = guest_total + tourist_tax;
    let pre_discount = taxed_total + extras_fee;
    let discount_rate = if nights >= 14 {
        15
    } else if nights >= 7 {
        10
    } else {
        0
    };
    let discount_basis = night_subtotal * discount_rate;
    let discount_numerator = 2 * discount_basis;
    let discount_rounding_bias = 100;
    let discount_denominator = 200;
    let long_stay_discount = (discount_numerator + discount_rounding_bias) / discount_denominator;
    let after_long_stay = pre_discount - long_stay_discount;
    let promo_discount = match promo.as_str() {
        "PCT10" => {
            let percentage_basis = after_long_stay * 10;
            let percentage_numerator = 2 * percentage_basis;
            let percentage_rounding_bias = 100;
            let percentage_denominator = 200;
            (percentage_numerator + percentage_rounding_bias) / percentage_denominator
        }
        "FIXED5000" => 5000.min(after_long_stay),
        "ONENIGHT" => cheapest_night,
        _ => 0,
    };
    let total = after_long_stay - promo_discount;
    let deposit_percentage_basis = total * 30;
    let deposit_numerator = 2 * deposit_percentage_basis;
    let deposit_rounding_bias = 100;
    let deposit_denominator = 200;
    let percentage_deposit = (deposit_numerator + deposit_rounding_bias) / deposit_denominator;
    let minimum_deposit = 10_000;
    let deposit = total.min(minimum_deposit.max(percentage_deposit));
    let cancellation = if request.arrival >= 30 {
        "FLEX"
    } else if request.arrival >= 7 {
        "STANDARD"
    } else {
        "FIRM"
    };
    let mut applied = Vec::new();
    if has_weekend {
        applied.push("weekend".into());
    }
    applied.push("cleaning".into());
    if extra_guest_fee > 0 {
        applied.push("extra-guests".into());
    }
    if tourist_tax > 0 {
        applied.push("tourist-tax".into());
    }
    if has_parking {
        applied.push("parking".into());
    }
    if has_pet {
        applied.push("pet".into());
    }
    if long_stay_discount > 0 {
        applied.push("long-stay".into());
    }
    if promo_discount > 0 {
        applied.push("promo".into());
    }
    if total > 0 {
        applied.push("deposit".into());
    }
    Outcome::Quote(Quote {
        nights,
        night_lines,
        cleaning_fee,
        extra_guest_fee,
        tourist_tax,
        extras_fee,
        long_stay_discount,
        promo_discount,
        total,
        deposit,
        balance_due: total - deposit,
        applied,
        cancellation: cancellation.into(),
    })
}
