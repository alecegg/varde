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

#[derive(Clone)]
struct Data {
    property: String,
    arrival: i64,
    departure: i64,
    adults: i64,
    children: i64,
    extras: Vec<String>,
    bookings: Vec<Booking>,
    promo: String,
}
struct Pricing {
    fees: FeeParts,
    long: i64,
    promo: i64,
    total: i64,
    deposit: i64,
}
struct FeeParts {
    subtotal: i64,
    cleaning: i64,
    guests: i64,
    tax: i64,
    extras: i64,
}
struct Discounts {
    long: i64,
    promo: i64,
    total: i64,
    deposit: i64,
}

fn normalize_extras(values: &[String]) -> Vec<String> {
    let mut normalized = Vec::with_capacity(values.len());
    for value in values {
        normalized.push(value.trim_matches(' ').to_ascii_uppercase());
    }
    normalized
}
fn normalize_request(request: &Request) -> Data {
    let property = request.property_id.trim_matches(' ').to_ascii_uppercase();
    let extras = normalize_extras(&request.extras);
    let mut bookings = Vec::with_capacity(request.bookings.len());
    for booking in &request.bookings {
        let property_id = booking.property_id.trim_matches(' ').to_ascii_uppercase();
        bookings.push(Booking {
            property_id,
            arrival: booking.arrival,
            departure: booking.departure,
        });
    }
    let promo = request.promo_code.trim_matches(' ').to_ascii_uppercase();
    Data {
        property,
        arrival: request.arrival,
        departure: request.departure,
        adults: request.adults,
        children: request.children,
        extras,
        bookings,
        promo,
    }
}
fn check_property_and_guests(data: &Data) -> Option<Outcome> {
    if data.property != "CEDAR" && data.property != "LAKE" {
        return Some(Outcome::Error {
            code: "BAD_PROPERTY".into(),
            index: None,
        });
    }
    if !(1..=8).contains(&data.adults) {
        return Some(Outcome::Error {
            code: "BAD_ADULTS".into(),
            index: None,
        });
    }
    if !(0..=8).contains(&data.children) {
        return Some(Outcome::Error {
            code: "BAD_CHILDREN".into(),
            index: None,
        });
    }
    None
}
fn check_day_bounds(data: &Data) -> Option<Outcome> {
    let arrival_in_range = (0..=1_000_000).contains(&data.arrival);
    let departure_in_range = (0..=1_000_000).contains(&data.departure);
    if !arrival_in_range || !departure_in_range || data.departure <= data.arrival {
        return Some(Outcome::Error {
            code: "BAD_DAYS".into(),
            index: None,
        });
    }
    None
}
fn check_extra_list(data: &Data) -> Option<Outcome> {
    if data.extras.len() > 4 {
        return Some(Outcome::Error {
            code: "BAD_EXTRA".into(),
            index: None,
        });
    }
    for (index, extra) in data.extras.iter().enumerate() {
        if !["PARKING", "PET"].contains(&extra.as_str()) || data.extras[..index].contains(extra) {
            return Some(Outcome::Error {
                code: "BAD_EXTRA".into(),
                index: Some(index),
            });
        }
    }
    None
}
fn check_booking_list(data: &Data) -> Option<Outcome> {
    for (index, booking) in data.bookings.iter().enumerate() {
        if !["CEDAR", "LAKE"].contains(&booking.property_id.as_str())
            || !(0..=1_000_000).contains(&booking.arrival)
            || !(0..=1_000_000).contains(&booking.departure)
            || booking.departure <= booking.arrival
        {
            return Some(Outcome::Error {
                code: "BAD_BOOKING".into(),
                index: Some(index),
            });
        }
    }
    None
}
fn check_stay_and_capacity(data: &Data) -> Option<Outcome> {
    let nights = data.departure - data.arrival;
    if !(1..=30).contains(&nights) {
        return Some(Outcome::Error {
            code: "BAD_STAY".into(),
            index: None,
        });
    }
    let capacity = if data.property == "CEDAR" { 4 } else { 6 };
    if data.adults + data.children > capacity {
        return Some(Outcome::Error {
            code: "OVER_CAPACITY".into(),
            index: None,
        });
    }
    None
}
fn check_minimums(data: &Data) -> Option<Outcome> {
    let nights = data.departure - data.arrival;
    let mut occupied = [false; 3];
    for day in data.arrival..data.departure {
        let season = match day.rem_euclid(365) {
            0..=119 => 0,
            120..=239 => 1,
            _ => 2,
        };
        occupied[season] = true;
    }
    if (occupied[0] && nights < 1) || (occupied[1] && nights < 3) || (occupied[2] && nights < 2) {
        return Some(Outcome::Error {
            code: "MIN_STAY".into(),
            index: None,
        });
    }
    None
}
fn check_availability(data: &Data) -> Option<Outcome> {
    for (index, booking) in data.bookings.iter().enumerate() {
        let same_property = booking.property_id == data.property;
        let overlaps = data.arrival < booking.departure && booking.arrival < data.departure;
        if same_property && overlaps {
            return Some(Outcome::Error {
                code: "UNAVAILABLE".into(),
                index: Some(index),
            });
        }
    }
    None
}
fn check_promo(data: &Data) -> Option<Outcome> {
    let supported = data.promo.is_empty()
        || data.promo == "PCT10"
        || data.promo == "FIXED5000"
        || data.promo == "ONENIGHT";
    if !supported {
        return Some(Outcome::Error {
            code: "BAD_PROMO".into(),
            index: None,
        });
    }
    None
}
fn validate_request(data: &Data) -> Option<Outcome> {
    check_property_and_guests(data)
        .or_else(|| check_day_bounds(data))
        .or_else(|| check_extra_list(data))
        .or_else(|| {
            (data.bookings.len() > 100).then(|| Outcome::Error {
                code: "BAD_BOOKING".into(),
                index: None,
            })
        })
        .or_else(|| check_booking_list(data))
        .or_else(|| check_stay_and_capacity(data))
        .or_else(|| check_minimums(data))
        .or_else(|| check_availability(data))
        .or_else(|| check_promo(data))
}
fn build_lines(data: &Data) -> Vec<NightLine> {
    let mut lines = Vec::new();
    for day in data.arrival..data.departure {
        let (season, base_cents) = match day.rem_euclid(365) {
            0..=119 => ("LOW", 5000),
            120..=239 => ("PEAK", 9000),
            _ => ("SHOULDER", 6500),
        };
        let weekend_cents = if matches!(day.rem_euclid(7), 4 | 5) {
            1500
        } else {
            0
        };
        let night_cents = base_cents + weekend_cents;
        lines.push(NightLine {
            day,
            season: season.to_string(),
            base_cents,
            weekend_cents,
            night_cents,
        });
    }
    lines
}
fn round_half_up(numerator: i64, denominator: i64) -> i64 {
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let rounds_up = remainder * 2 >= denominator;
    if rounds_up {
        quotient + 1
    } else {
        quotient
    }
}
fn fee_parts(data: &Data, lines: &[NightLine]) -> FeeParts {
    let nights = data.departure - data.arrival;
    let subtotal = lines.iter().map(|line| line.night_cents).sum();
    let guests = (2000 * (data.adults - 2).max(0) + 1000 * data.children) * nights;
    let tax = 800 * (data.adults + data.children) * nights.min(5);
    let mut extras = 0;
    for extra in &data.extras {
        extras += if extra == "PARKING" {
            1200 * nights
        } else {
            2500
        };
    }
    FeeParts {
        subtotal,
        cleaning: 4500,
        guests,
        tax,
        extras,
    }
}
fn discounts_and_deposit(data: &Data, lines: &[NightLine], parts: &FeeParts) -> Discounts {
    let pre_discount = parts.subtotal + parts.cleaning + parts.guests + parts.tax + parts.extras;
    let rate = match data.departure - data.arrival {
        14.. => 15,
        7.. => 10,
        _ => 0,
    };
    let long = round_half_up(parts.subtotal * rate, 100);
    let promo = promo_discount_for(data, lines, pre_discount - long);
    let total = pre_discount - long - promo;
    let deposit = total.min(10_000.max(round_half_up(total * 30, 100)));
    Discounts {
        long,
        promo,
        total,
        deposit,
    }
}
fn promo_discount_for(data: &Data, lines: &[NightLine], remaining: i64) -> i64 {
    if data.promo == "PCT10" {
        return round_half_up(remaining * 10, 100);
    }
    if data.promo == "FIXED5000" {
        return 5000.min(remaining);
    }
    if data.promo == "ONENIGHT" {
        return lines.iter().map(|line| line.night_cents).min().unwrap_or(0);
    }
    0
}
fn price_quote(data: &Data, lines: &[NightLine]) -> Pricing {
    let parts = fee_parts(data, lines);
    let discounts = discounts_and_deposit(data, lines, &parts);
    Pricing {
        fees: parts,
        long: discounts.long,
        promo: discounts.promo,
        total: discounts.total,
        deposit: discounts.deposit,
    }
}
fn collect_stay_effects(lines: &[NightLine], price: &Pricing, applied: &mut Vec<String>) {
    if lines.iter().any(|line| line.weekend_cents > 0) {
        applied.push("weekend".into());
    }
    if price.fees.cleaning > 0 {
        applied.push("cleaning".into());
    }
    if price.fees.guests > 0 {
        applied.push("extra-guests".into());
    }
    if price.fees.tax > 0 {
        applied.push("tourist-tax".into());
    }
}
fn collect_adjustment_effects(data: &Data, price: &Pricing, applied: &mut Vec<String>) {
    if data.extras.iter().any(|extra| extra == "PARKING") {
        applied.push("parking".into());
    }
    if data.extras.iter().any(|extra| extra == "PET") {
        applied.push("pet".into());
    }
    if price.long > 0 {
        applied.push("long-stay".into());
    }
    if price.promo > 0 {
        applied.push("promo".into());
    }
    applied.push("deposit".into());
}
fn success_out(
    data: &Data,
    lines: Vec<NightLine>,
    price: Pricing,
    applied: Vec<String>,
) -> Outcome {
    Outcome::Quote(Quote {
        nights: data.departure - data.arrival,
        night_lines: lines,
        cleaning_fee: price.fees.cleaning,
        extra_guest_fee: price.fees.guests,
        tourist_tax: price.fees.tax,
        extras_fee: price.fees.extras,
        long_stay_discount: price.long,
        promo_discount: price.promo,
        total: price.total,
        deposit: price.deposit,
        balance_due: price.total - price.deposit,
        applied,
        cancellation: cancellation_policy(data.arrival),
    })
}
fn cancellation_policy(arrival: i64) -> String {
    match arrival {
        30.. => "FLEX",
        7.. => "STANDARD",
        _ => "FIRM",
    }
    .into()
}
/// Quote a stay with seasonal rates, fees, discounts, and deposit.
pub fn solution(request: &Request) -> Outcome {
    let data = normalize_request(request);
    if let Some(error) = validate_request(&data) {
        return error;
    }
    let lines = build_lines(&data);
    let price = price_quote(&data, &lines);
    let mut applied = Vec::new();
    collect_stay_effects(&lines, &price, &mut applied);
    collect_adjustment_effects(&data, &price, &mut applied);
    success_out(&data, lines, price, applied)
}
