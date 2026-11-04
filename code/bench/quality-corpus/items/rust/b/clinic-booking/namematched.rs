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
    let n = normalize(request);
    let size = kind_size(&n.kind);
    if let Some(e) = validate(request, &n) {
        return Outcome::Error(e);
    }
    make_outcome(find_slot(request, &n, size.0, size.1))
}
fn normalize(r: &Request) -> Normalized {
    Normalized {
        kind: lower_ascii(r.kind.trim_matches(' ')),
        preferred: lower_ascii(r.preferred_doctor.trim_matches(' ')),
        doctors: normalize_doctors(&r.doctors),
        bookings: normalize_bookings(&r.bookings),
    }
}
fn lower_ascii(s: &str) -> String {
    s.to_ascii_lowercase()
}
fn normalize_doctors(ds: &[Doctor]) -> Vec<Doctor> {
    ds.iter().map(normalize_doctor).collect()
}
fn normalize_doctor(d: &Doctor) -> Doctor {
    Doctor {
        name: d.name.trim_matches(' ').to_string(),
        windows: d.windows.clone(),
    }
}
fn normalize_bookings(bs: &[Booking]) -> Vec<Booking> {
    bs.iter().map(normalize_booking).collect()
}
fn normalize_booking(b: &Booking) -> Booking {
    Booking {
        day: b.day,
        start: b.start,
        end: b.end,
        doctor: lower_ascii(b.doctor.trim_matches(' ')),
    }
}
fn validate(r: &Request, n: &Normalized) -> Option<ClinicError> {
    validate_basics(r, n).or_else(|| validate_lists(r, n))
}
fn validate_basics(r: &Request, n: &Normalized) -> Option<ClinicError> {
    check_scalars(r, n)
        .or_else(|| check_doctors(&n.doctors))
        .or_else(|| check_windows(&n.doctors))
        .or_else(|| check_holidays(&r.holidays))
}
fn validate_lists(r: &Request, n: &Normalized) -> Option<ClinicError> {
    check_bookings(n)
        .or_else(|| preference_error(n))
        .or_else(|| check_day_order(r))
}
fn clinic_error(code: &str, index: Option<usize>) -> ClinicError {
    ClinicError {
        code: code.to_string(),
        index,
    }
}
fn check_scalars(r: &Request, n: &Normalized) -> Option<ClinicError> {
    let valid = valid_days(r) && valid_clock(r) && valid_kind(&n.kind);
    (!valid).then(|| clinic_error("BAD_REQUEST", None))
}
fn valid_days(r: &Request) -> bool {
    (0..=1_000_000).contains(&r.now_day) && (0..=1_000_000).contains(&r.requested_day)
}
fn valid_clock(r: &Request) -> bool {
    (0..=1439).contains(&r.now_minute) && (0..=14).contains(&r.horizon_days)
}
fn valid_kind(k: &str) -> bool {
    ["checkup", "consultation", "procedure"].contains(&k)
}
fn check_doctors(ds: &[Doctor]) -> Option<ClinicError> {
    if !(1..=12).contains(&ds.len()) {
        return Some(clinic_error("BAD_DOCTORS", None));
    }
    unique_doctors(ds)
}
fn unique_doctors(ds: &[Doctor]) -> Option<ClinicError> {
    for (i, d) in ds.iter().enumerate() {
        if !valid_doctor(d, &ds[..i]) {
            return Some(clinic_error("BAD_DOCTORS", Some(i)));
        }
    }
    None
}
fn valid_doctor(d: &Doctor, prior: &[Doctor]) -> bool {
    valid_name(&d.name) && !prior.iter().any(|p| same_name(&p.name, &d.name))
}
fn valid_name(s: &str) -> bool {
    !s.is_empty()
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b' ' || b == b'-')
}
fn same_name(a: &str, b: &str) -> bool {
    a.eq_ignore_ascii_case(b)
}
fn check_windows(ds: &[Doctor]) -> Option<ClinicError> {
    for (i, d) in ds.iter().enumerate() {
        if d.windows.len() > 8 || d.windows.iter().any(|w| !valid_window(w)) {
            return Some(clinic_error("BAD_WINDOW", Some(i)));
        }
    }
    None
}
fn valid_window(w: &Window) -> bool {
    (0..=6).contains(&w.weekday)
        && (0..=1440).contains(&w.open)
        && (0..=1440).contains(&w.close)
        && w.open < w.close
}
fn check_holidays(hs: &[i64]) -> Option<ClinicError> {
    if hs.len() > 60 {
        return Some(clinic_error("BAD_HOLIDAY", None));
    }
    unique_holidays(hs)
}
fn unique_holidays(hs: &[i64]) -> Option<ClinicError> {
    for (i, day) in hs.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || hs[..i].contains(day) {
            return Some(clinic_error("BAD_HOLIDAY", Some(i)));
        }
    }
    None
}
fn check_bookings(n: &Normalized) -> Option<ClinicError> {
    if n.bookings.len() > 200 {
        return Some(clinic_error("BAD_BOOKING", None));
    }
    valid_bookings(n)
}
fn valid_bookings(n: &Normalized) -> Option<ClinicError> {
    for (i, b) in n.bookings.iter().enumerate() {
        if !valid_booking(b, &n.doctors) {
            return Some(clinic_error("BAD_BOOKING", Some(i)));
        }
    }
    None
}
fn valid_booking(b: &Booking, ds: &[Doctor]) -> bool {
    valid_booking_time(b) && ds.iter().any(|d| same_name(&d.name, &b.doctor))
}
fn valid_booking_time(b: &Booking) -> bool {
    (0..=1_000_000).contains(&b.day)
        && (0..=1440).contains(&b.start)
        && b.start < b.end
        && b.end <= 1440
}
fn preference_error(n: &Normalized) -> Option<ClinicError> {
    if n.preferred.is_empty() || preferred_doctor_found(n) {
        None
    } else {
        Some(clinic_error("UNKNOWN_DOCTOR", None))
    }
}
fn preferred_doctor_found(n: &Normalized) -> bool {
    n.doctors
        .iter()
        .any(|d| d.name.eq_ignore_ascii_case(&n.preferred))
}
fn check_day_order(r: &Request) -> Option<ClinicError> {
    (!(r.requested_day >= r.now_day && r.requested_day - r.now_day <= 8))
        .then(|| clinic_error("BAD_DAY_ORDER", None))
}
fn make_outcome(slot: Option<Slot>) -> Outcome {
    slot.map_or_else(
        || Outcome::Error(clinic_error("NO_SLOT", None)),
        |s| Outcome::Appointment(appointment(s)),
    )
}
fn kind_size(k: &str) -> (i64, i64) {
    match k {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    }
}
fn find_slot(r: &Request, n: &Normalized, d: i64, b: i64) -> Option<Slot> {
    let end = (r.requested_day + r.horizon_days)
        .min(r.requested_day + 14)
        .min(1_000_000);
    (r.requested_day..=end)
        .flat_map(|day| slots_for_day(r, n, day, d, b))
        .min()
}
fn slots_for_day(r: &Request, n: &Normalized, day: i64, d: i64, b: i64) -> Vec<Slot> {
    if r.holidays.contains(&day) {
        return Vec::new();
    }
    n.doctors
        .iter()
        .flat_map(|doc| doctor_slots(r, n, doc, day, d, b))
        .collect()
}
fn doctor_slots(r: &Request, n: &Normalized, doc: &Doctor, day: i64, d: i64, b: i64) -> Vec<Slot> {
    if !eligible_doctor(r, n, doc) {
        return Vec::new();
    }
    grid_starts()
        .filter_map(|start| make_candidate(r, n, doc, (day, start, d, b)))
        .collect()
}
fn eligible_doctor(r: &Request, n: &Normalized, d: &Doctor) -> bool {
    r.urgent || n.preferred.is_empty() || d.name.eq_ignore_ascii_case(&n.preferred)
}
fn grid_starts() -> impl Iterator<Item = i64> {
    (0..1440).filter(|v| v % 5 == 0)
}
fn make_candidate(
    r: &Request,
    n: &Normalized,
    d: &Doctor,
    p: (i64, i64, i64, i64),
) -> Option<Slot> {
    let (day, start, len, buf) = p;
    candidate(r, n, d, day, start, start + len + buf).then(|| make_slot_record(day, start, len, d))
}
fn make_slot_record(day: i64, start: i64, len: i64, d: &Doctor) -> Slot {
    Slot {
        order: (day, start, lower_ascii(&d.name)),
        day,
        start,
        end: start + len,
        doctor: d.name.clone(),
    }
}
fn candidate(r: &Request, n: &Normalized, d: &Doctor, day: i64, start: i64, end: i64) -> bool {
    within_opening(day % 7, start, end)
        && matches_window(d, day % 7, start, end)
        && meets_notice(r, day, start)
        && schedule_clear(n, d, day, start, end)
}
fn within_opening(w: i64, s: i64, e: i64) -> bool {
    let (a, b) = if w < 5 {
        (540, 1020)
    } else if w == 5 {
        (600, 840)
    } else {
        (0, 0)
    };
    a <= s && e <= b && !(s < 780 && e > 720)
}
fn matches_window(d: &Doctor, w: i64, s: i64, e: i64) -> bool {
    d.windows
        .iter()
        .any(|x| x.weekday == w && x.open <= s && e <= x.close)
}
fn meets_notice(r: &Request, day: i64, start: i64) -> bool {
    day > r.now_day || start as i128 >= r.now_minute as i128 + 60
}
fn schedule_clear(n: &Normalized, d: &Doctor, day: i64, s: i64, e: i64) -> bool {
    let rows = bookings_for_day(n, d, day);
    rows.len() < 4 && rows.iter().all(|b| s >= b.end || e <= b.start)
}
fn bookings_for_day<'a>(n: &'a Normalized, d: &Doctor, day: i64) -> Vec<&'a Booking> {
    n.bookings
        .iter()
        .filter(|b| b.day == day && b.doctor.eq_ignore_ascii_case(&d.name))
        .collect()
}
fn appointment(s: Slot) -> Appointment {
    Appointment {
        day: s.day,
        start: s.start,
        end: s.end,
        doctor: s.doctor,
        trace: trace_for(),
    }
}
fn trace_for() -> Vec<String> {
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
