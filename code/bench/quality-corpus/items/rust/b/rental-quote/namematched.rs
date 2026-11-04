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
macro_rules! make_data {
    ($r:expr,$v:expr) => {
        Data {
            property: $v.0,
            arrival: $r.arrival,
            departure: $r.departure,
            adults: $r.adults,
            children: $r.children,
            extras: $v.1,
            bookings: $v.2,
            promo: $v.3,
        }
    };
}
macro_rules! make_line {
    ($day:expr,$s:expr,$b:expr,$w:expr) => {
        NightLine {
            day: $day,
            season: $s.into(),
            base_cents: $b,
            weekend_cents: $w,
            night_cents: $b + $w,
        }
    };
}
macro_rules! make_quote {
    ($v:expr,$xs:expr,$dep:expr,$effects:expr,$cancel:expr) => {
        Outcome::Quote(Quote {
            nights: $v.0,
            night_lines: $xs.clone(),
            cleaning_fee: cleaning_fee(),
            extra_guest_fee: $v.1,
            tourist_tax: $v.2,
            extras_fee: $v.3,
            long_stay_discount: $v.4,
            promo_discount: $v.5,
            total: $v.6,
            deposit: $dep,
            balance_due: $v.6 - $dep,
            applied: $effects,
            cancellation: $cancel,
        })
    };
}
fn error_result(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn normalize_text(s: &String) -> String {
    s.trim_matches(' ').to_ascii_uppercase()
}
fn normalize_request(r: &Request) -> Data {
    make_data!(r, normalized_fields(r))
}
fn normalized_fields(r: &Request) -> (String, Vec<String>, Vec<Booking>, String) {
    (
        normalize_text(&r.property_id),
        normalize_extras(&r.extras),
        normalize_bookings(&r.bookings),
        normalize_text(&r.promo_code),
    )
}
fn normalize_extras(xs: &[String]) -> Vec<String> {
    xs.iter().map(normalize_text).collect()
}
fn normalize_bookings(xs: &[Booking]) -> Vec<Booking> {
    normalized_booking_records(xs)
}
fn normalized_booking_records(xs: &[Booking]) -> Vec<Booking> {
    xs.iter().map(normalize_booking).collect()
}
fn normalize_booking(b: &Booking) -> Booking {
    Booking {
        property_id: normalize_text(&b.property_id),
        arrival: b.arrival,
        departure: b.departure,
    }
}
fn property_error(d: &Data) -> Option<Outcome> {
    (!matches!(d.property.as_str(), "CEDAR" | "LAKE")).then(|| error_result("BAD_PROPERTY", None))
}
fn adult_count_error(d: &Data) -> Option<Outcome> {
    (!(1..=8).contains(&d.adults)).then(|| error_result("BAD_ADULTS", None))
}
fn child_count_error(d: &Data) -> Option<Outcome> {
    (!(0..=8).contains(&d.children)).then(|| error_result("BAD_CHILDREN", None))
}
fn valid_days(a: i64, b: i64) -> bool {
    (0..=1_000_000).contains(&a) && (0..=1_000_000).contains(&b) && b > a
}
fn day_range_error(d: &Data) -> Option<Outcome> {
    (!valid_days(d.arrival, d.departure)).then(|| error_result("BAD_DAYS", None))
}
fn extra_error(d: &Data) -> Option<Outcome> {
    if d.extras.len() > 4 {
        return Some(error_result("BAD_EXTRA", None));
    }
    scan_extras(d)
}
fn scan_extras(d: &Data) -> Option<Outcome> {
    for (i, x) in d.extras.iter().enumerate() {
        if !matches!(x.as_str(), "PARKING" | "PET") || d.extras[..i].contains(x) {
            return Some(error_result("BAD_EXTRA", Some(i)));
        }
    }
    None
}
fn booking_error(d: &Data) -> Option<Outcome> {
    if d.bookings.len() > 100 {
        return Some(error_result("BAD_BOOKING", None));
    }
    scan_bookings(d)
}
fn scan_bookings(d: &Data) -> Option<Outcome> {
    for (i, b) in d.bookings.iter().enumerate() {
        if !matches!(b.property_id.as_str(), "CEDAR" | "LAKE")
            || !valid_days(b.arrival, b.departure)
        {
            return Some(error_result("BAD_BOOKING", Some(i)));
        }
    }
    None
}
fn stay_length_error(d: &Data) -> Option<Outcome> {
    (!(1..=30).contains(&(d.departure - d.arrival))).then(|| error_result("BAD_STAY", None))
}
fn capacity_error(d: &Data) -> Option<Outcome> {
    let cap = if d.property == "CEDAR" { 4 } else { 6 };
    (d.adults + d.children > cap).then(|| error_result("OVER_CAPACITY", None))
}
fn season_index(day: i64) -> usize {
    match day.rem_euclid(365) {
        0..=119 => 0,
        120..=239 => 1,
        _ => 2,
    }
}
fn minimum_stay_error(d: &Data) -> Option<Outcome> {
    let found = occupied_seasons(d);
    let n = d.departure - d.arrival;
    minimum_fails(found, n).then(|| error_result("MIN_STAY", None))
}
fn occupied_seasons(d: &Data) -> [bool; 3] {
    let mut found = [false; 3];
    for day in d.arrival..d.departure {
        found[season_index(day)] = true;
    }
    found
}
fn minimum_fails(found: [bool; 3], n: i64) -> bool {
    found[1] && n < 3 || found[2] && n < 2
}
fn booking_overlap_error(d: &Data) -> Option<Outcome> {
    d.bookings
        .iter()
        .position(|b| {
            b.property_id == d.property && d.arrival < b.departure && b.arrival < d.departure
        })
        .map(|i| error_result("UNAVAILABLE", Some(i)))
}
fn promo_validation_error(d: &Data) -> Option<Outcome> {
    (!matches!(d.promo.as_str(), "" | "PCT10" | "FIXED5000" | "ONENIGHT"))
        .then(|| error_result("BAD_PROMO", None))
}
fn validate_request(d: &Data) -> Option<Outcome> {
    scalar_validation(d)
        .or_else(|| list_validation(d))
        .or_else(|| stay_validation(d))
}
fn scalar_validation(d: &Data) -> Option<Outcome> {
    property_error(d)
        .or_else(|| adult_count_error(d))
        .or_else(|| child_count_error(d))
        .or_else(|| day_range_error(d))
}
fn list_validation(d: &Data) -> Option<Outcome> {
    extra_error(d).or_else(|| booking_error(d))
}
fn stay_validation(d: &Data) -> Option<Outcome> {
    stay_length_error(d)
        .or_else(|| capacity_error(d))
        .or_else(|| minimum_stay_error(d))
        .or_else(|| booking_overlap_error(d))
        .or_else(|| promo_validation_error(d))
}
fn season_for_day(day: i64) -> &'static str {
    match season_index(day) {
        0 => "LOW",
        1 => "PEAK",
        _ => "SHOULDER",
    }
}
fn base_rate(s: &str) -> i64 {
    match s {
        "LOW" => 5000,
        "PEAK" => 9000,
        _ => 6500,
    }
}
fn weekend_surcharge(day: i64) -> i64 {
    if matches!(day.rem_euclid(7), 4 | 5) {
        1500
    } else {
        0
    }
}
fn make_night_line(day: i64) -> NightLine {
    let s = season_for_day(day);
    make_line!(day, s, base_rate(s), weekend_surcharge(day))
}
fn make_night_lines(d: &Data) -> Vec<NightLine> {
    collect_night_lines(d)
}
fn collect_night_lines(d: &Data) -> Vec<NightLine> {
    (d.arrival..d.departure)
        .map(|day| make_night_line(day))
        .collect()
}
fn round_half_up(n: i64, d: i64) -> i64 {
    (2 * n + d) / (2 * d)
}
fn night_subtotal(xs: &[NightLine]) -> i64 {
    xs.iter().map(|x| x.night_cents).sum()
}
fn cleaning_fee() -> i64 {
    4500
}
fn extra_guest_fee(d: &Data, n: i64) -> i64 {
    (2000 * (d.adults - 2).max(0) + 1000 * d.children) * n
}
fn tourist_tax(d: &Data, n: i64) -> i64 {
    800 * (d.adults + d.children) * n.min(5)
}
fn extras_fee(d: &Data, n: i64) -> i64 {
    calculate_extra_fees(d, n)
}
fn calculate_extra_fees(d: &Data, n: i64) -> i64 {
    d.extras
        .iter()
        .map(|x| if x == "PARKING" { 1200 * n } else { 2500 })
        .sum()
}
fn long_stay_discount(s: i64, n: i64) -> i64 {
    round_half_up(s * long_stay_rate(n), 100)
}
fn long_stay_rate(n: i64) -> i64 {
    if n >= 14 {
        15
    } else if n >= 7 {
        10
    } else {
        0
    }
}
fn promo_discount(d: &Data, net: i64, xs: &[NightLine]) -> i64 {
    if d.promo == "PCT10" {
        return round_half_up(net * 10, 100);
    }
    if d.promo == "FIXED5000" {
        return net.min(5000);
    }
    one_night_discount(&d.promo, xs)
}
fn one_night_discount(code: &str, xs: &[NightLine]) -> i64 {
    if code == "ONENIGHT" {
        xs.iter().map(|x| x.night_cents).min().unwrap_or(0)
    } else {
        0
    }
}
fn deposit_amount(total: i64) -> i64 {
    total.min(10_000.max(round_half_up(total * 30, 100)))
}
fn cancellation_policy(day: i64) -> String {
    if day >= 30 {
        "FLEX"
    } else if day >= 7 {
        "STANDARD"
    } else {
        "FIRM"
    }
    .into()
}
fn applied_adjustments(d: &Data, xs: &[NightLine], v: (i64, i64, i64, i64, i64)) -> Vec<String> {
    let (g, t, l, p, total) = v;
    let mut out = weekend_effects(xs);
    out.extend(fee_effects(d, g, t));
    out.extend(discount_effects(l, p, total));
    out
}
fn weekend_effects(xs: &[NightLine]) -> Vec<String> {
    let mut out = vec!["cleaning".into()];
    if xs.iter().any(|x| x.weekend_cents > 0) {
        out.insert(0, "weekend".into());
    }
    out
}
fn fee_effects(d: &Data, g: i64, t: i64) -> Vec<String> {
    let mut out = guest_effects(g, t);
    out.extend(extra_effects(d));
    out
}
fn guest_effects(g: i64, t: i64) -> Vec<String> {
    let mut out = Vec::new();
    if g > 0 {
        out.push("extra-guests".into());
    }
    if t > 0 {
        out.push("tourist-tax".into());
    }
    out
}
fn extra_effects(d: &Data) -> Vec<String> {
    let mut out = parking_effect(d);
    out.extend(pet_effect(d));
    out
}
fn parking_effect(d: &Data) -> Vec<String> {
    if d.extras.iter().any(|x| x == "PARKING") {
        vec!["parking".into()]
    } else {
        Vec::new()
    }
}
fn pet_effect(d: &Data) -> Vec<String> {
    if d.extras.iter().any(|x| x == "PET") {
        vec!["pet".into()]
    } else {
        Vec::new()
    }
}
fn discount_effects(l: i64, p: i64, total: i64) -> Vec<String> {
    let mut out = long_stay_effect(l);
    out.extend(promo_effect(p));
    out.extend(deposit_effect(total));
    out
}
fn long_stay_effect(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["long-stay".into()]
    } else {
        Vec::new()
    }
}
fn promo_effect(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["promo".into()]
    } else {
        Vec::new()
    }
}
fn deposit_effect(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["deposit".into()]
    } else {
        Vec::new()
    }
}

fn price_quote(d: &Data, xs: &[NightLine], n: i64) -> (i64, i64, i64, i64, i64, i64) {
    price_components(d, xs, n)
}
fn price_components(d: &Data, xs: &[NightLine], n: i64) -> (i64, i64, i64, i64, i64, i64) {
    let s = night_subtotal(xs);
    let f = stay_fees(d, n);
    price_result_values(d, xs, (s, f, long_stay_discount(s, n)))
}
fn price_result_values(
    d: &Data,
    xs: &[NightLine],
    v: (i64, (i64, i64, i64), i64),
) -> (i64, i64, i64, i64, i64, i64) {
    let (s, f, l) = v;
    finish_price(d, xs, (f.0, f.1, f.2, l, pre_discount_total(s, f)))
}
fn pre_discount_total(s: i64, f: (i64, i64, i64)) -> i64 {
    s + cleaning_fee() + f.0 + f.1 + f.2
}
fn stay_fees(d: &Data, n: i64) -> (i64, i64, i64) {
    (extra_guest_fee(d, n), tourist_tax(d, n), extras_fee(d, n))
}
fn finish_price(
    d: &Data,
    xs: &[NightLine],
    v: (i64, i64, i64, i64, i64),
) -> (i64, i64, i64, i64, i64, i64) {
    discounted_total(v, promo_discount(d, v.4 - v.3, xs))
}
fn discounted_total(v: (i64, i64, i64, i64, i64), p: i64) -> (i64, i64, i64, i64, i64, i64) {
    (v.0, v.1, v.2, v.3, p, v.4 - v.3 - p)
}
fn assemble_quote(d: &Data, xs: Vec<NightLine>) -> Outcome {
    let n = d.departure - d.arrival;
    let (g, t, ex, l, p, total) = price_quote(d, &xs, n);
    quote_output(d, xs, (n, g, t, ex, l, p, total))
}
fn quote_output(d: &Data, xs: Vec<NightLine>, v: (i64, i64, i64, i64, i64, i64, i64)) -> Outcome {
    make_quote!(
        v,
        xs,
        deposit_amount(v.6),
        applied_adjustments(d, &xs, (v.1, v.2, v.4, v.5, v.6)),
        cancellation_policy(d.arrival)
    )
}
/// Quote a stay with seasonal rates, fees, discounts, and deposit.
pub fn solution(request: &Request) -> Outcome {
    let d = normalize_request(request);
    if let Some(e) = validate_request(&d) {
        return e;
    }
    assemble_quote(&d, make_night_lines(&d))
}
