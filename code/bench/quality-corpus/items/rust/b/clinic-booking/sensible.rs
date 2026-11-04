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

#[derive(Clone)]
struct Slot {
    day: i64,
    start: i64,
    end: i64,
    doctor: String,
}

const OPENING: [(i64, i64); 7] = [
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (540, 1020),
    (600, 840),
    (0, 0),
];

macro_rules! clinic_error {
    ($code:expr, $index:expr) => {
        ClinicError {
            code: $code.to_string(),
            index: $index,
        }
    };
}

/// Return the earliest valid appointment or the first validation error.
pub fn solution(request: &Request) -> Outcome {
    let data = normalize(request);
    if let Some(error) = validate(request, &data) {
        return Outcome::Error(error);
    }
    let (duration, buffer) = match data.kind.as_str() {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    };
    match find_slot(request, &data, duration, buffer) {
        Some(slot) => Outcome::Appointment(appointment(slot)),
        None => Outcome::Error(clinic_error!("NO_SLOT", None)),
    }
}

fn normalize(request: &Request) -> Normalized {
    Normalized {
        kind: request.kind.trim_matches(' ').to_ascii_lowercase(),
        preferred: request
            .preferred_doctor
            .trim_matches(' ')
            .to_ascii_lowercase(),
        doctors: request
            .doctors
            .iter()
            .map(|doctor| Doctor {
                name: doctor.name.trim_matches(' ').to_string(),
                windows: doctor.windows.clone(),
            })
            .collect(),
        bookings: request
            .bookings
            .iter()
            .map(|booking| Booking {
                day: booking.day,
                start: booking.start,
                end: booking.end,
                doctor: booking.doctor.trim_matches(' ').to_ascii_lowercase(),
            })
            .collect(),
    }
}

fn validate(request: &Request, data: &Normalized) -> Option<ClinicError> {
    check_scalars(request, data)
        .or_else(|| check_doctors(&data.doctors))
        .or_else(|| check_windows(&data.doctors))
        .or_else(|| check_holidays(&request.holidays))
        .or_else(|| check_bookings(data))
        .or_else(|| check_preference(request, data))
}

fn check_scalars(request: &Request, data: &Normalized) -> Option<ClinicError> {
    let valid = (0..=1_000_000).contains(&request.now_day)
        && (0..=1_000_000).contains(&request.requested_day)
        && (0..=1439).contains(&request.now_minute)
        && (0..=14).contains(&request.horizon_days)
        && ["checkup", "consultation", "procedure"].contains(&data.kind.as_str());
    (!valid).then(|| clinic_error!("BAD_REQUEST", None))
}

fn check_doctors(doctors: &[Doctor]) -> Option<ClinicError> {
    if !(1..=12).contains(&doctors.len()) {
        return Some(clinic_error!("BAD_DOCTORS", None));
    }
    for (index, doctor) in doctors.iter().enumerate() {
        if !valid_name(&doctor.name)
            || doctors[..index]
                .iter()
                .any(|prior| prior.name.eq_ignore_ascii_case(&doctor.name))
        {
            return Some(clinic_error!("BAD_DOCTORS", Some(index)));
        }
    }
    None
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b' ' || byte == b'-')
}

fn check_windows(doctors: &[Doctor]) -> Option<ClinicError> {
    for (index, doctor) in doctors.iter().enumerate() {
        if doctor.windows.len() > 8
            || doctor.windows.iter().any(|window| {
                !(0..=6).contains(&window.weekday)
                    || window.open < 0
                    || window.open >= window.close
                    || window.close > 1440
            })
        {
            return Some(clinic_error!("BAD_WINDOW", Some(index)));
        }
    }
    None
}

fn check_holidays(holidays: &[i64]) -> Option<ClinicError> {
    if holidays.len() > 60 {
        return Some(clinic_error!("BAD_HOLIDAY", None));
    }
    for (index, day) in holidays.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || holidays[..index].contains(day) {
            return Some(clinic_error!("BAD_HOLIDAY", Some(index)));
        }
    }
    None
}

fn check_bookings(data: &Normalized) -> Option<ClinicError> {
    if data.bookings.len() > 200 {
        return Some(clinic_error!("BAD_BOOKING", None));
    }
    for (index, booking) in data.bookings.iter().enumerate() {
        let valid = (0..=1_000_000).contains(&booking.day)
            && booking.start >= 0
            && booking.start < booking.end
            && booking.end <= 1440
            && data
                .doctors
                .iter()
                .any(|doctor| doctor.name.eq_ignore_ascii_case(&booking.doctor));
        if !valid {
            return Some(clinic_error!("BAD_BOOKING", Some(index)));
        }
    }
    None
}

fn check_preference(request: &Request, data: &Normalized) -> Option<ClinicError> {
    let known = data.preferred.is_empty()
        || data
            .doctors
            .iter()
            .any(|doctor| doctor.name.to_ascii_lowercase() == data.preferred);
    if !known {
        return Some(clinic_error!("UNKNOWN_DOCTOR", None));
    }
    if request.requested_day < request.now_day || request.requested_day - request.now_day > 8 {
        return Some(clinic_error!("BAD_DAY_ORDER", None));
    }
    None
}

fn find_slot(request: &Request, data: &Normalized, duration: i64, buffer: i64) -> Option<Slot> {
    let last = (request.requested_day + request.horizon_days)
        .min(request.requested_day + 14)
        .min(1_000_000);
    let mut doctors: Vec<&Doctor> = data.doctors.iter().collect();
    doctors.sort_by_key(|doctor| doctor.name.to_ascii_lowercase());
    for day in request.requested_day..=last {
        if !request.holidays.contains(&day) {
            if let Some(slot) = day_slots(request, data, &doctors, day, duration, buffer) {
                return Some(slot);
            }
        }
    }
    None
}

fn day_slots(
    request: &Request,
    data: &Normalized,
    doctors: &[&Doctor],
    day: i64,
    duration: i64,
    buffer: i64,
) -> Option<Slot> {
    for start in (0..288).map(|grid_index| grid_index * 5) {
        for doctor in doctors {
            let reserved_end = start + duration + buffer;
            if doctor_is_eligible(request, data, doctor)
                && candidate(request, doctor, day, start, duration, buffer)
                && schedule_clear(data, doctor, day, start, reserved_end)
            {
                return Some(Slot {
                    day,
                    start,
                    end: start + duration,
                    doctor: doctor.name.clone(),
                });
            }
        }
    }
    None
}

fn doctor_is_eligible(request: &Request, data: &Normalized, doctor: &Doctor) -> bool {
    let urgent_booking = request.urgent;
    let preference_is_empty = data.preferred.is_empty();
    let preferred_doctor_matches = doctor.name.eq_ignore_ascii_case(&data.preferred);
    urgent_booking || preference_is_empty || preferred_doctor_matches
}

fn candidate(
    request: &Request,
    doctor: &Doctor,
    day: i64,
    start: i64,
    duration: i64,
    buffer: i64,
) -> bool {
    let reserved_end = start + duration + buffer;
    let weekday = day % 7;
    let (opening, closing) = OPENING[weekday as usize];
    opening <= start
        && reserved_end <= closing
        && !(start < 780 && reserved_end > 720)
        && doctor.windows.iter().any(|window| {
            window.weekday == weekday && window.open <= start && reserved_end <= window.close
        })
        && (day > request.now_day || start as i128 >= request.now_minute as i128 + 60)
}

fn schedule_clear(
    data: &Normalized,
    doctor: &Doctor,
    day: i64,
    start: i64,
    reserved_end: i64,
) -> bool {
    let bookings: Vec<&Booking> = data
        .bookings
        .iter()
        .filter(|booking| booking.day == day && booking.doctor.eq_ignore_ascii_case(&doctor.name))
        .collect();
    bookings.len() < 4
        && bookings
            .iter()
            .all(|booking| start >= booking.end || reserved_end <= booking.start)
}

fn appointment(slot: Slot) -> Appointment {
    Appointment {
        day: slot.day,
        start: slot.start,
        end: slot.end,
        doctor: slot.doctor,
        trace: [
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
        ]
        .iter()
        .map(|part| part.to_string())
        .collect(),
    }
}
