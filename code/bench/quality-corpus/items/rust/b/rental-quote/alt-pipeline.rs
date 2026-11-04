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
const CLEANING_FEE: i64 = 4500;
const DAYS: std::ops::RangeInclusive<i64> = 0..=1_000_000;
const PROMOS: [&str; 4] = ["", "PCT10", "FIXED5000", "ONENIGHT"];

struct Stay {
    property: String,
    arrival: i64,
    departure: i64,
    adults: i64,
    children: i64,
    extras: Vec<String>,
    bookings: Vec<Booking>,
    promo: String,
}

struct Priced {
    guests: i64,
    tax: i64,
    extras: i64,
    long: i64,
    promo: i64,
    total: i64,
    deposit: i64,
}

fn failure(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}

fn normalise(request: &Request) -> Stay {
    let bookings = request.bookings.iter().map(|b| Booking {
        property_id: b.property_id.trim_matches(' ').to_ascii_uppercase(),
        ..b.clone()
    });
    Stay {
        property: request.property_id.trim_matches(' ').to_ascii_uppercase(),
        arrival: request.arrival,
        departure: request.departure,
        adults: request.adults,
        children: request.children,
        extras: request
            .extras
            .iter()
            .map(|x| x.trim_matches(' ').to_ascii_uppercase())
            .collect(),
        bookings: bookings.collect(),
        promo: request.promo_code.trim_matches(' ').to_ascii_uppercase(),
    }
}

fn check_identity(s: &Stay) -> Result<(), Outcome> {
    if s.property != "CEDAR" && s.property != "LAKE" {
        return Err(failure("BAD_PROPERTY", None));
    }
    if !(1..=8).contains(&s.adults) {
        return Err(failure("BAD_ADULTS", None));
    }
    if !(0..=8).contains(&s.children) {
        return Err(failure("BAD_CHILDREN", None));
    }
    Ok(())
}

fn check_dates(s: &Stay) -> Result<i64, Outcome> {
    let days = [s.arrival, s.departure];
    if days.iter().any(|d| !DAYS.contains(d)) || s.departure <= s.arrival {
        return Err(failure("BAD_DAYS", None));
    }
    Ok(s.departure - s.arrival)
}

fn check_extras(s: &Stay) -> Result<(), Outcome> {
    if s.extras.len() > 4 {
        return Err(failure("BAD_EXTRA", None));
    }
    for (i, x) in s.extras.iter().enumerate() {
        if (x != "PET" && x != "PARKING") || s.extras[..i].contains(x) {
            return Err(failure("BAD_EXTRA", Some(i)));
        }
    }
    Ok(())
}

fn check_bookings(s: &Stay) -> Result<(), Outcome> {
    if s.bookings.len() > 100 {
        return Err(failure("BAD_BOOKING", None));
    }
    for (i, b) in s.bookings.iter().enumerate() {
        if (b.property_id != "CEDAR" && b.property_id != "LAKE")
            || !DAYS.contains(&b.arrival)
            || !DAYS.contains(&b.departure)
            || b.departure <= b.arrival
        {
            return Err(failure("BAD_BOOKING", Some(i)));
        }
    }
    Ok(())
}

fn season(day: i64) -> (&'static str, i64, i64) {
    match day.rem_euclid(365) {
        0..=119 => ("LOW", 5000, 1),
        120..=239 => ("PEAK", 9000, 3),
        _ => ("SHOULDER", 6500, 2),
    }
}

fn check_stay(s: &Stay, n: i64) -> Result<(), Outcome> {
    if !(1..=30).contains(&n) {
        return Err(failure("BAD_STAY", None));
    }
    let capacity = if s.property == "CEDAR" { 4 } else { 6 };
    if s.adults + s.children > capacity {
        return Err(failure("OVER_CAPACITY", None));
    }
    if (s.arrival..s.departure).any(|day| season(day).2 > n) {
        return Err(failure("MIN_STAY", None));
    }
    Ok(())
}

fn check_availability(s: &Stay) -> Result<(), Outcome> {
    let overlapping = s.bookings.iter().enumerate().find(|(_, b)| {
        b.property_id == s.property && s.arrival < b.departure && b.arrival < s.departure
    });
    match overlapping {
        Some((i, _)) => Err(failure("UNAVAILABLE", Some(i))),
        None => Ok(()),
    }
}

fn validate(s: &Stay) -> Result<i64, Outcome> {
    check_identity(s)?;
    let n = check_dates(s)?;
    check_extras(s)?;
    check_bookings(s)?;
    check_stay(s, n)?;
    check_availability(s)?;
    if !PROMOS.contains(&s.promo.as_str()) {
        return Err(failure("BAD_PROMO", None));
    }
    Ok(n)
}

fn nights(s: &Stay) -> Vec<NightLine> {
    (s.arrival..s.departure)
        .map(|day| {
            let (name, base, _) = season(day);
            let weekend = if matches!(day.rem_euclid(7), 4 | 5) {
                1500
            } else {
                0
            };
            NightLine {
                day,
                season: name.into(),
                base_cents: base,
                weekend_cents: weekend,
                night_cents: base + weekend,
            }
        })
        .collect()
}

fn guest_tax_extras(s: &Stay, n: i64) -> (i64, i64, i64) {
    let guests = (2000 * (s.adults - 2).max(0) + 1000 * s.children) * n;
    let tax = 800 * (s.adults + s.children) * n.min(5);
    let extras = s
        .extras
        .iter()
        .map(|x| if x == "PARKING" { 1200 * n } else { 2500 });
    (guests, tax, extras.sum())
}

fn promo_amount(s: &Stay, lines: &[NightLine], basis: i64) -> i64 {
    let cheapest = lines.iter().map(|x| x.night_cents).fold(i64::MAX, i64::min);
    match s.promo.as_str() {
        "PCT10" => (2 * basis * 10 + 100) / 200,
        "FIXED5000" => basis.min(5000),
        "ONENIGHT" => cheapest,
        _ => 0,
    }
}

fn long_stay(subtotal: i64, n: i64) -> i64 {
    let rate = match n {
        14.. => 15,
        7.. => 10,
        _ => 0,
    };
    (2 * subtotal * rate + 100) / 200
}

fn price(s: &Stay, lines: &[NightLine], n: i64) -> Priced {
    let subtotal: i64 = lines.iter().map(|x| x.night_cents).sum();
    let (guests, tax, extras) = guest_tax_extras(s, n);
    let long = long_stay(subtotal, n);
    let basis = subtotal + CLEANING_FEE + guests + tax + extras - long;
    let promo = promo_amount(s, lines, basis);
    let total = basis - promo;
    let deposit = total.min(10000.max((2 * total * 30 + 100) / 200));
    Priced {
        guests,
        tax,
        extras,
        long,
        promo,
        total,
        deposit,
    }
}

fn fee_labels(lines: &[NightLine], p: &Priced) -> Vec<String> {
    [
        (lines.iter().any(|x| x.weekend_cents > 0), "weekend"),
        (true, "cleaning"),
        (p.guests > 0, "extra-guests"),
        (p.tax > 0, "tourist-tax"),
    ]
    .into_iter()
    .filter_map(|(active, label)| active.then(|| label.into()))
    .collect()
}

fn adjustment_labels(s: &Stay, p: &Priced) -> Vec<String> {
    [
        (s.extras.iter().any(|x| x == "PARKING"), "parking"),
        (s.extras.iter().any(|x| x == "PET"), "pet"),
        (p.long > 0, "long-stay"),
        (p.promo > 0, "promo"),
        (p.total > 0, "deposit"),
    ]
    .into_iter()
    .filter_map(|(active, label)| active.then(|| label.into()))
    .collect()
}

fn cancellation(arrival: i64) -> String {
    match arrival {
        30.. => "FLEX",
        7.. => "STANDARD",
        _ => "FIRM",
    }
    .into()
}

fn assemble(s: &Stay, lines: Vec<NightLine>, p: Priced, n: i64) -> Outcome {
    let labels = [fee_labels(&lines, &p), adjustment_labels(s, &p)].concat();
    Outcome::Quote(Quote {
        nights: n,
        night_lines: lines,
        cleaning_fee: CLEANING_FEE,
        extra_guest_fee: p.guests,
        tourist_tax: p.tax,
        extras_fee: p.extras,
        long_stay_discount: p.long,
        promo_discount: p.promo,
        total: p.total,
        deposit: p.deposit,
        balance_due: p.total - p.deposit,
        applied: labels,
        cancellation: cancellation(s.arrival),
    })
}

/// Quote a stay by passing validated values through checked validation and iterator pipelines.
pub fn solution(request: &Request) -> Outcome {
    let stay = normalise(request);
    match validate(&stay) {
        Ok(n) => {
            let lines = nights(&stay);
            let priced = price(&stay, &lines, n);
            assemble(&stay, lines, priced, n)
        }
        Err(outcome) => outcome,
    }
}
