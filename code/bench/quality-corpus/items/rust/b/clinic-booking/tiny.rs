#[derive(Debug, Clone, PartialEq)]
pub struct Request {
    pub now_day: i64,
    pub now_minute: i64,
    pub requested_day: i64,
    pub horizon_days: i64,
    pub kind: String,
    pub urgent: bool,
    pub preferred_doctor: String,
    pub holidays: Vec<i64>,
    pub doctors: Vec<Doctor>,
    pub bookings: Vec<Booking>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Doctor {
    pub name: String,
    pub windows: Vec<Window>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Window {
    pub weekday: i64,
    pub open: i64,
    pub close: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Booking {
    pub day: i64,
    pub start: i64,
    pub end: i64,
    pub doctor: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Appointment {
    pub day: i64,
    pub start: i64,
    pub end: i64,
    pub doctor: String,
    pub trace: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ClinicError {
    pub code: String,
    pub index: Option<usize>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Appointment(Appointment),
    Error(ClinicError),
}

#[derive(Clone)]
struct Normalized {
    kind: String,
    preferred: String,
    doctors: Vec<Doctor>,
    bookings: Vec<Booking>,
}

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Slot {
    order: (i64, i64, String),
    day: i64,
    start: i64,
    end: i64,
    doctor: String,
}

/// Return the earliest valid appointment or the first validation error.
pub fn solution(request: &Request) -> Outcome {
    let n = norm(request);
    let size = kind(&n.kind);
    if let Some(e) = checks(request, &n) {
        return Outcome::Error(e);
    }
    finish(first_slot(request, &n, size.0, size.1))
}
fn norm(r: &Request) -> Normalized {
    Normalized {
        kind: lower(r.kind.trim_matches(' ')),
        preferred: lower(r.preferred_doctor.trim_matches(' ')),
        doctors: norm_doctors(&r.doctors),
        bookings: norm_bookings(&r.bookings),
    }
}
fn lower(s: &str) -> String {
    s.to_ascii_lowercase()
}
fn norm_doctors(ds: &[Doctor]) -> Vec<Doctor> {
    ds.iter().map(norm_doctor).collect()
}
fn norm_doctor(d: &Doctor) -> Doctor {
    Doctor {
        name: d.name.trim_matches(' ').to_string(),
        windows: d.windows.clone(),
    }
}
fn norm_bookings(bs: &[Booking]) -> Vec<Booking> {
    bs.iter().map(norm_booking).collect()
}
fn norm_booking(b: &Booking) -> Booking {
    Booking {
        day: b.day,
        start: b.start,
        end: b.end,
        doctor: lower(b.doctor.trim_matches(' ')),
    }
}
fn checks(r: &Request, n: &Normalized) -> Option<ClinicError> {
    early_checks(r, n).or_else(|| later_checks(r, n))
}
fn early_checks(r: &Request, n: &Normalized) -> Option<ClinicError> {
    scalar(r, n)
        .or_else(|| doctors(&n.doctors))
        .or_else(|| windows(&n.doctors))
        .or_else(|| holidays(&r.holidays))
}
fn later_checks(r: &Request, n: &Normalized) -> Option<ClinicError> {
    bookings(n)
        .or_else(|| preference(n))
        .or_else(|| day_order(r))
}
fn error(code: &str, index: Option<usize>) -> ClinicError {
    ClinicError {
        code: code.to_string(),
        index,
    }
}
fn scalar(r: &Request, n: &Normalized) -> Option<ClinicError> {
    let valid = days_ok(r) && clock_ok(r) && kind_ok(&n.kind);
    (!valid).then(|| error("BAD_REQUEST", None))
}
fn days_ok(r: &Request) -> bool {
    (0..=1_000_000).contains(&r.now_day) && (0..=1_000_000).contains(&r.requested_day)
}
fn clock_ok(r: &Request) -> bool {
    (0..=1439).contains(&r.now_minute) && (0..=14).contains(&r.horizon_days)
}
fn kind_ok(k: &str) -> bool {
    ["checkup", "consultation", "procedure"].contains(&k)
}
fn doctors(ds: &[Doctor]) -> Option<ClinicError> {
    if !(1..=12).contains(&ds.len()) {
        return Some(error("BAD_DOCTORS", None));
    }
    duplicate_doctor(ds)
}
fn duplicate_doctor(ds: &[Doctor]) -> Option<ClinicError> {
    for (i, d) in ds.iter().enumerate() {
        if !doctor_name_ok(d, &ds[..i]) {
            return Some(error("BAD_DOCTORS", Some(i)));
        }
    }
    None
}
fn doctor_name_ok(d: &Doctor, prior: &[Doctor]) -> bool {
    name_ok(&d.name) && !prior.iter().any(|p| eq_name(&p.name, &d.name))
}
fn name_ok(s: &str) -> bool {
    !s.is_empty()
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b' ' || b == b'-')
}
fn eq_name(a: &str, b: &str) -> bool {
    a.eq_ignore_ascii_case(b)
}
fn windows(ds: &[Doctor]) -> Option<ClinicError> {
    for (i, d) in ds.iter().enumerate() {
        if d.windows.len() > 8 || d.windows.iter().any(|w| !window_ok(w)) {
            return Some(error("BAD_WINDOW", Some(i)));
        }
    }
    None
}
fn window_ok(w: &Window) -> bool {
    (0..=6).contains(&w.weekday)
        && (0..=1440).contains(&w.open)
        && (0..=1440).contains(&w.close)
        && w.open < w.close
}
fn holidays(hs: &[i64]) -> Option<ClinicError> {
    if hs.len() > 60 {
        return Some(error("BAD_HOLIDAY", None));
    }
    duplicate_holiday(hs)
}
fn duplicate_holiday(hs: &[i64]) -> Option<ClinicError> {
    for (i, day) in hs.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || hs[..i].contains(day) {
            return Some(error("BAD_HOLIDAY", Some(i)));
        }
    }
    None
}
fn bookings(n: &Normalized) -> Option<ClinicError> {
    if n.bookings.len() > 200 {
        return Some(error("BAD_BOOKING", None));
    }
    bad_booking(n)
}
fn bad_booking(n: &Normalized) -> Option<ClinicError> {
    for (i, b) in n.bookings.iter().enumerate() {
        if !booking_ok(b, &n.doctors) {
            return Some(error("BAD_BOOKING", Some(i)));
        }
    }
    None
}
fn booking_ok(b: &Booking, ds: &[Doctor]) -> bool {
    booking_time_ok(b) && ds.iter().any(|d| eq_name(&d.name, &b.doctor))
}
fn booking_time_ok(b: &Booking) -> bool {
    (0..=1_000_000).contains(&b.day)
        && (0..=1440).contains(&b.start)
        && b.start < b.end
        && b.end <= 1440
}
fn preference(n: &Normalized) -> Option<ClinicError> {
    if n.preferred.is_empty() || preferred_found(n) {
        None
    } else {
        Some(error("UNKNOWN_DOCTOR", None))
    }
}
fn preferred_found(n: &Normalized) -> bool {
    n.doctors
        .iter()
        .any(|d| d.name.eq_ignore_ascii_case(&n.preferred))
}
fn day_order(r: &Request) -> Option<ClinicError> {
    (!(r.requested_day >= r.now_day && r.requested_day - r.now_day <= 8))
        .then(|| error("BAD_DAY_ORDER", None))
}
fn finish(slot: Option<Slot>) -> Outcome {
    slot.map_or_else(
        || Outcome::Error(error("NO_SLOT", None)),
        |s| Outcome::Appointment(assemble(s)),
    )
}
fn kind(k: &str) -> (i64, i64) {
    match k {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    }
}
fn first_slot(r: &Request, n: &Normalized, d: i64, b: i64) -> Option<Slot> {
    let end = (r.requested_day + r.horizon_days)
        .min(r.requested_day + 14)
        .min(1_000_000);
    (r.requested_day..=end)
        .flat_map(|day| day_slots(r, n, day, d, b))
        .min()
}
fn day_slots(r: &Request, n: &Normalized, day: i64, d: i64, b: i64) -> Vec<Slot> {
    if r.holidays.contains(&day) {
        return Vec::new();
    }
    n.doctors
        .iter()
        .flat_map(|doc| doc_slots(r, n, doc, day, d, b))
        .collect()
}
fn doc_slots(r: &Request, n: &Normalized, doc: &Doctor, day: i64, d: i64, b: i64) -> Vec<Slot> {
    if !eligible(r, n, doc) {
        return Vec::new();
    }
    starts()
        .filter_map(|start| make_slot(r, n, doc, (day, start, d, b)))
        .collect()
}
fn eligible(r: &Request, n: &Normalized, d: &Doctor) -> bool {
    r.urgent || n.preferred.is_empty() || d.name.eq_ignore_ascii_case(&n.preferred)
}
fn starts() -> impl Iterator<Item = i64> {
    (0..1440).filter(|v| v % 5 == 0)
}
fn make_slot(r: &Request, n: &Normalized, d: &Doctor, p: (i64, i64, i64, i64)) -> Option<Slot> {
    let (day, start, len, buf) = p;
    cand(r, n, d, day, start, start + len + buf).then(|| slot(day, start, len, d))
}
fn slot(day: i64, start: i64, len: i64, d: &Doctor) -> Slot {
    Slot {
        order: (day, start, lower(&d.name)),
        day,
        start,
        end: start + len,
        doctor: d.name.clone(),
    }
}
fn cand(r: &Request, n: &Normalized, d: &Doctor, day: i64, start: i64, end: i64) -> bool {
    opening_ok(day % 7, start, end)
        && doctor_window(d, day % 7, start, end)
        && notice(r, day, start)
        && available(n, d, day, start, end)
}
fn opening_ok(w: i64, s: i64, e: i64) -> bool {
    let (a, b) = if w < 5 {
        (540, 1020)
    } else if w == 5 {
        (600, 840)
    } else {
        (0, 0)
    };
    a <= s && e <= b && !(s < 780 && e > 720)
}
fn doctor_window(d: &Doctor, w: i64, s: i64, e: i64) -> bool {
    d.windows
        .iter()
        .any(|x| x.weekday == w && x.open <= s && e <= x.close)
}
fn notice(r: &Request, day: i64, start: i64) -> bool {
    day > r.now_day || start as i128 >= r.now_minute as i128 + 60
}
fn available(n: &Normalized, d: &Doctor, day: i64, s: i64, e: i64) -> bool {
    let rows = matching_bookings(n, d, day);
    rows.len() < 4 && rows.iter().all(|b| s >= b.end || e <= b.start)
}
fn matching_bookings<'a>(n: &'a Normalized, d: &Doctor, day: i64) -> Vec<&'a Booking> {
    n.bookings
        .iter()
        .filter(|b| b.day == day && b.doctor.eq_ignore_ascii_case(&d.name))
        .collect()
}
fn assemble(s: Slot) -> Appointment {
    Appointment {
        day: s.day,
        start: s.start,
        end: s.end,
        doctor: s.doctor,
        trace: trace(),
    }
}
fn trace() -> Vec<String> {
    TRACE.iter().map(|s| s.to_string()).collect()
}
const TRACE: [&str; 10] = [
    "normalised",
    "validated",
    "holiday-filter",
    "hours-and-lunch",
    "notice",
    "doctor-availability",
    "daily-cap",
    "booking-conflicts",
    "urgent-priority",
    "earliest-grid-slot",
];
