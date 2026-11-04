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
    key: String,
}

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
    let normalized = normalize_request(request);
    if let Some(error) = validate_request(request, &normalized) {
        return Outcome::Error(error);
    }
    let (duration, buffer) = match normalized.kind.as_str() {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    };
    assemble_outcome(find_slot(request, &normalized, duration, buffer))
}

fn normalize_request(request: &Request) -> Normalized {
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

fn validate_request(request: &Request, data: &Normalized) -> Option<ClinicError> {
    check_scalars(request, data)
        .or_else(|| check_doctors(&data.doctors))
        .or_else(|| check_windows(&data.doctors))
        .or_else(|| check_holidays(&request.holidays))
        .or_else(|| check_bookings(data))
        .or_else(|| check_request_links(request, data))
}

fn check_scalars(request: &Request, data: &Normalized) -> Option<ClinicError> {
    let day_bounds_hold = (0..=1_000_000).contains(&request.now_day)
        && (0..=1_000_000).contains(&request.requested_day);
    let minute_is_valid = (0..=1439).contains(&request.now_minute);
    let horizon_is_valid = (0..=14).contains(&request.horizon_days);
    let kind_is_supported = ["checkup", "consultation", "procedure"].contains(&data.kind.as_str());
    if day_bounds_hold && minute_is_valid && horizon_is_valid && kind_is_supported {
        None
    } else {
        Some(clinic_error!("BAD_REQUEST", None))
    }
}

fn check_doctors(doctors: &[Doctor]) -> Option<ClinicError> {
    if !(1..=12).contains(&doctors.len()) {
        return Some(clinic_error!("BAD_DOCTORS", None));
    }
    let mut names_seen = Vec::new();
    for (index, doctor) in doctors.iter().enumerate() {
        let key = doctor.name.to_ascii_lowercase();
        let name_is_valid = valid_name(&doctor.name);
        let duplicate_name = names_seen.contains(&key);
        if !name_is_valid || duplicate_name {
            return Some(clinic_error!("BAD_DOCTORS", Some(index)));
        }
        names_seen.push(key);
    }
    None
}

fn valid_name(name: &str) -> bool {
    let has_text = !name.is_empty();
    let characters_are_valid = name.bytes().all(|byte| {
        let is_alphanumeric = byte.is_ascii_alphanumeric();
        let is_separator = byte == b' ' || byte == b'-';
        is_alphanumeric || is_separator
    });
    has_text && characters_are_valid
}

fn check_windows(doctors: &[Doctor]) -> Option<ClinicError> {
    for (index, doctor) in doctors.iter().enumerate() {
        let too_many_windows = doctor.windows.len() > 8;
        let malformed_window = doctor.windows.iter().any(|window| {
            let weekday_is_valid = (0..=6).contains(&window.weekday);
            let endpoints_are_valid =
                window.open >= 0 && window.open < window.close && window.close <= 1440;
            !weekday_is_valid || !endpoints_are_valid
        });
        if too_many_windows || malformed_window {
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
        let day_is_valid = (0..=1_000_000).contains(day);
        let duplicate_day = holidays[..index].iter().any(|prior| prior == day);
        if !day_is_valid || duplicate_day {
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
        if !(0..=1_000_000).contains(&booking.day)
            || booking.start < 0
            || booking.start >= booking.end
            || booking.end > 1440
            || !data
                .doctors
                .iter()
                .any(|doctor| doctor.name.eq_ignore_ascii_case(&booking.doctor))
        {
            return Some(clinic_error!("BAD_BOOKING", Some(index)));
        }
    }
    None
}

fn check_request_links(request: &Request, data: &Normalized) -> Option<ClinicError> {
    let preference_is_known = data.preferred.is_empty()
        || data
            .doctors
            .iter()
            .any(|doctor| doctor.name.eq_ignore_ascii_case(&data.preferred));
    if !preference_is_known {
        return Some(clinic_error!("UNKNOWN_DOCTOR", None));
    }
    let day_order_is_valid =
        request.requested_day >= request.now_day && request.requested_day - request.now_day <= 8;
    if day_order_is_valid {
        None
    } else {
        Some(clinic_error!("BAD_DAY_ORDER", None))
    }
}

fn find_slot(request: &Request, data: &Normalized, duration: i64, buffer: i64) -> Option<Slot> {
    let last = (request.requested_day + request.horizon_days)
        .min(request.requested_day + 14)
        .min(1_000_000);
    let mut choices = Vec::new();
    for day in request.requested_day..=last {
        if request.holidays.contains(&day) {
            continue;
        }
        choices.extend(slots_for_day(request, data, day, duration, buffer));
    }
    choices.into_iter().min_by(|left, right| {
        (left.day, left.start, &left.key).cmp(&(right.day, right.start, &right.key))
    })
}

fn slots_for_day(
    request: &Request,
    data: &Normalized,
    day: i64,
    duration: i64,
    buffer: i64,
) -> Vec<Slot> {
    let weekday = day % 7;
    let mut slots = Vec::new();
    for doctor in &data.doctors {
        for grid_index in 0..288 {
            let start = grid_index * 5;
            if slot_is_valid(request, data, doctor, day, weekday, start, duration, buffer) {
                slots.push(Slot {
                    day,
                    start,
                    end: start + duration,
                    doctor: doctor.name.clone(),
                    key: doctor.name.to_ascii_lowercase(),
                });
            }
        }
    }
    slots
}

fn slot_is_valid(
    request: &Request,
    data: &Normalized,
    doctor: &Doctor,
    day: i64,
    weekday: i64,
    start: i64,
    duration: i64,
    buffer: i64,
) -> bool {
    let reserved = start + duration + buffer;
    within_clinic_hours(weekday, start, reserved)
        && !(start < 780 && reserved > 720)
        && within_doctor_window(doctor, weekday, start, reserved)
        && (day > request.now_day || start >= request.now_minute + 60)
        && (request.urgent
            || data.preferred.is_empty()
            || doctor.name.eq_ignore_ascii_case(&data.preferred))
        && bookings_are_clear(data, doctor, day, start, reserved)
}

fn within_clinic_hours(weekday: i64, start: i64, reserved_end: i64) -> bool {
    let weekday_open = weekday < 5;
    let saturday = weekday == 5;
    let opening = if weekday_open {
        540
    } else if saturday {
        600
    } else {
        0
    };
    let closing = if weekday_open {
        1020
    } else if saturday {
        840
    } else {
        0
    };
    let starts_in_time = opening <= start;
    let ends_in_time = reserved_end <= closing;
    starts_in_time && ends_in_time
}

fn within_doctor_window(doctor: &Doctor, weekday: i64, start: i64, reserved_end: i64) -> bool {
    doctor.windows.iter().any(|window| {
        let day_matches = window.weekday == weekday;
        let starts_after_open = window.open <= start;
        let ends_before_close = reserved_end <= window.close;
        day_matches && starts_after_open && ends_before_close
    })
}

fn bookings_are_clear(
    data: &Normalized,
    doctor: &Doctor,
    day: i64,
    start: i64,
    reserved_end: i64,
) -> bool {
    data.bookings
        .iter()
        .filter(|booking| booking.day == day && booking.doctor.eq_ignore_ascii_case(&doctor.name))
        .count()
        < 4
        && data
            .bookings
            .iter()
            .filter(|booking| {
                booking.day == day && booking.doctor.eq_ignore_ascii_case(&doctor.name)
            })
            .all(|booking| start >= booking.end || reserved_end <= booking.start)
}

fn assemble_outcome(slot: Option<Slot>) -> Outcome {
    match slot {
        Some(slot) => Outcome::Appointment(Appointment {
            day: slot.day,
            start: slot.start,
            end: slot.end,
            doctor: slot.doctor,
            trace: collect_trace(),
        }),
        None => Outcome::Error(clinic_error!("NO_SLOT", None)),
    }
}

fn collect_trace() -> Vec<String> {
    [
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
    .map(|entry| entry.to_string())
    .collect()
}
