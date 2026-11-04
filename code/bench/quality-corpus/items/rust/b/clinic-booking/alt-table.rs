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
fn issue(code: &str, index: Option<usize>) -> ClinicError {
    ClinicError {
        code: code.into(),
        index,
    }
}
fn good_name(s: &str) -> bool {
    !s.is_empty()
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b' ' || b == b'-')
}
fn appointment(day: i64, start: i64, duration: i64, doctor: String) -> Outcome {
    Outcome::Appointment(Appointment {
        day,
        start,
        end: start + duration,
        doctor,
        trace: TRACE.iter().map(|s| s.to_string()).collect(),
    })
}
#[derive(Clone, Copy)]
struct KindRule {
    name: &'static str,
    duration: i64,
    buffer: i64,
}
const KINDS: [KindRule; 3] = [
    KindRule {
        name: "checkup",
        duration: 20,
        buffer: 5,
    },
    KindRule {
        name: "consultation",
        duration: 30,
        buffer: 10,
    },
    KindRule {
        name: "procedure",
        duration: 60,
        buffer: 15,
    },
];
#[derive(Clone, Copy)]
struct RangeRule {
    value: fn(&Request) -> i64,
    low: i64,
    high: i64,
}
const OPENINGS: [(i64, i64); 7] = [
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (600, 840),
    (0, 0),
];
const REQUEST_RANGES: [RangeRule; 4] = [
    RangeRule {
        value: |r| r.now_day,
        low: 0,
        high: 1_000_000,
    },
    RangeRule {
        value: |r| r.now_minute,
        low: 0,
        high: 1439,
    },
    RangeRule {
        value: |r| r.requested_day,
        low: 0,
        high: 1_000_000,
    },
    RangeRule {
        value: |r| r.horizon_days,
        low: 0,
        high: 14,
    },
];
fn kind(r: &Request) -> Option<KindRule> {
    let name = r.kind.trim_matches(' ').to_ascii_lowercase();
    KINDS.iter().find(|rule| rule.name == name).copied()
}
fn validate(request: &Request) -> Option<ClinicError> {
    let checks: [fn(&Request) -> Option<ClinicError>; 6] = [
        check_scalars,
        check_doctors,
        check_windows,
        check_holidays,
        check_bookings,
        check_preference,
    ];
    checks.iter().find_map(|check| check(request))
}
fn check_scalars(r: &Request) -> Option<ClinicError> {
    let in_range = REQUEST_RANGES
        .iter()
        .all(|rule| (rule.low..=rule.high).contains(&(rule.value)(r)));
    (!in_range).then(|| issue("BAD_REQUEST", None))
}
fn check_doctors(r: &Request) -> Option<ClinicError> {
    if !(1..=12).contains(&r.doctors.len()) {
        return Some(issue("BAD_DOCTORS", None));
    }
    r.doctors
        .iter()
        .enumerate()
        .find(|(i, doctor)| {
            let name = doctor.name.trim_matches(' ');
            !good_name(name)
                || r.doctors[..*i]
                    .iter()
                    .any(|prior| prior.name.trim_matches(' ').eq_ignore_ascii_case(name))
        })
        .map(|(index, _)| issue("BAD_DOCTORS", Some(index)))
}
fn check_windows(r: &Request) -> Option<ClinicError> {
    r.doctors
        .iter()
        .enumerate()
        .find(|(_, doctor)| {
            doctor.windows.len() > 8
                || doctor.windows.iter().any(|window| {
                    !(0..=6).contains(&window.weekday)
                        || window.open < 0
                        || window.open >= window.close
                        || window.close > 1440
                })
        })
        .map(|(index, _)| issue("BAD_WINDOW", Some(index)))
}
fn check_holidays(r: &Request) -> Option<ClinicError> {
    if r.holidays.len() > 60 {
        return Some(issue("BAD_HOLIDAY", None));
    }
    r.holidays
        .iter()
        .enumerate()
        .find(|(index, day)| !(0..=1_000_000).contains(*day) || r.holidays[..*index].contains(*day))
        .map(|(index, _)| issue("BAD_HOLIDAY", Some(index)))
}
fn check_bookings(r: &Request) -> Option<ClinicError> {
    if r.bookings.len() > 200 {
        return Some(issue("BAD_BOOKING", None));
    }
    r.bookings
        .iter()
        .enumerate()
        .find(|(_, booking)| !valid_booking(r, booking))
        .map(|(index, _)| issue("BAD_BOOKING", Some(index)))
}
fn valid_booking(r: &Request, b: &Booking) -> bool {
    (0..=1_000_000).contains(&b.day)
        && b.start >= 0
        && b.start < b.end
        && b.end <= 1440
        && r.doctors.iter().any(|d| {
            d.name
                .trim_matches(' ')
                .eq_ignore_ascii_case(b.doctor.trim_matches(' '))
        })
}
fn check_preference(r: &Request) -> Option<ClinicError> {
    let preferred = r.preferred_doctor.trim_matches(' ');
    if !preferred.is_empty()
        && !r.doctors.iter().any(|doctor| {
            doctor
                .name
                .trim_matches(' ')
                .eq_ignore_ascii_case(preferred)
        })
    {
        return Some(issue("UNKNOWN_DOCTOR", None));
    }
    (r.requested_day < r.now_day || r.requested_day as i128 > r.now_day as i128 + 8)
        .then(|| issue("BAD_DAY_ORDER", None))
}
fn slot_is_clear(r: &Request, d: &Doctor, day: i64, start: i64, end: i64) -> bool {
    let same: Vec<&Booking> = r
        .bookings
        .iter()
        .filter(|b| {
            b.day == day
                && b.doctor
                    .trim_matches(' ')
                    .eq_ignore_ascii_case(d.name.trim_matches(' '))
        })
        .collect();
    same.len() < 4 && same.iter().all(|b| start >= b.end || end <= b.start)
}
fn slot_fits(r: &Request, d: &Doctor, day: i64, start: i64, duration: i64, buffer: i64) -> bool {
    let weekday = day % 7;
    let end = start + duration + buffer;
    let (open, close) = OPENINGS[weekday as usize];
    open <= start
        && end <= close
        && !(start < 780 && end > 720)
        && d.windows
            .iter()
            .any(|w| w.weekday == weekday && w.open <= start && end <= w.close)
        && (day > r.now_day || start as i128 >= r.now_minute as i128 + 60)
}
fn last_day(r: &Request) -> i64 {
    (r.requested_day + r.horizon_days)
        .min(r.requested_day + 14)
        .min(1_000_000)
}
fn ordered_doctors(r: &Request) -> Vec<&Doctor> {
    let mut doctors: Vec<&Doctor> = r.doctors.iter().collect();
    doctors.sort_by_key(|d| d.name.trim_matches(' ').to_ascii_lowercase());
    doctors
}
fn doctor_allowed(r: &Request, d: &Doctor, preferred: &str) -> bool {
    r.urgent || preferred.is_empty() || d.name.trim_matches(' ').eq_ignore_ascii_case(preferred)
}
fn search_day(r: &Request, rule: KindRule, day: i64) -> Option<(i64, i64, String)> {
    if r.holidays.contains(&day) {
        return None;
    }
    let preferred = r.preferred_doctor.trim_matches(' ').to_ascii_lowercase();
    best_slot(r, rule, day, &preferred, ordered_doctors(r))
}
fn best_slot(
    r: &Request,
    rule: KindRule,
    day: i64,
    preferred: &str,
    doctors: Vec<&Doctor>,
) -> Option<(i64, i64, String)> {
    (0..288).map(|n| n * 5).find_map(|start| {
        doctors
            .iter()
            .find(|d| {
                doctor_allowed(r, d, preferred)
                    && slot_fits(r, d, day, start, rule.duration, rule.buffer)
                    && slot_is_clear(r, d, day, start, start + rule.duration + rule.buffer)
            })
            .map(|d| (day, start, d.name.trim_matches(' ').into()))
    })
}
pub fn solution(request: &Request) -> Outcome {
    let Some(rule) = kind(request) else {
        return Outcome::Error(issue("BAD_REQUEST", None));
    };
    if let Some(error) = validate(request) {
        return Outcome::Error(error);
    }
    match (request.requested_day..=last_day(request)).find_map(|day| search_day(request, rule, day))
    {
        Some((day, start, name)) => appointment(day, start, rule.duration, name),
        None => Outcome::Error(issue("NO_SLOT", None)),
    }
}
