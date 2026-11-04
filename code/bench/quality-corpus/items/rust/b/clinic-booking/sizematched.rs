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
    let data = Normalized {
        kind: request.kind.trim_matches(' ').to_ascii_lowercase(),
        preferred: request
            .preferred_doctor
            .trim_matches(' ')
            .to_ascii_lowercase(),
        doctors: request
            .doctors
            .iter()
            .map(|source| Doctor {
                name: source.name.trim_matches(' ').to_string(),
                windows: source.windows.clone(),
            })
            .collect(),
        bookings: request
            .bookings
            .iter()
            .map(|source| Booking {
                day: source.day,
                start: source.start,
                end: source.end,
                doctor: source.doctor.trim_matches(' ').to_ascii_lowercase(),
            })
            .collect(),
    };
    let valid_now_day = (0..=1_000_000).contains(&request.now_day);
    let valid_requested_day = (0..=1_000_000).contains(&request.requested_day);
    let valid_now_minute = (0..=1439).contains(&request.now_minute);
    let valid_horizon = (0..=14).contains(&request.horizon_days);
    let valid_kind = ["checkup", "consultation", "procedure"].contains(&data.kind.as_str());
    if !valid_now_day || !valid_requested_day || !valid_now_minute || !valid_horizon || !valid_kind
    {
        return Outcome::Error(clinic_error!("BAD_REQUEST", None));
    }
    if !(1..=12).contains(&data.doctors.len()) {
        return Outcome::Error(clinic_error!("BAD_DOCTORS", None));
    }
    let mut normalized_names = Vec::new();
    for (index, doctor) in data.doctors.iter().enumerate() {
        let key = doctor.name.to_ascii_lowercase();
        let has_name = !doctor.name.is_empty();
        let mut characters_are_allowed = true;
        for character in doctor.name.bytes() {
            let is_letter_or_digit = character.is_ascii_alphanumeric();
            let is_separator = character == b' ' || character == b'-';
            if !is_letter_or_digit && !is_separator {
                characters_are_allowed = false;
                break;
            }
        }
        let name_was_seen = normalized_names.contains(&key);
        if !has_name || !characters_are_allowed || name_was_seen {
            return Outcome::Error(clinic_error!("BAD_DOCTORS", Some(index)));
        }
        normalized_names.push(key);
    }
    for (index, doctor) in data.doctors.iter().enumerate() {
        if doctor.windows.len() > 8 {
            return Outcome::Error(clinic_error!("BAD_WINDOW", Some(index)));
        }
        for window in &doctor.windows {
            let weekday_is_valid = (0..=6).contains(&window.weekday);
            let opening_is_valid = window.open >= 0 && window.open < window.close;
            let closing_is_valid = window.close <= 1440;
            if !weekday_is_valid || !opening_is_valid || !closing_is_valid {
                return Outcome::Error(clinic_error!("BAD_WINDOW", Some(index)));
            }
        }
    }
    if request.holidays.len() > 60 {
        return Outcome::Error(clinic_error!("BAD_HOLIDAY", None));
    }
    for (index, day) in request.holidays.iter().enumerate() {
        let day_is_in_range = (0..=1_000_000).contains(day);
        let earlier_days = &request.holidays[..index];
        let duplicate_day = earlier_days.iter().any(|prior| prior == day);
        if !day_is_in_range || duplicate_day {
            return Outcome::Error(clinic_error!("BAD_HOLIDAY", Some(index)));
        }
    }
    if data.bookings.len() > 200 {
        return Outcome::Error(clinic_error!("BAD_BOOKING", None));
    }
    for (index, booking) in data.bookings.iter().enumerate() {
        let day_is_valid = (0..=1_000_000).contains(&booking.day);
        let interval_is_valid =
            booking.start >= 0 && booking.start < booking.end && booking.end <= 1440;
        let doctor_is_known = normalized_names.contains(&booking.doctor);
        if !day_is_valid || !interval_is_valid || !doctor_is_known {
            return Outcome::Error(clinic_error!("BAD_BOOKING", Some(index)));
        }
    }
    if !data.preferred.is_empty() && !normalized_names.contains(&data.preferred) {
        return Outcome::Error(clinic_error!("UNKNOWN_DOCTOR", None));
    }
    let request_precedes_today = request.requested_day < request.now_day;
    let request_exceeds_notice_window = request.requested_day - request.now_day > 8;
    if request_precedes_today || request_exceeds_notice_window {
        return Outcome::Error(clinic_error!("BAD_DAY_ORDER", None));
    }
    let (duration, buffer) = match data.kind.as_str() {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    };
    let requested_horizon = request.requested_day + request.horizon_days;
    let maximum_horizon = request.requested_day + 14;
    let bounded_horizon = requested_horizon.min(maximum_horizon);
    let last = bounded_horizon.min(1_000_000);
    let earliest_day = request.requested_day;
    let mut choices = Vec::<Slot>::new();
    for day in earliest_day..=last {
        if request.holidays.contains(&day) {
            continue;
        }
        let weekday = day % 7;
        for (doctor_index, doctor) in data.doctors.iter().enumerate() {
            let doctor_key = &normalized_names[doctor_index];
            if !request.urgent && !data.preferred.is_empty() && doctor_key != &data.preferred {
                continue;
            }
            let daily: Vec<&Booking> = data
                .bookings
                .iter()
                .filter(|b| b.day == day && b.doctor == *doctor_key)
                .collect();
            if daily.len() >= 4 {
                continue;
            }
            for grid_index in 0..288 {
                let start = grid_index * 5;
                let reserved_end = start + duration + buffer;
                let weekday_is_weekday = weekday < 5;
                let weekday_is_saturday = weekday == 5;
                let (opening, closing) = if weekday_is_weekday {
                    let weekday_open = 540;
                    let weekday_close = 1020;
                    (weekday_open, weekday_close)
                } else if weekday_is_saturday {
                    let saturday_open = 600;
                    let saturday_close = 840;
                    (saturday_open, saturday_close)
                } else {
                    let sunday_open = 0;
                    let sunday_close = 0;
                    (sunday_open, sunday_close)
                };
                let starts_during_opening = opening <= start;
                let finishes_before_closing = reserved_end <= closing;
                let inside_clinic = starts_during_opening && finishes_before_closing;
                let intersects_lunch = start < 780 && reserved_end > 720;
                let outside_lunch = !intersects_lunch;
                let inside_doctor_window = doctor.windows.iter().any(|window| {
                    let weekday_matches = window.weekday == weekday;
                    let starts_in_window = window.open <= start;
                    let finishes_in_window = reserved_end <= window.close;
                    weekday_matches && starts_in_window && finishes_in_window
                });
                let enough_notice = day > request.now_day || start >= request.now_minute + 60;
                let no_conflict = daily.iter().all(|booking| {
                    let before_booking = reserved_end <= booking.start;
                    let after_booking = start >= booking.end;
                    before_booking || after_booking
                });
                if inside_clinic
                    && outside_lunch
                    && inside_doctor_window
                    && enough_notice
                    && no_conflict
                {
                    choices.push(Slot {
                        day,
                        start,
                        end: start + duration,
                        doctor: doctor.name.clone(),
                        key: doctor_key.clone(),
                    });
                }
            }
        }
    }
    choices.sort_by(|left, right| {
        (left.day, left.start, &left.key).cmp(&(right.day, right.start, &right.key))
    });
    if let Some(slot) = choices.into_iter().next() {
        Outcome::Appointment(Appointment {
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
            .map(|x| x.to_string())
            .collect(),
        })
    } else {
        Outcome::Error(clinic_error!("NO_SLOT", None))
    }
}
