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
            cleaning_fee: cleaning(),
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
fn bad(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn upper(s: &String) -> String {
    s.trim_matches(' ').to_ascii_uppercase()
}
fn norm(r: &Request) -> Data {
    make_data!(r, norm_bits(r))
}
fn norm_bits(r: &Request) -> (String, Vec<String>, Vec<Booking>, String) {
    (
        upper(&r.property_id),
        ext_norm(&r.extras),
        book_norm(&r.bookings),
        upper(&r.promo_code),
    )
}
fn ext_norm(xs: &[String]) -> Vec<String> {
    xs.iter().map(upper).collect()
}
fn book_norm(xs: &[Booking]) -> Vec<Booking> {
    normalized_bookings(xs)
}
fn normalized_bookings(xs: &[Booking]) -> Vec<Booking> {
    xs.iter().map(book).collect()
}
fn book(b: &Booking) -> Booking {
    Booking {
        property_id: upper(&b.property_id),
        arrival: b.arrival,
        departure: b.departure,
    }
}
fn prop(d: &Data) -> Option<Outcome> {
    (!matches!(d.property.as_str(), "CEDAR" | "LAKE")).then(|| bad("BAD_PROPERTY", None))
}
fn adults(d: &Data) -> Option<Outcome> {
    (!(1..=8).contains(&d.adults)).then(|| bad("BAD_ADULTS", None))
}
fn children(d: &Data) -> Option<Outcome> {
    (!(0..=8).contains(&d.children)).then(|| bad("BAD_CHILDREN", None))
}
fn days(a: i64, b: i64) -> bool {
    (0..=1_000_000).contains(&a) && (0..=1_000_000).contains(&b) && b > a
}
fn date_err(d: &Data) -> Option<Outcome> {
    (!days(d.arrival, d.departure)).then(|| bad("BAD_DAYS", None))
}
fn ext(d: &Data) -> Option<Outcome> {
    if d.extras.len() > 4 {
        return Some(bad("BAD_EXTRA", None));
    }
    ext_scan(d)
}
fn ext_scan(d: &Data) -> Option<Outcome> {
    for (i, x) in d.extras.iter().enumerate() {
        if !matches!(x.as_str(), "PARKING" | "PET") || d.extras[..i].contains(x) {
            return Some(bad("BAD_EXTRA", Some(i)));
        }
    }
    None
}
fn books(d: &Data) -> Option<Outcome> {
    if d.bookings.len() > 100 {
        return Some(bad("BAD_BOOKING", None));
    }
    book_scan(d)
}
fn book_scan(d: &Data) -> Option<Outcome> {
    for (i, b) in d.bookings.iter().enumerate() {
        if !matches!(b.property_id.as_str(), "CEDAR" | "LAKE") || !days(b.arrival, b.departure) {
            return Some(bad("BAD_BOOKING", Some(i)));
        }
    }
    None
}
fn stay(d: &Data) -> Option<Outcome> {
    (!(1..=30).contains(&(d.departure - d.arrival))).then(|| bad("BAD_STAY", None))
}
fn capacity(d: &Data) -> Option<Outcome> {
    let cap = if d.property == "CEDAR" { 4 } else { 6 };
    (d.adults + d.children > cap).then(|| bad("OVER_CAPACITY", None))
}
fn seas(day: i64) -> usize {
    match day.rem_euclid(365) {
        0..=119 => 0,
        120..=239 => 1,
        _ => 2,
    }
}
fn mins(d: &Data) -> Option<Outcome> {
    let found = occupied(d);
    let n = d.departure - d.arrival;
    minimum_bad(found, n).then(|| bad("MIN_STAY", None))
}
fn occupied(d: &Data) -> [bool; 3] {
    let mut found = [false; 3];
    for day in d.arrival..d.departure {
        found[seas(day)] = true;
    }
    found
}
fn minimum_bad(found: [bool; 3], n: i64) -> bool {
    found[1] && n < 3 || found[2] && n < 2
}
fn overlap(d: &Data) -> Option<Outcome> {
    d.bookings
        .iter()
        .position(|b| {
            b.property_id == d.property && d.arrival < b.departure && b.arrival < d.departure
        })
        .map(|i| bad("UNAVAILABLE", Some(i)))
}
fn p_err(d: &Data) -> Option<Outcome> {
    (!matches!(d.promo.as_str(), "" | "PCT10" | "FIXED5000" | "ONENIGHT"))
        .then(|| bad("BAD_PROMO", None))
}
fn validate(d: &Data) -> Option<Outcome> {
    scalar_checks(d)
        .or_else(|| list_checks(d))
        .or_else(|| stay_checks(d))
}
fn scalar_checks(d: &Data) -> Option<Outcome> {
    prop(d)
        .or_else(|| adults(d))
        .or_else(|| children(d))
        .or_else(|| date_err(d))
}
fn list_checks(d: &Data) -> Option<Outcome> {
    ext(d).or_else(|| books(d))
}
fn stay_checks(d: &Data) -> Option<Outcome> {
    stay(d)
        .or_else(|| capacity(d))
        .or_else(|| mins(d))
        .or_else(|| overlap(d))
        .or_else(|| p_err(d))
}
fn season(day: i64) -> &'static str {
    match seas(day) {
        0 => "LOW",
        1 => "PEAK",
        _ => "SHOULDER",
    }
}
fn rate(s: &str) -> i64 {
    match s {
        "LOW" => 5000,
        "PEAK" => 9000,
        _ => 6500,
    }
}
fn wk(day: i64) -> i64 {
    if matches!(day.rem_euclid(7), 4 | 5) {
        1500
    } else {
        0
    }
}
fn line(day: i64) -> NightLine {
    let s = season(day);
    make_line!(day, s, rate(s), wk(day))
}
fn rows(d: &Data) -> Vec<NightLine> {
    collect_rows(d)
}
fn collect_rows(d: &Data) -> Vec<NightLine> {
    (d.arrival..d.departure).map(|day| line(day)).collect()
}
fn rhu(n: i64, d: i64) -> i64 {
    (2 * n + d) / (2 * d)
}
fn subtotal(xs: &[NightLine]) -> i64 {
    xs.iter().map(|x| x.night_cents).sum()
}
fn cleaning() -> i64 {
    4500
}
fn guest(d: &Data, n: i64) -> i64 {
    (2000 * (d.adults - 2).max(0) + 1000 * d.children) * n
}
fn tax(d: &Data, n: i64) -> i64 {
    800 * (d.adults + d.children) * n.min(5)
}
fn extra(d: &Data, n: i64) -> i64 {
    extra_fee(d, n)
}
fn extra_fee(d: &Data, n: i64) -> i64 {
    d.extras
        .iter()
        .map(|x| if x == "PARKING" { 1200 * n } else { 2500 })
        .sum()
}
fn long(s: i64, n: i64) -> i64 {
    rhu(s * long_rate(n), 100)
}
fn long_rate(n: i64) -> i64 {
    if n >= 14 {
        15
    } else if n >= 7 {
        10
    } else {
        0
    }
}
fn cut(d: &Data, net: i64, xs: &[NightLine]) -> i64 {
    if d.promo == "PCT10" {
        return rhu(net * 10, 100);
    }
    if d.promo == "FIXED5000" {
        return net.min(5000);
    }
    night_cut(&d.promo, xs)
}
fn night_cut(code: &str, xs: &[NightLine]) -> i64 {
    if code == "ONENIGHT" {
        xs.iter().map(|x| x.night_cents).min().unwrap_or(0)
    } else {
        0
    }
}
fn deposit(total: i64) -> i64 {
    total.min(10_000.max(rhu(total * 30, 100)))
}
fn cancel(day: i64) -> String {
    if day >= 30 {
        "FLEX"
    } else if day >= 7 {
        "STANDARD"
    } else {
        "FIRM"
    }
    .into()
}
fn applied(d: &Data, xs: &[NightLine], v: (i64, i64, i64, i64, i64)) -> Vec<String> {
    let (g, t, l, p, total) = v;
    let mut out = weekend_flags(xs);
    out.extend(fee_flags(d, g, t));
    out.extend(discount_flags(l, p, total));
    out
}
fn weekend_flags(xs: &[NightLine]) -> Vec<String> {
    let mut out = vec!["cleaning".into()];
    if xs.iter().any(|x| x.weekend_cents > 0) {
        out.insert(0, "weekend".into());
    }
    out
}
fn fee_flags(d: &Data, g: i64, t: i64) -> Vec<String> {
    let mut out = guest_flags(g, t);
    out.extend(extra_flags(d));
    out
}
fn guest_flags(g: i64, t: i64) -> Vec<String> {
    let mut out = Vec::new();
    if g > 0 {
        out.push("extra-guests".into());
    }
    if t > 0 {
        out.push("tourist-tax".into());
    }
    out
}
fn extra_flags(d: &Data) -> Vec<String> {
    let mut out = parking_flag(d);
    out.extend(pet_flag(d));
    out
}
fn parking_flag(d: &Data) -> Vec<String> {
    if d.extras.iter().any(|x| x == "PARKING") {
        vec!["parking".into()]
    } else {
        Vec::new()
    }
}
fn pet_flag(d: &Data) -> Vec<String> {
    if d.extras.iter().any(|x| x == "PET") {
        vec!["pet".into()]
    } else {
        Vec::new()
    }
}
fn discount_flags(l: i64, p: i64, total: i64) -> Vec<String> {
    let mut out = long_flags(l);
    out.extend(promo_flags(p));
    out.extend(deposit_flags(total));
    out
}
fn long_flags(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["long-stay".into()]
    } else {
        Vec::new()
    }
}
fn promo_flags(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["promo".into()]
    } else {
        Vec::new()
    }
}
fn deposit_flags(v: i64) -> Vec<String> {
    if v > 0 {
        vec!["deposit".into()]
    } else {
        Vec::new()
    }
}

fn price(d: &Data, xs: &[NightLine], n: i64) -> (i64, i64, i64, i64, i64, i64) {
    price_parts(d, xs, n)
}
fn price_parts(d: &Data, xs: &[NightLine], n: i64) -> (i64, i64, i64, i64, i64, i64) {
    let s = subtotal(xs);
    let f = fees(d, n);
    price_values(d, xs, (s, f, long(s, n)))
}
fn price_values(
    d: &Data,
    xs: &[NightLine],
    v: (i64, (i64, i64, i64), i64),
) -> (i64, i64, i64, i64, i64, i64) {
    let (s, f, l) = v;
    priced(d, xs, (f.0, f.1, f.2, l, pre_price(s, f)))
}
fn pre_price(s: i64, f: (i64, i64, i64)) -> i64 {
    s + cleaning() + f.0 + f.1 + f.2
}
fn fees(d: &Data, n: i64) -> (i64, i64, i64) {
    (guest(d, n), tax(d, n), extra(d, n))
}
fn priced(
    d: &Data,
    xs: &[NightLine],
    v: (i64, i64, i64, i64, i64),
) -> (i64, i64, i64, i64, i64, i64) {
    price_result(v, cut(d, v.4 - v.3, xs))
}
fn price_result(v: (i64, i64, i64, i64, i64), p: i64) -> (i64, i64, i64, i64, i64, i64) {
    (v.0, v.1, v.2, v.3, p, v.4 - v.3 - p)
}
fn quote(d: &Data, xs: Vec<NightLine>) -> Outcome {
    let n = d.departure - d.arrival;
    let (g, t, ex, l, p, total) = price(d, &xs, n);
    quote_record(d, xs, (n, g, t, ex, l, p, total))
}
fn quote_record(d: &Data, xs: Vec<NightLine>, v: (i64, i64, i64, i64, i64, i64, i64)) -> Outcome {
    make_quote!(
        v,
        xs,
        deposit(v.6),
        applied(d, &xs, (v.1, v.2, v.4, v.5, v.6)),
        cancel(d.arrival)
    )
}
/// Quote a stay with seasonal rates, fees, discounts, and deposit.
pub fn solution(request: &Request) -> Outcome {
    let d = norm(request);
    if let Some(e) = validate(&d) {
        return e;
    }
    quote(&d, rows(&d))
}
