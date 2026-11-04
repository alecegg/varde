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
#[derive(Clone)]
struct Candidate {
    day: i64,
    start: i64,
    doctor: String,
    duration: i64,
}
fn kind_spec(name: &str) -> (i64, i64) {
    match name {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    }
}
fn validate(r: &Request) -> Result<(), ClinicError> {
    validate_scalars(r)?;
    validate_doctors(r)?;
    validate_windows(r)?;
    validate_holidays(r)?;
    validate_bookings(r)?;
    validate_preference(r)
}
fn validate_scalars(r: &Request) -> Result<(), ClinicError> {
    let valid = (0..=1_000_000).contains(&r.now_day)
        && (0..=1439).contains(&r.now_minute)
        && (0..=1_000_000).contains(&r.requested_day)
        && (0..=14).contains(&r.horizon_days)
        && ["checkup", "consultation", "procedure"]
            .contains(&r.kind.trim_matches(' ').to_ascii_lowercase().as_str());
    if valid {
        Ok(())
    } else {
        Err(issue("BAD_REQUEST", None))
    }
}
fn validate_doctors(r: &Request) -> Result<(), ClinicError> {
    if !(1..=12).contains(&r.doctors.len()) {
        return Err(issue("BAD_DOCTORS", None));
    }
    for (index, doctor) in r.doctors.iter().enumerate() {
        let name = doctor.name.trim_matches(' ');
        if !good_name(name)
            || r.doctors[..index]
                .iter()
                .any(|prior| prior.name.trim_matches(' ').eq_ignore_ascii_case(name))
        {
            return Err(issue("BAD_DOCTORS", Some(index)));
        }
    }
    Ok(())
}
fn validate_windows(r: &Request) -> Result<(), ClinicError> {
    for (index, doctor) in r.doctors.iter().enumerate() {
        if doctor.windows.len() > 8
            || doctor.windows.iter().any(|w| {
                !(0..=6).contains(&w.weekday) || w.open < 0 || w.open >= w.close || w.close > 1440
            })
        {
            return Err(issue("BAD_WINDOW", Some(index)));
        }
    }
    Ok(())
}
fn validate_holidays(r: &Request) -> Result<(), ClinicError> {
    if r.holidays.len() > 60 {
        return Err(issue("BAD_HOLIDAY", None));
    }
    for (index, day) in r.holidays.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || r.holidays[..index].contains(day) {
            return Err(issue("BAD_HOLIDAY", Some(index)));
        }
    }
    Ok(())
}
fn validate_bookings(r: &Request) -> Result<(), ClinicError> {
    if r.bookings.len() > 200 {
        return Err(issue("BAD_BOOKING", None));
    }
    for (index, booking) in r.bookings.iter().enumerate() {
        if !valid_booking(r, booking) {
            return Err(issue("BAD_BOOKING", Some(index)));
        }
    }
    Ok(())
}
fn valid_booking(r: &Request, booking: &Booking) -> bool {
    let valid_time = (0..=1_000_000).contains(&booking.day)
        && booking.start >= 0
        && booking.start < booking.end
        && booking.end <= 1440;
    valid_time
        && r.doctors.iter().any(|doctor| {
            doctor
                .name
                .trim_matches(' ')
                .eq_ignore_ascii_case(booking.doctor.trim_matches(' '))
        })
}
fn validate_preference(r: &Request) -> Result<(), ClinicError> {
    let preferred = r.preferred_doctor.trim_matches(' ');
    if !preferred.is_empty()
        && !r.doctors.iter().any(|doctor| {
            doctor
                .name
                .trim_matches(' ')
                .eq_ignore_ascii_case(preferred)
        })
    {
        return Err(issue("UNKNOWN_DOCTOR", None));
    }
    if r.requested_day < r.now_day || r.requested_day as i128 > r.now_day as i128 + 8 {
        return Err(issue("BAD_DAY_ORDER", None));
    }
    Ok(())
}
fn clinic_time(r: &Request, day: i64, start: i64, end: i64) -> bool {
    let weekday = day % 7;
    let (opens, closes) = match weekday {
        0..=4 => (540, 1020),
        5 => (600, 840),
        _ => (0, 0),
    };
    opens <= start
        && end <= closes
        && !(start < 780 && end > 720)
        && (day > r.now_day || start as i128 >= r.now_minute as i128 + 60)
}
fn doctor_window(doctor: &Doctor, day: i64, start: i64, end: i64) -> bool {
    doctor
        .windows
        .iter()
        .any(|w| w.weekday == day % 7 && w.open <= start && end <= w.close)
}
fn bookings_clear(r: &Request, doctor: &Doctor, day: i64, start: i64, end: i64) -> bool {
    let same: Vec<&Booking> = r
        .bookings
        .iter()
        .filter(|b| {
            b.day == day
                && b.doctor
                    .trim_matches(' ')
                    .eq_ignore_ascii_case(doctor.name.trim_matches(' '))
        })
        .collect();
    same.len() < 4 && same.iter().all(|b| start >= b.end || end <= b.start)
}
fn candidate(day: i64, start: i64, doctor: &Doctor, duration: i64) -> Candidate {
    Candidate {
        day,
        start,
        doctor: doctor.name.trim_matches(' ').into(),
        duration,
    }
}
fn candidates(r: &Request) -> impl Iterator<Item = Candidate> + '_ {
    let (duration, buffer) = kind_spec(&r.kind.trim_matches(' ').to_ascii_lowercase());
    let last = (r.requested_day + r.horizon_days)
        .min(r.requested_day + 14)
        .min(1_000_000);
    (r.requested_day..=last)
        .filter(|day| !r.holidays.contains(day))
        .flat_map(move |day| slots_for_day(r, day, duration, buffer))
}
fn preferred_doctor(r: &Request, doctor: &Doctor) -> bool {
    r.urgent
        || r.preferred_doctor.trim_matches(' ').is_empty()
        || doctor
            .name
            .trim_matches(' ')
            .eq_ignore_ascii_case(r.preferred_doctor.trim_matches(' '))
}
fn slots_for_day(
    r: &Request,
    day: i64,
    duration: i64,
    buffer: i64,
) -> impl Iterator<Item = Candidate> + '_ {
    (0..288).flat_map(move |index| {
        let start = index * 5;
        r.doctors
            .iter()
            .filter(move |doctor| preferred_doctor(r, doctor))
            .filter(move |doctor| {
                let end = start + duration + buffer;
                clinic_time(r, day, start, end)
                    && doctor_window(doctor, day, start, end)
                    && bookings_clear(r, doctor, day, start, end)
            })
            .map(move |doctor| candidate(day, start, doctor, duration))
    })
}

pub fn solution(request: &Request) -> Outcome {
    if let Err(error) = validate(request) {
        return Outcome::Error(error);
    }
    let best = candidates(request).min_by(|a, b| {
        (a.day, a.start, a.doctor.to_ascii_lowercase()).cmp(&(
            b.day,
            b.start,
            b.doctor.to_ascii_lowercase(),
        ))
    });
    match best {
        Some(c) => appointment(c.day, c.start, c.duration, c.doctor),
        None => Outcome::Error(issue("NO_SLOT", None)),
    }
}
