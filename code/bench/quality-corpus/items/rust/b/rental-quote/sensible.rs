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
#[derive(Clone)]
struct Amounts {
    subtotal: i64,
    cleaning: i64,
    guest: i64,
    tax: i64,
    extras: i64,
    long: i64,
    promo: i64,
    total: i64,
    deposit: i64,
}
fn error(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn normalize(r: &Request) -> Data {
    Data {
        property: r.property_id.trim_matches(' ').to_ascii_uppercase(),
        arrival: r.arrival,
        departure: r.departure,
        adults: r.adults,
        children: r.children,
        extras: r
            .extras
            .iter()
            .map(|x| x.trim_matches(' ').to_ascii_uppercase())
            .collect(),
        bookings: r
            .bookings
            .iter()
            .map(|b| Booking {
                property_id: b.property_id.trim_matches(' ').to_ascii_uppercase(),
                arrival: b.arrival,
                departure: b.departure,
            })
            .collect(),
        promo: r.promo_code.trim_matches(' ').to_ascii_uppercase(),
    }
}
fn validate_identity(d: &Data) -> Option<Outcome> {
    if !["CEDAR", "LAKE"].contains(&d.property.as_str()) {
        return Some(error("BAD_PROPERTY", None));
    }
    if !(1..=8).contains(&d.adults) {
        return Some(error("BAD_ADULTS", None));
    }
    if !(0..=8).contains(&d.children) {
        return Some(error("BAD_CHILDREN", None));
    }
    None
}
fn validate_days(d: &Data) -> Option<Outcome> {
    let bounded = (0..=1_000_000).contains(&d.arrival) && (0..=1_000_000).contains(&d.departure);
    if !bounded || d.departure <= d.arrival {
        return Some(error("BAD_DAYS", None));
    }
    None
}
fn validate_extras(d: &Data) -> Option<Outcome> {
    if d.extras.len() > 4 {
        return Some(error("BAD_EXTRA", None));
    }
    let mut seen: Vec<&String> = Vec::new();
    for (i, x) in d.extras.iter().enumerate() {
        if !["PARKING", "PET"].contains(&x.as_str()) || seen.contains(&x) {
            return Some(error("BAD_EXTRA", Some(i)));
        }
        seen.push(x);
    }
    None
}
fn validate_bookings(d: &Data) -> Option<Outcome> {
    if d.bookings.len() > 100 {
        return Some(error("BAD_BOOKING", None));
    }
    for (i, b) in d.bookings.iter().enumerate() {
        if !["CEDAR", "LAKE"].contains(&b.property_id.as_str())
            || !(0..=1_000_000).contains(&b.arrival)
            || !(0..=1_000_000).contains(&b.departure)
            || b.departure <= b.arrival
        {
            return Some(error("BAD_BOOKING", Some(i)));
        }
    }
    None
}
fn validate_stay(d: &Data) -> Option<Outcome> {
    let nights = d.departure - d.arrival;
    if !(1..=30).contains(&nights) {
        return Some(error("BAD_STAY", None));
    }
    let capacity = if d.property == "CEDAR" { 4 } else { 6 };
    if d.adults + d.children > capacity {
        return Some(error("OVER_CAPACITY", None));
    }
    None
}
fn validate_minimums(d: &Data) -> Option<Outcome> {
    let nights = d.departure - d.arrival;
    let mut counts = [0, 0, 0];
    for day in d.arrival..d.departure {
        let position = day.rem_euclid(365);
        counts[if position < 120 {
            0
        } else if position < 240 {
            1
        } else {
            2
        }] += 1;
    }
    if (counts[0] > 0 && nights < 1)
        || (counts[1] > 0 && nights < 3)
        || (counts[2] > 0 && nights < 2)
    {
        return Some(error("MIN_STAY", None));
    }
    None
}
fn validate_availability(d: &Data) -> Option<Outcome> {
    for (i, b) in d.bookings.iter().enumerate() {
        if b.property_id == d.property && d.arrival < b.departure && b.arrival < d.departure {
            return Some(error("UNAVAILABLE", Some(i)));
        }
    }
    None
}
fn validate(d: &Data) -> Option<Outcome> {
    validate_identity(d)
        .or_else(|| validate_days(d))
        .or_else(|| validate_extras(d))
        .or_else(|| validate_bookings(d))
        .or_else(|| validate_stay(d))
        .or_else(|| validate_minimums(d))
        .or_else(|| validate_availability(d))
        .or_else(|| {
            if ["", "PCT10", "FIXED5000", "ONENIGHT"].contains(&d.promo.as_str()) {
                None
            } else {
                Some(error("BAD_PROMO", None))
            }
        })
}
fn rows(d: &Data) -> Vec<NightLine> {
    (d.arrival..d.departure)
        .map(|day| {
            let position = day.rem_euclid(365);
            let (season, base) = if position < 120 {
                ("LOW", 5000)
            } else if position < 240 {
                ("PEAK", 9000)
            } else {
                ("SHOULDER", 6500)
            };
            let weekend = if matches!(day.rem_euclid(7), 4 | 5) {
                1500
            } else {
                0
            };
            NightLine {
                day,
                season: season.into(),
                base_cents: base,
                weekend_cents: weekend,
                night_cents: base + weekend,
            }
        })
        .collect()
}
fn guest_charges(d: &Data, nights: i64) -> (i64, i64) {
    let guest = (2000 * (d.adults - 2).max(0) + 1000 * d.children) * nights;
    let tax = 800 * (d.adults + d.children) * nights.min(5);
    (guest, tax)
}
fn price_fees(d: &Data, lines: &[NightLine]) -> Amounts {
    let nights = d.departure - d.arrival;
    let subtotal = lines.iter().map(|x| x.night_cents).sum();
    let (guest, tax) = guest_charges(d, nights);
    let extras = d
        .extras
        .iter()
        .map(|x| if x == "PARKING" { 1200 * nights } else { 2500 })
        .sum();
    Amounts {
        subtotal,
        cleaning: 4500,
        guest,
        tax,
        extras,
        long: 0,
        promo: 0,
        total: subtotal + 4500 + guest + tax + extras,
        deposit: 0,
    }
}
fn apply_long(d: &Data, a: &mut Amounts) {
    let nights = d.departure - d.arrival;
    let rate = match nights {
        14.. => 15,
        7.. => 10,
        _ => 0,
    };
    a.long = (2 * a.subtotal * rate + 100) / 200;
}
fn apply_promo(d: &Data, lines: &[NightLine], a: &mut Amounts) {
    let remaining = a.total - a.long;
    a.promo = match d.promo.as_str() {
        "PCT10" => (2 * remaining * 10 + 100) / 200,
        "FIXED5000" => 5000.min(remaining),
        "ONENIGHT" => lines.iter().map(|x| x.night_cents).min().unwrap_or(0),
        _ => 0,
    };
    a.total = remaining - a.promo;
}
fn price(d: &Data, lines: &[NightLine]) -> Amounts {
    let mut amounts = price_fees(d, lines);
    apply_long(d, &mut amounts);
    apply_promo(d, lines, &mut amounts);
    amounts.deposit = amounts
        .total
        .min(10_000.max((2 * amounts.total * 30 + 100) / 200));
    amounts
}
const BASE_LABELS: [&str; 6] = [
    "weekend",
    "cleaning",
    "extra-guests",
    "tourist-tax",
    "parking",
    "pet",
];
fn base_effects(d: &Data, lines: &[NightLine], a: &Amounts) -> Vec<String> {
    let flags = [
        lines.iter().any(|x| x.weekend_cents > 0),
        true,
        a.guest > 0,
        a.tax > 0,
        d.extras.iter().any(|x| x == "PARKING"),
        d.extras.iter().any(|x| x == "PET"),
    ];
    flags
        .into_iter()
        .zip(BASE_LABELS)
        .filter_map(|(on, name)| on.then(|| name.into()))
        .collect()
}
fn applied(d: &Data, lines: &[NightLine], a: &Amounts) -> Vec<String> {
    let mut names = base_effects(d, lines, a);
    for (active, name) in [
        (a.long > 0, "long-stay"),
        (a.promo > 0, "promo"),
        (a.total > 0, "deposit"),
    ] {
        if active {
            names.push(name.into());
        }
    }
    names
}
fn assemble(d: &Data, lines: Vec<NightLine>, a: Amounts) -> Outcome {
    let applied = applied(d, &lines, &a);
    Outcome::Quote(Quote {
        nights: d.departure - d.arrival,
        night_lines: lines,
        cleaning_fee: a.cleaning,
        extra_guest_fee: a.guest,
        tourist_tax: a.tax,
        extras_fee: a.extras,
        long_stay_discount: a.long,
        promo_discount: a.promo,
        total: a.total,
        deposit: a.deposit,
        balance_due: a.total - a.deposit,
        applied,
        cancellation: match d.arrival {
            30.. => "FLEX",
            7.. => "STANDARD",
            _ => "FIRM",
        }
        .into(),
    })
}
/// Quote a stay with seasonal rates, fees, discounts, and deposit.
pub fn solution(request: &Request) -> Outcome {
    let d = normalize(request);
    if let Some(out) = validate(&d) {
        return out;
    }
    let lines = rows(&d);
    let amounts = price(&d, &lines);
    assemble(&d, lines, amounts)
}
