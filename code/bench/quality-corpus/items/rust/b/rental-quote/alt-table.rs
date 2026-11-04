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
struct Fees {
    guests: i64,
    tax: i64,
    extras: i64,
}
struct State {
    lines: Vec<NightLine>,
    fees: Fees,
    long: i64,
    promo: i64,
    total: i64,
    deposit: i64,
}
struct Season {
    start: i64,
    end: i64,
    name: &'static str,
    base: i64,
    min_nights: i64,
}
const SEASONS: [Season; 3] = [
    Season {
        start: 0,
        end: 120,
        name: "LOW",
        base: 5000,
        min_nights: 1,
    },
    Season {
        start: 120,
        end: 240,
        name: "PEAK",
        base: 9000,
        min_nights: 3,
    },
    Season {
        start: 240,
        end: 365,
        name: "SHOULDER",
        base: 6500,
        min_nights: 2,
    },
];
const CLEANING: i64 = 4500;
const LABELS: [&str; 9] = [
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
fn error(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn normalise(request: &Request) -> Stay {
    Stay {
        property: request.property_id.trim_matches(' ').to_ascii_uppercase(),
        arrival: request.arrival,
        departure: request.departure,
        adults: request.adults,
        children: request.children,
        extras: request
            .extras
            .iter()
            .map(|s| s.trim_matches(' ').to_ascii_uppercase())
            .collect(),
        bookings: request
            .bookings
            .iter()
            .map(|b| Booking {
                property_id: b.property_id.trim_matches(' ').to_ascii_uppercase(),
                arrival: b.arrival,
                departure: b.departure,
            })
            .collect(),
        promo: request.promo_code.trim_matches(' ').to_ascii_uppercase(),
    }
}
fn identity(s: &Stay) -> Option<Outcome> {
    if s.property != "CEDAR" && s.property != "LAKE" {
        return Some(error("BAD_PROPERTY", None));
    }
    if !(1..=8).contains(&s.adults) {
        return Some(error("BAD_ADULTS", None));
    }
    if !(0..=8).contains(&s.children) {
        return Some(error("BAD_CHILDREN", None));
    }
    None
}
fn days(s: &Stay) -> Option<Outcome> {
    (!(0..=1_000_000).contains(&s.arrival)
        || !(0..=1_000_000).contains(&s.departure)
        || s.departure <= s.arrival)
        .then(|| error("BAD_DAYS", None))
}
fn extras(s: &Stay) -> Option<Outcome> {
    if s.extras.len() > 4 {
        return Some(error("BAD_EXTRA", None));
    }
    for (i, x) in s.extras.iter().enumerate() {
        if (x != "PET" && x != "PARKING") || s.extras[..i].contains(x) {
            return Some(error("BAD_EXTRA", Some(i)));
        }
    }
    None
}
fn bookings(s: &Stay) -> Option<Outcome> {
    if s.bookings.len() > 100 {
        return Some(error("BAD_BOOKING", None));
    }
    for (index, booking) in s.bookings.iter().enumerate() {
        let property_ok = booking.property_id == "CEDAR" || booking.property_id == "LAKE";
        let days_ok = (0..=1_000_000).contains(&booking.arrival)
            && (0..=1_000_000).contains(&booking.departure)
            && booking.departure > booking.arrival;
        if !property_ok || !days_ok {
            return Some(error("BAD_BOOKING", Some(index)));
        }
    }
    None
}
fn capacity(s: &Stay) -> Option<Outcome> {
    if !(1..=30).contains(&(s.departure - s.arrival)) {
        return Some(error("BAD_STAY", None));
    }
    if s.adults + s.children > if s.property == "CEDAR" { 4 } else { 6 } {
        return Some(error("OVER_CAPACITY", None));
    }
    None
}
fn minimums(s: &Stay) -> Option<Outcome> {
    let n = s.departure - s.arrival;
    for season in &SEASONS {
        let active = (s.arrival..s.departure)
            .any(|day| (season.start..season.end).contains(&day.rem_euclid(365)));
        if active && n < season.min_nights {
            return Some(error("MIN_STAY", None));
        }
    }
    None
}
fn availability(s: &Stay) -> Option<Outcome> {
    for (i, booking) in s.bookings.iter().enumerate() {
        if booking.property_id == s.property
            && s.arrival < booking.departure
            && booking.arrival < s.departure
        {
            return Some(error("UNAVAILABLE", Some(i)));
        }
    }
    None
}
fn promo(s: &Stay) -> Option<Outcome> {
    let known = ["", "PCT10", "FIXED5000", "ONENIGHT"].contains(&s.promo.as_str());
    (!known).then(|| error("BAD_PROMO", None))
}
fn run_checks(s: &Stay) -> Result<(), Outcome> {
    let checks: [fn(&Stay) -> Option<Outcome>; 8] = [
        identity,
        days,
        extras,
        bookings,
        capacity,
        minimums,
        availability,
        promo,
    ];
    match checks.iter().find_map(|check| check(s)) {
        Some(problem) => Err(problem),
        None => Ok(()),
    }
}
fn lines(s: &Stay) -> Vec<NightLine> {
    let mut rows = Vec::new();
    for day in s.arrival..s.departure {
        let position = day.rem_euclid(365);
        let season = SEASONS
            .iter()
            .find(|x| (x.start..x.end).contains(&position))
            .expect("position lies in a season");
        let weekend = 1500 * i64::from(matches!(day.rem_euclid(7), 4 | 5));
        rows.push(NightLine {
            day,
            season: season.name.into(),
            base_cents: season.base,
            weekend_cents: weekend,
            night_cents: season.base + weekend,
        });
    }
    rows
}
fn long_stay(subtotal: i64, nights: i64) -> i64 {
    let rate = match nights {
        14.. => 15,
        7.. => 10,
        _ => 0,
    };
    (2 * subtotal * rate + 100) / 200
}
fn promo_amount(s: &Stay, l: &[NightLine], base: i64) -> i64 {
    match s.promo.as_str() {
        "PCT10" => (2 * base * 10 + 100) / 200,
        "FIXED5000" => base.min(5000),
        "ONENIGHT" => l
            .iter()
            .map(|row| row.night_cents)
            .min()
            .expect("validated stay contains a night"),
        _ => 0,
    }
}
fn fees(s: &Stay, nights: i64) -> Fees {
    Fees {
        guests: (2000 * (s.adults - 2).max(0) + 1000 * s.children) * nights,
        tax: 800 * (s.adults + s.children) * nights.min(5),
        extras: s
            .extras
            .iter()
            .map(|x| if x == "PARKING" { 1200 * nights } else { 2500 })
            .sum(),
    }
}
fn computed(s: &Stay, l: Vec<NightLine>) -> State {
    let nights = l.len() as i64;
    let subtotal: i64 = l.iter().map(|row| row.night_cents).sum();
    let charges = fees(s, nights);
    let long = long_stay(subtotal, nights);
    let base = subtotal + CLEANING + charges.guests + charges.tax + charges.extras - long;
    let promo = promo_amount(s, &l, base);
    let total = base - promo;
    State {
        lines: l,
        fees: charges,
        long,
        promo,
        total,
        deposit: total.min(10000.max((2 * total * 30 + 100) / 200)),
    }
}
fn applied_names(s: &Stay, q: &State) -> Vec<String> {
    let flags = [
        q.lines.iter().any(|line| line.weekend_cents > 0),
        true,
        q.fees.guests > 0,
        q.fees.tax > 0,
        s.extras.contains(&"PARKING".into()),
        s.extras.contains(&"PET".into()),
        q.long > 0,
        q.promo > 0,
        q.total > 0,
    ];
    flags
        .into_iter()
        .zip(LABELS)
        .filter_map(|(active, name)| active.then(|| name.into()))
        .collect()
}
fn assemble(s: &Stay, q: State, applied: Vec<String>) -> Outcome {
    let cancellation = match s.arrival {
        30.. => "FLEX",
        7.. => "STANDARD",
        _ => "FIRM",
    }
    .into();
    Outcome::Quote(Quote {
        nights: q.lines.len() as i64,
        night_lines: q.lines,
        cleaning_fee: CLEANING,
        extra_guest_fee: q.fees.guests,
        tourist_tax: q.fees.tax,
        extras_fee: q.fees.extras,
        long_stay_discount: q.long,
        promo_discount: q.promo,
        total: q.total,
        deposit: q.deposit,
        balance_due: q.total - q.deposit,
        applied,
        cancellation,
    })
}
pub fn solution(request: &Request) -> Outcome {
    let stay = normalise(request);
    if let Err(problem) = run_checks(&stay) {
        return problem;
    }
    let rows = lines(&stay);
    let priced = computed(&stay, rows);
    let applied = applied_names(&stay, &priced);
    assemble(&stay, priced, applied)
}
