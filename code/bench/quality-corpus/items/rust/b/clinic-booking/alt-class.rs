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
const OPENINGS: [(i64, i64); 7] = [
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (600, 840),
    (0, 0),
];
struct Scheduler<'a> {
    request: &'a Request,
    preferred: String,
    duration: i64,
    buffer: i64,
    last_day: i64,
}
fn kind_times(r: &Request) -> Option<(i64, i64)> {
    match r.kind.trim_matches(' ').to_ascii_lowercase().as_str() {
        "checkup" => Some((20, 5)),
        "consultation" => Some((30, 10)),
        "procedure" => Some((60, 15)),
        _ => None,
    }
}
fn ordered_doctors(r: &Request) -> Vec<&Doctor> {
    let mut doctors: Vec<&Doctor> = r.doctors.iter().collect();
    doctors.sort_by_key(|d| d.name.trim_matches(' ').to_ascii_lowercase());
    doctors
}
fn validate_request(r: &Request) -> Option<ClinicError> {
    validate_scalar_fields(r)
        .or_else(|| validate_doctor_rows(r))
        .or_else(|| validate_window_rows(r))
        .or_else(|| validate_holiday_rows(r))
        .or_else(|| validate_booking_rows(r))
        .or_else(|| validate_request_links(r))
}
fn validate_scalar_fields(r: &Request) -> Option<ClinicError> {
    let valid = (0..=1_000_000).contains(&r.now_day)
        && (0..=1439).contains(&r.now_minute)
        && (0..=1_000_000).contains(&r.requested_day)
        && (0..=14).contains(&r.horizon_days);
    if valid {
        None
    } else {
        Some(issue("BAD_REQUEST", None))
    }
}
fn validate_doctor_rows(r: &Request) -> Option<ClinicError> {
    if !(1..=12).contains(&r.doctors.len()) {
        return Some(issue("BAD_DOCTORS", None));
    }
    r.doctors
        .iter()
        .enumerate()
        .find(|(i, d)| {
            let name = d.name.trim_matches(' ');
            !good_name(name)
                || r.doctors[..*i]
                    .iter()
                    .any(|prior| prior.name.trim_matches(' ').eq_ignore_ascii_case(name))
        })
        .map(|(i, _)| issue("BAD_DOCTORS", Some(i)))
}
fn validate_window_rows(r: &Request) -> Option<ClinicError> {
    r.doctors
        .iter()
        .enumerate()
        .find(|(_, d)| {
            d.windows.len() > 8
                || d.windows.iter().any(|w| {
                    !(0..=6).contains(&w.weekday)
                        || w.open < 0
                        || w.open >= w.close
                        || w.close > 1440
                })
        })
        .map(|(i, _)| issue("BAD_WINDOW", Some(i)))
}
fn validate_holiday_rows(r: &Request) -> Option<ClinicError> {
    if r.holidays.len() > 60 {
        return Some(issue("BAD_HOLIDAY", None));
    }
    r.holidays
        .iter()
        .enumerate()
        .find(|(i, day)| !(0..=1_000_000).contains(*day) || r.holidays[..*i].contains(*day))
        .map(|(i, _)| issue("BAD_HOLIDAY", Some(i)))
}
fn validate_booking_rows(r: &Request) -> Option<ClinicError> {
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
fn validate_request_links(r: &Request) -> Option<ClinicError> {
    let preferred = r.preferred_doctor.trim_matches(' ');
    if !preferred.is_empty()
        && !r
            .doctors
            .iter()
            .any(|d| d.name.trim_matches(' ').eq_ignore_ascii_case(preferred))
    {
        return Some(issue("UNKNOWN_DOCTOR", None));
    }
    if r.requested_day < r.now_day || r.requested_day as i128 > r.now_day as i128 + 8 {
        return Some(issue("BAD_DAY_ORDER", None));
    }
    None
}

impl<'a> Scheduler<'a> {
    fn new(request: &'a Request, (duration, buffer): (i64, i64)) -> Self {
        let preferred = request
            .preferred_doctor
            .trim_matches(' ')
            .to_ascii_lowercase();
        let last_day = (request.requested_day + request.horizon_days)
            .min(request.requested_day + 14)
            .min(1_000_000);
        Self {
            request,
            preferred,
            duration,
            buffer,
            last_day,
        }
    }

    fn time_open(&self, d: &Doctor, day: i64, start: i64) -> bool {
        let weekday = day % 7;
        let end = start + self.duration + self.buffer;
        let (open, close) = OPENINGS[weekday as usize];
        open <= start
            && end <= close
            && !(start < 780 && end > 720)
            && (day > self.request.now_day || start as i128 >= self.request.now_minute as i128 + 60)
            && d.windows
                .iter()
                .any(|w| w.weekday == weekday && w.open <= start && end <= w.close)
    }
    fn room_left(&self, d: &Doctor, day: i64, start: i64) -> bool {
        let end = start + self.duration + self.buffer;
        let same: Vec<&Booking> = self
            .request
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
    fn doctor_allowed(&self, doctor: &Doctor) -> bool {
        self.request.urgent
            || self.preferred.is_empty()
            || doctor
                .name
                .trim_matches(' ')
                .eq_ignore_ascii_case(&self.preferred)
    }
    fn on_day(&self, day: i64) -> Option<(i64, String)> {
        if self.request.holidays.contains(&day) {
            return None;
        }
        let doctors = ordered_doctors(self.request);
        (0..288).map(|i| i * 5).find_map(|start| {
            doctors
                .iter()
                .find(|doctor| {
                    self.doctor_allowed(doctor)
                        && self.time_open(doctor, day, start)
                        && self.room_left(doctor, day, start)
                })
                .map(|doctor| (start, doctor.name.trim_matches(' ').into()))
        })
    }

    fn first_appointment(&self) -> Option<(i64, i64, String)> {
        (self.request.requested_day..=self.last_day)
            .find_map(|day| self.on_day(day).map(|(start, name)| (day, start, name)))
    }
}
pub fn solution(request: &Request) -> Outcome {
    let Some(times) = kind_times(request) else {
        return Outcome::Error(issue("BAD_REQUEST", None));
    };
    if let Some(error) = validate_request(request) {
        return Outcome::Error(error);
    }
    let scheduler = Scheduler::new(request, times);
    match scheduler.first_appointment() {
        Some((day, start, name)) => appointment(day, start, scheduler.duration, name),
        None => Outcome::Error(issue("NO_SLOT", None)),
    }
}
