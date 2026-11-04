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
    let current_day_is_valid = (0..=1_000_000).contains(&request.now_day);
    let requested_day_is_valid = (0..=1_000_000).contains(&request.requested_day);
    let current_minute_is_valid = (0..=1439).contains(&request.now_minute);
    let horizon_is_valid = (0..=14).contains(&request.horizon_days);
    let appointment_kind_is_valid =
        ["checkup", "consultation", "procedure"].contains(&data.kind.as_str());
    if !current_day_is_valid
        || !requested_day_is_valid
        || !current_minute_is_valid
        || !horizon_is_valid
        || !appointment_kind_is_valid
    {
        return Outcome::Error(clinic_error!("BAD_REQUEST", None));
    }
    if !(1..=12).contains(&data.doctors.len()) {
        return Outcome::Error(clinic_error!("BAD_DOCTORS", None));
    }
    let mut normalized_names = Vec::new();
    for (index, doctor) in data.doctors.iter().enumerate() {
        let key = doctor.name.to_ascii_lowercase();
        if doctor.name.is_empty()
            || !doctor
                .name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b' ' || b == b'-')
            || normalized_names.contains(&key)
        {
            return Outcome::Error(clinic_error!("BAD_DOCTORS", Some(index)));
        }
        normalized_names.push(key);
    }
    for (index, doctor) in data.doctors.iter().enumerate() {
        if doctor.windows.len() > 8
            || doctor.windows.iter().any(|w| {
                !(0..=6).contains(&w.weekday) || w.open < 0 || w.open >= w.close || w.close > 1440
            })
        {
            return Outcome::Error(clinic_error!("BAD_WINDOW", Some(index)));
        }
    }
    if request.holidays.len() > 60 {
        return Outcome::Error(clinic_error!("BAD_HOLIDAY", None));
    }
    for (index, day) in request.holidays.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || request.holidays[..index].contains(day) {
            return Outcome::Error(clinic_error!("BAD_HOLIDAY", Some(index)));
        }
    }
    if data.bookings.len() > 200 {
        return Outcome::Error(clinic_error!("BAD_BOOKING", None));
    }
    for (index, booking) in data.bookings.iter().enumerate() {
        if !(0..=1_000_000).contains(&booking.day)
            || booking.start < 0
            || booking.start >= booking.end
            || booking.end > 1440
            || !normalized_names.contains(&booking.doctor)
        {
            return Outcome::Error(clinic_error!("BAD_BOOKING", Some(index)));
        }
    }
    if !data.preferred.is_empty() && !normalized_names.contains(&data.preferred) {
        return Outcome::Error(clinic_error!("UNKNOWN_DOCTOR", None));
    }
    if request.requested_day < request.now_day || request.requested_day - request.now_day > 8 {
        return Outcome::Error(clinic_error!("BAD_DAY_ORDER", None));
    }
    let (duration, buffer) = match data.kind.as_str() {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    };
    let last = (request.requested_day + request.horizon_days)
        .min(request.requested_day + 14)
        .min(1_000_000);
    let mut choices = Vec::<Slot>::new();
    for day in request.requested_day..=last {
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
                let (opening, closing) = if weekday < 5 {
                    (540, 1020)
                } else if weekday == 5 {
                    (600, 840)
                } else {
                    (0, 0)
                };
                let inside_clinic = opening <= start && reserved_end <= closing;
                let outside_lunch = !(start < 780 && reserved_end > 720);
                let inside_doctor_window = doctor
                    .windows
                    .iter()
                    .any(|w| w.weekday == weekday && w.open <= start && reserved_end <= w.close);
                let enough_notice = day > request.now_day || start >= request.now_minute + 60;
                let no_conflict = daily
                    .iter()
                    .all(|b| start >= b.end || reserved_end <= b.start);
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
    choices.sort_by(|a, b| (&a.day, &a.start, &a.key).cmp(&(&b.day, &b.start, &b.key)));
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
