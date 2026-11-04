use corpus::{solution, Appointment, Booking, ClinicError, Doctor, Outcome, Request, Window};

fn doctor(name: &str, windows: &[(i64, i64, i64)]) -> Doctor {
    Doctor {
        name: name.into(),
        windows: windows
            .iter()
            .map(|&(weekday, open, close)| Window {
                weekday,
                open,
                close,
            })
            .collect(),
    }
}
fn booking(day: i64, start: i64, end: i64, doctor: &str) -> Booking {
    Booking {
        day,
        start,
        end,
        doctor: doctor.into(),
    }
}
fn base() -> Request {
    Request {
        now_day: 100,
        now_minute: 480,
        requested_day: 100,
        horizon_days: 2,
        kind: "checkup".into(),
        urgent: false,
        preferred_doctor: "".into(),
        holidays: vec![],
        doctors: vec![doctor(
            "Ada",
            &(0..5).map(|d| (d, 540, 1020)).collect::<Vec<_>>(),
        )],
        bookings: vec![],
    }
}
fn success(day: i64, start: i64, end: i64, name: &str) -> Outcome {
    Outcome::Appointment(Appointment {
        day,
        start,
        end,
        doctor: name.into(),
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
}
fn failure(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error(ClinicError {
        code: code.into(),
        index,
    })
}
fn check(request: &Request, expected: Outcome) {
    let actual = solution(request);
    assert_eq!(actual, expected, "request: {request:?}");
    assert_eq!(actual, oracle(request), "oracle request: {request:?}");
}

// This oracle enumerates each day, doctor and grid point without implementation helpers.
fn oracle(r: &Request) -> Outcome {
    let kind = r.kind.trim_matches(' ').to_ascii_lowercase();
    if !(0..=1_000_000).contains(&r.now_day)
        || !(0..=1_000_000).contains(&r.requested_day)
        || !(0..=1439).contains(&r.now_minute)
        || !(0..=14).contains(&r.horizon_days)
        || !["checkup", "consultation", "procedure"].contains(&kind.as_str())
    {
        return failure("BAD_REQUEST", None);
    }
    if !(1..=12).contains(&r.doctors.len()) {
        return failure("BAD_DOCTORS", None);
    }
    let names: Vec<String> = r
        .doctors
        .iter()
        .map(|d| d.name.trim_matches(' ').to_ascii_lowercase())
        .collect();
    for (i, name) in names.iter().enumerate() {
        if name.is_empty()
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b' ' || b == b'-')
            || names[..i].contains(name)
        {
            return failure("BAD_DOCTORS", Some(i));
        }
    }
    for (i, d) in r.doctors.iter().enumerate() {
        if d.windows.len() > 8
            || d.windows.iter().any(|w| {
                !(0..=6).contains(&w.weekday) || w.open < 0 || w.open >= w.close || w.close > 1440
            })
        {
            return failure("BAD_WINDOW", Some(i));
        }
    }
    if r.holidays.len() > 60 {
        return failure("BAD_HOLIDAY", None);
    }
    for (i, day) in r.holidays.iter().enumerate() {
        if !(0..=1_000_000).contains(day) || r.holidays[..i].contains(day) {
            return failure("BAD_HOLIDAY", Some(i));
        }
    }
    if r.bookings.len() > 200 {
        return failure("BAD_BOOKING", None);
    }
    for (i, b) in r.bookings.iter().enumerate() {
        let name = b.doctor.trim_matches(' ').to_ascii_lowercase();
        if !(0..=1_000_000).contains(&b.day)
            || b.start < 0
            || b.start >= b.end
            || b.end > 1440
            || !names.contains(&name)
        {
            return failure("BAD_BOOKING", Some(i));
        }
    }
    let preferred = r.preferred_doctor.trim_matches(' ').to_ascii_lowercase();
    if !preferred.is_empty() && !names.contains(&preferred) {
        return failure("UNKNOWN_DOCTOR", None);
    }
    if r.requested_day < r.now_day || r.requested_day as i128 > r.now_day as i128 + 8 {
        return failure("BAD_DAY_ORDER", None);
    }
    let (duration, buffer) = match kind.as_str() {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15),
    };
    let last = (r.requested_day as i128 + r.horizon_days as i128)
        .min(r.requested_day as i128 + 14)
        .min(1_000_000) as i64;
    let mut valid = Vec::<(i64, i64, String, String, i64)>::new();
    for day in r.requested_day..=last {
        if r.holidays.iter().any(|h| *h == day) {
            continue;
        }
        let weekday = day % 7;
        for (di, d) in r.doctors.iter().enumerate() {
            let key = &names[di];
            if !r.urgent && !preferred.is_empty() && key != &preferred {
                continue;
            }
            let daily: Vec<&Booking> = r
                .bookings
                .iter()
                .filter(|b| {
                    b.day == day
                        && b.doctor
                            .trim_matches(' ')
                            .eq_ignore_ascii_case(&d.name.trim_matches(' '))
                })
                .collect();
            for start in (0..=1435).step_by(5) {
                let occupied_end = start + duration + buffer;
                let (open, close) = if weekday < 5 {
                    (540, 1020)
                } else if weekday == 5 {
                    (600, 840)
                } else {
                    (0, 0)
                };
                let window_ok = d
                    .windows
                    .iter()
                    .any(|w| w.weekday == weekday && w.open <= start && occupied_end <= w.close);
                let hour_ok =
                    open <= start && occupied_end <= close && !(start < 780 && occupied_end > 720);
                let notice_ok = day > r.now_day || start as i128 >= r.now_minute as i128 + 60;
                let conflict = daily
                    .iter()
                    .any(|b| start < b.end && b.start < occupied_end);
                if window_ok && hour_ok && notice_ok && daily.len() < 4 && !conflict {
                    valid.push((
                        day,
                        start,
                        key.clone(),
                        d.name.trim_matches(' ').to_string(),
                        start + duration,
                    ));
                }
            }
        }
    }
    valid.sort();
    match valid.first() {
        Some((day, start, _, name, end)) => success(*day, *start, *end, name),
        None => failure("NO_SLOT", None),
    }
}

#[test]
fn worked_examples_and_error_precedence() {
    let mut r = base();
    check(&r, success(100, 540, 560, "Ada"));
    r.kind = "  CONSULTATION  ".into();
    check(&r, success(100, 540, 570, "Ada"));
    r = base();
    r.now_minute = 500;
    check(&r, success(100, 560, 580, "Ada"));
    r.now_minute = 1000;
    check(&r, success(101, 540, 560, "Ada"));
    r = base();
    r.kind = "procedure".into();
    check(&r, success(100, 540, 600, "Ada"));
    r = base();
    r.doctors = vec![doctor("  Ada  ", &[(2, 600, 660)])];
    check(&r, success(100, 600, 620, "Ada"));
    r.doctors = vec![doctor("Ada", &[(2, 700, 840)])];
    check(&r, success(100, 780, 800, "Ada"));
    r = base();
    r.bookings = vec![booking(100, 540, 570, "  ADA  ")];
    check(&r, success(100, 570, 590, "Ada"));
    r.bookings = vec![booking(100, 540, 565, "Ada")];
    check(&r, success(100, 565, 585, "Ada"));
    r.bookings = [540, 560, 580, 600]
        .iter()
        .map(|s| booking(100, *s, *s + 10, "Ada"))
        .collect();
    check(&r, success(101, 540, 560, "Ada"));
    r = base();
    r.holidays = vec![100];
    check(&r, success(101, 540, 560, "Ada"));
    r = base();
    r.doctors = vec![
        doctor("Bo", &[(2, 540, 1020)]),
        doctor("Ada", &[(2, 540, 1020)]),
    ];
    check(&r, success(100, 540, 560, "Ada"));

    let mut cases = vec![];
    r = base();
    r.now_day = -1;
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.doctors.clear();
    cases.push((r, failure("BAD_DOCTORS", None)));
    r = base();
    r.doctors = vec![doctor("Ada", &[]), doctor(" ada ", &[])];
    cases.push((r, failure("BAD_DOCTORS", Some(1))));
    r = base();
    r.doctors = vec![
        doctor("Ada", &[]),
        doctor("Bo", &[]),
        doctor("Cy", &[(2, 900, 900)]),
    ];
    cases.push((r, failure("BAD_WINDOW", Some(2))));
    r = base();
    r.holidays = vec![100, 100];
    cases.push((r, failure("BAD_HOLIDAY", Some(1))));
    r = base();
    r.bookings = vec![booking(100, 540, 550, "Ada"), booking(100, 540, 540, "Ada")];
    cases.push((r, failure("BAD_BOOKING", Some(1))));
    r = base();
    r.preferred_doctor = "Bo".into();
    cases.push((r, failure("UNKNOWN_DOCTOR", None)));
    r = base();
    r.requested_day = 99;
    cases.push((r, failure("BAD_DAY_ORDER", None)));
    r = base();
    r.requested_day = 109;
    cases.push((r, failure("BAD_DAY_ORDER", None)));
    r = base();
    r.kind = "bad".into();
    r.doctors.clear();
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.doctors = vec![doctor("Ada", &[]), doctor("ada", &[])];
    r.holidays = vec![-1];
    cases.push((r, failure("BAD_DOCTORS", Some(1))));
    r = base();
    r.bookings = vec![booking(100, 1, 1, "Ada")];
    r.preferred_doctor = "Bo".into();
    cases.push((r, failure("BAD_BOOKING", Some(0))));
    r = base();
    r.bookings = vec![
        booking(100, 540, 550, "Ada"),
        booking(100, 550, 560, "Ada"),
        booking(100, 560, 560, "Ada"),
    ];
    cases.push((r, failure("BAD_BOOKING", Some(2))));
    r = base();
    r.bookings = vec![booking(100, 540, 550, "Missing")];
    cases.push((r, failure("BAD_BOOKING", Some(0))));
    r = base();
    r.bookings = vec![booking(100, 540, 1441, "Ada")];
    cases.push((r, failure("BAD_BOOKING", Some(0))));
    r = base();
    r.bookings = vec![booking(-1, 540, 550, "Ada")];
    cases.push((r, failure("BAD_BOOKING", Some(0))));
    r = base();
    r.bookings = vec![booking(100, -1, 550, "Ada")];
    cases.push((r, failure("BAD_BOOKING", Some(0))));
    r = base();
    r.holidays = vec![1_000_001];
    cases.push((r, failure("BAD_HOLIDAY", Some(0))));
    r = base();
    r.now_day = 1_000_001;
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.requested_day = 101;
    r.now_day = 100;
    r.preferred_doctor = "Missing".into();
    cases.push((r, failure("UNKNOWN_DOCTOR", None)));
    r = base();
    r.requested_day = 99;
    r.holidays = vec![100, 100];
    cases.push((r, failure("BAD_HOLIDAY", Some(1))));
    r = base();
    r.holidays = vec![-1];
    r.bookings = vec![booking(100, 540, 540, "Ada")];
    cases.push((r, failure("BAD_HOLIDAY", Some(0))));
    r = base();
    r.requested_day = 99;
    r.preferred_doctor = "Missing".into();
    cases.push((r, failure("UNKNOWN_DOCTOR", None)));
    r = base();
    r.doctors = vec![doctor("Ada", &[(7, 540, 600)])];
    cases.push((r, failure("BAD_WINDOW", Some(0))));
    r = base();
    r.doctors = vec![doctor("Ada", &[(1, 540, 1020)])];
    cases.push((r, failure("NO_SLOT", None)));
    r = base();
    r.doctors = vec![doctor("Ada@", &[])];
    cases.push((r, failure("BAD_DOCTORS", Some(0))));
    r = base();
    r.doctors = (0..13).map(|n| doctor(&format!("D{n}"), &[])).collect();
    cases.push((r, failure("BAD_DOCTORS", None)));
    r = base();
    r.horizon_days = 15;
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.now_minute = 1440;
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.requested_day = 1_000_001;
    cases.push((r, failure("BAD_REQUEST", None)));
    r = base();
    r.doctors = vec![doctor("Ada", &[(2, 540, 1441)])];
    cases.push((r, failure("BAD_WINDOW", Some(0))));
    r = base();
    r.holidays = (200..261).collect();
    cases.push((r, failure("BAD_HOLIDAY", None)));
    r = base();
    r.bookings = (0..201).map(|n| booking(500 + n, 0, 1, "Ada")).collect();
    cases.push((r, failure("BAD_BOOKING", None)));
    r = base();
    r.doctors = vec![doctor("Ada", &vec![(2, 540, 600); 9])];
    cases.push((r, failure("BAD_WINDOW", Some(0))));
    r = base();
    r.doctors = vec![doctor("Ada", &vec![(2, 540, 600); 8])];
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.now_minute = 481;
    check(&r, success(100, 545, 565, "Ada"));
    r = base();
    r.horizon_days = 0;
    check(&r, success(100, 540, 560, "Ada"));
    r.holidays = vec![100];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.now_day = 0;
    r.now_minute = 0;
    r.requested_day = 0;
    r.horizon_days = 0;
    check(&r, success(0, 540, 560, "Ada"));
    r = base();
    r.doctors = vec![doctor("Ada", &[])];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.now_day = 100;
    r.requested_day = 108;
    r.horizon_days = 0;
    check(&r, success(108, 540, 560, "Ada"));
    r = base();
    r.requested_day = 103;
    r.horizon_days = 0;
    r.doctors = vec![doctor("Ada", &[(5, 600, 840)])];
    check(&r, success(103, 600, 620, "Ada"));
    r = base();
    r.doctors = vec![doctor("Ada", &[(2, 540, 565)])];
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.doctors = vec![doctor("Ada", &[(2, 600, 625)])];
    check(&r, success(100, 600, 620, "Ada"));
    r = base();
    r.horizon_days = 0;
    r.doctors = vec![doctor("Ada", &[(2, 540, 564)])];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.doctors = vec![doctor("Ada", &[(2, 995, 1020)])];
    check(&r, success(100, 995, 1015, "Ada"));
    r = base();
    r.bookings = vec![booking(100, 540, 695, "Ada")];
    check(&r, success(100, 695, 715, "Ada"));
    r = base();
    r.preferred_doctor = " ada ".into();
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.now_day = 999_999;
    r.requested_day = 1_000_000;
    r.horizon_days = 14;
    check(&r, success(1_000_000, 540, 560, "Ada"));
    r = base();
    r.now_day = 999_992;
    r.requested_day = 1_000_000;
    r.horizon_days = 14;
    r.doctors = vec![doctor("Ada", &[(2, 540, 1020)])];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.doctors = vec![
        doctor("Zoe", &[(2, 540, 1020)]),
        doctor("Ada", &[(2, 540, 1020)]),
    ];
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.doctors = vec![
        doctor("BO", &[(2, 540, 1020)]),
        doctor("ada", &[(2, 540, 1020)]),
    ];
    check(&r, success(100, 540, 560, "ada"));
    r = base();
    r.preferred_doctor = "Ada".into();
    r.doctors = vec![doctor("Ada", &[]), doctor("Bo", &[(2, 540, 1020)])];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.doctors = vec![
        doctor("Ada", &[(2, 800, 900)]),
        doctor("Bo", &[(2, 540, 1020)]),
    ];
    r.bookings = vec![
        booking(100, 540, 570, "Bo"),
        booking(100, 560, 590, "Bo"),
        booking(100, 580, 610, "Bo"),
        booking(100, 600, 630, "Bo"),
    ];
    check(&r, success(100, 800, 820, "Ada"));
    r = base();
    r.doctors = vec![
        doctor("Ada", &[(2, 540, 1020)]),
        doctor("Bo", &[(2, 540, 1020)]),
    ];
    r.bookings = [540, 560, 580, 600]
        .iter()
        .map(|s| booking(100, *s, *s + 10, "Ada"))
        .collect();
    check(&r, success(100, 540, 560, "Bo"));
    r.horizon_days = 0;
    r.doctors = vec![doctor("Ada", &[(2, 540, 1020)])];
    check(&r, failure("NO_SLOT", None));
    r = base();
    r.bookings = [800, 820, 840]
        .iter()
        .map(|s| booking(100, *s, *s + 10, "Ada"))
        .collect();
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.holidays = (200..260).collect();
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.horizon_days = 14;
    r.holidays = (100..114).collect();
    check(&r, success(114, 540, 560, "Ada"));
    r = base();
    r.bookings = (0..200).map(|n| booking(500 + n, 0, 1, "Ada")).collect();
    check(&r, success(100, 540, 560, "Ada"));
    r = base();
    r.doctors = (0..12)
        .map(|n| doctor(&format!("D{n}"), &[(2, 540, 1020)]))
        .collect();
    check(&r, success(100, 540, 560, "D0"));
    for (case, expected) in cases {
        check(&case, expected);
    }
}

struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }
}

#[test]
fn seeded_random_domain_mix_matches_brute_force_oracle() {
    let mut rng = Lcg(731904);
    let mut valid_count = 0;
    let mut invalid_count = 0;
    for round in 0..2000 {
        let names = ["Ada", "Bo", "Cy"];
        let count = 1 + (rng.next() % 3) as usize;
        let mut r = base();
        r.now_day = 20 + (rng.next() % 880) as i64;
        r.requested_day = r.now_day + (rng.next() % 9) as i64;
        r.now_minute = (rng.next() % 1440) as i64;
        r.horizon_days = (rng.next() % 15) as i64;
        r.kind = ["checkup", "consultation", "procedure"][(rng.next() % 3) as usize].into();
        r.urgent = rng.next() % 2 == 0;
        r.preferred_doctor = ["", "Ada", "Bo"][(rng.next() % 3) as usize].into();
        r.doctors = (0..count)
            .map(|i| {
                let windows = (0..7)
                    .filter(|_| rng.next() % 4 != 0)
                    .map(|weekday| {
                        let open = if weekday == 5 { 600 } else { 540 };
                        let close = if weekday == 5 { 840 } else { 1020 };
                        (weekday, open, close)
                    })
                    .collect::<Vec<_>>();
                doctor(names[i], &windows)
            })
            .collect();
        let first = r.requested_day;
        r.holidays = (0..(rng.next() % 3))
            .map(|_| first + (rng.next() % (r.horizon_days as u64 + 1)) as i64)
            .collect();
        r.holidays.sort();
        r.holidays.dedup();
        if round % 4 == 0 {
            r.horizon_days = 15;
        }
        let booking_count = (rng.next() % 7) as usize;
        r.bookings = (0..booking_count)
            .map(|_| {
                let doctor_name = names[(rng.next() % count as u64) as usize];
                let day = first + (rng.next() % (r.horizon_days.max(0) as u64 + 1)) as i64;
                let start = [540, 560, 580, 600, 620, 800, 820][(rng.next() % 7) as usize];
                let length = [10, 20, 30][(rng.next() % 3) as usize];
                booking(day, start, start + length, doctor_name)
            })
            .collect();
        if round % 8 == 1 && count > 0 {
            let name = names[0];
            r.bookings.extend(
                [540, 560, 580, 600]
                    .iter()
                    .map(|s| booking(first, *s, *s + 10, name)),
            );
        }
        if round % 4 == 0 {
            invalid_count += 1;
        } else {
            valid_count += 1;
        }
        check(&r, oracle(&r));
    }
    println!("seeded random mix: {valid_count} valid, {invalid_count} invalid (75% valid)");
    assert!(valid_count * 2 >= valid_count + invalid_count);
}
