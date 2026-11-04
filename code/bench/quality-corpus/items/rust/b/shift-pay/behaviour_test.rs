use std::collections::HashSet;

use corpus::{solution, Outcome, PayShift, Quote, Request, Shift};

fn shift(
    day: i64,
    start: i64,
    end: i64,
    break_minutes: i64,
    holiday: bool,
    callout: bool,
) -> Shift {
    Shift {
        day,
        start,
        end,
        break_minutes,
        holiday,
        callout,
    }
}

fn request(role: &str, shifts: Vec<Shift>, bonus: bool) -> Request {
    Request {
        role: role.to_string(),
        shifts,
        bonus,
    }
}

fn error(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.to_string(),
        index,
    }
}

fn quote(shifts: Vec<PayShift>, paid: i64, cents: i64, applied: &[&str]) -> Outcome {
    Outcome::Quote(Quote {
        shifts,
        weekly_paid_minutes: paid,
        weekly_cents: cents,
        applied: applied.iter().map(|name| name.to_string()).collect(),
    })
}

fn pay(
    day: i64,
    start: i64,
    end: i64,
    paid: i64,
    regular: i64,
    overtime: i64,
    night: i64,
    weekend: i64,
    holiday: i64,
    callout: i64,
    bonus: i64,
    cents: i64,
) -> PayShift {
    PayShift {
        day,
        start,
        end,
        paid_minutes: paid,
        regular_minutes: regular,
        overtime_minutes: overtime,
        night_minutes: night,
        weekend_minutes: weekend,
        holiday_minutes: holiday,
        callout_minutes: callout,
        bonus_cents: bonus,
        cents,
    }
}

fn rhu(numerator: i128, denominator: i128) -> i64 {
    ((2 * numerator + denominator) / (2 * denominator)) as i64
}

fn oracle(given: &Request) -> Outcome {
    let role = given.role.trim().to_ascii_lowercase();
    let base = match role.as_str() {
        "helper" => 1800_i128,
        "nurse" => 2400_i128,
        "lead" => 3000_i128,
        _ => return error("BAD_ROLE", None),
    };
    if given.shifts.is_empty() {
        return error("EMPTY_WEEK", None);
    }
    if given.shifts.len() > 14 {
        return error("TOO_MANY_SHIFTS", None);
    }

    let mut occupied_minutes = Vec::new();
    for (index, row) in given.shifts.iter().enumerate() {
        if !(0..=6).contains(&row.day) {
            return error("BAD_DAY", Some(index));
        }
        if !(0..=1439).contains(&row.start) {
            return error("BAD_START", Some(index));
        }
        if !(0..=1439).contains(&row.end) {
            return error("BAD_END", Some(index));
        }
        if !(0..=240).contains(&row.break_minutes) {
            return error("BAD_BREAK", Some(index));
        }
        let duration = (row.end - row.start).rem_euclid(1440);
        let duration = if duration == 0 { 1440 } else { duration };
        if !(1..=960).contains(&duration) {
            return error("BAD_LENGTH", Some(index));
        }
        if row.break_minutes > duration {
            return error("BREAK_TOO_LONG", Some(index));
        }
        let first_minute = row.day * 1440 + row.start;
        let minutes = (first_minute..first_minute + duration).collect::<Vec<_>>();
        occupied_minutes.push((index, minutes));
    }

    let mut prior_minutes = HashSet::new();
    let mut earliest_collision = None;
    for (index, minutes) in &occupied_minutes {
        for minute in minutes {
            for offset in [-10080_i64, 0, 10080] {
                if prior_minutes.contains(&(*minute + offset)) {
                    let pair = (*minute, *index);
                    if earliest_collision.is_none_or(|found| pair < found) {
                        earliest_collision = Some(pair);
                    }
                }
            }
        }
        prior_minutes.extend(minutes.iter().copied());
    }
    if let Some((_, index)) = earliest_collision {
        return error("OVERLAP", Some(index));
    }

    let mut output = Vec::new();
    let mut prior_paid = 0_i64;
    let mut daily_seen = false;
    let mut weekly_seen = false;
    for (index, row) in given.shifts.iter().enumerate() {
        let duration = (row.end - row.start).rem_euclid(1440);
        let duration = if duration == 0 { 1440 } else { duration };
        let unpaid = if duration > 360 { row.break_minutes } else { 0 };
        let paid = duration - unpaid;
        let mut totals = [0_i64; 5];
        let mut amount = 0_i128;
        for worked_offset in 0..paid {
            let absolute = row.day * 1440 + row.start + unpaid + worked_offset;
            let minute_day = absolute.div_euclid(1440).rem_euclid(7);
            let minute_clock = absolute.rem_euclid(1440);
            let daily = worked_offset >= 480;
            let weekly = prior_paid + worked_offset >= 2400;
            let overtime = daily || weekly;
            let night = minute_clock >= 1320 || minute_clock < 360;
            let weekend = minute_day >= 5;
            let holiday = row.holiday;
            totals[if overtime { 1 } else { 0 }] += 1;
            totals[2] += i64::from(night);
            totals[3] += i64::from(weekend);
            totals[4] += i64::from(holiday);
            amount += base
                + base * i128::from(overtime) / 2
                + base * i128::from(night) / 5
                + base * i128::from(weekend) / 4
                + base * i128::from(holiday);
            daily_seen |= daily;
            weekly_seen |= weekly;
        }
        let top_up = if row.callout { (180 - paid).max(0) } else { 0 };
        amount += base * i128::from(top_up);
        let bonus_cents = if given.bonus && index + 1 == given.shifts.len() {
            // The weekly threshold is checked after all worked minutes below.
            500
        } else {
            0
        };
        output.push((
            pay(
                row.day,
                row.start,
                row.end,
                paid,
                totals[0],
                totals[1],
                totals[2],
                totals[3],
                totals[4],
                top_up,
                0,
                rhu(amount, 60),
            ),
            amount,
            bonus_cents,
        ));
        prior_paid += paid;
    }
    if given.bonus && prior_paid >= 600 {
        let last = output.last_mut().unwrap();
        last.0.bonus_cents = 500;
        last.0.cents = rhu(last.1 + 500 * 60, 60);
    }
    let applied = [
        (daily_seen, "daily-overtime"),
        (weekly_seen, "weekly-overtime"),
        (
            output.iter().any(|row| row.0.night_minutes > 0),
            "night-premium",
        ),
        (
            output.iter().any(|row| row.0.weekend_minutes > 0),
            "weekend-premium",
        ),
        (
            output.iter().any(|row| row.0.holiday_minutes > 0),
            "holiday-rate",
        ),
        (
            output.iter().any(|row| row.0.callout_minutes > 0),
            "callout-minimum",
        ),
        (output.iter().any(|row| row.0.bonus_cents > 0), "bonus"),
    ]
    .into_iter()
    .filter_map(|(used, name)| used.then(|| name.to_string()))
    .collect();
    let cents = output.iter().map(|row| row.0.cents).sum();
    Outcome::Quote(Quote {
        shifts: output.into_iter().map(|row| row.0).collect(),
        weekly_paid_minutes: prior_paid,
        weekly_cents: cents,
        applied,
    })
}

fn check(given: Request, expected: Option<Outcome>) {
    let wanted = expected.unwrap_or_else(|| oracle(&given));
    assert_eq!(solution(&given), wanted, "request: {given:?}");
}

#[test]
fn matches_worked_examples_and_precedence_errors() {
    let cases = [
        (
            request("helper", vec![shift(0, 540, 1020, 30, false, false)], false),
            quote(
                vec![pay(0, 540, 1020, 450, 450, 0, 0, 0, 0, 0, 0, 13500)],
                450,
                13500,
                &[],
            ),
        ),
        (
            request("nurse", vec![shift(1, 1320, 360, 30, false, false)], false),
            quote(
                vec![pay(1, 1320, 360, 450, 450, 0, 450, 0, 0, 0, 0, 21600)],
                450,
                21600,
                &["night-premium"],
            ),
        ),
        (
            request("helper", vec![shift(5, 540, 780, 0, false, false)], false),
            quote(
                vec![pay(5, 540, 780, 240, 240, 0, 0, 240, 0, 0, 0, 9000)],
                240,
                9000,
                &["weekend-premium"],
            ),
        ),
        (
            request("lead", vec![shift(2, 540, 780, 0, true, false)], false),
            quote(
                vec![pay(2, 540, 780, 240, 240, 0, 0, 0, 240, 0, 0, 24000)],
                240,
                24000,
                &["holiday-rate"],
            ),
        ),
        (
            request("helper", vec![shift(0, 540, 600, 0, false, true)], false),
            quote(
                vec![pay(0, 540, 600, 60, 60, 0, 0, 0, 0, 120, 0, 5400)],
                60,
                5400,
                &["callout-minimum"],
            ),
        ),
        (
            request("nurse", vec![shift(4, 480, 1080, 60, false, false)], false),
            quote(
                vec![pay(4, 480, 1080, 540, 480, 60, 0, 0, 0, 0, 0, 22800)],
                540,
                22800,
                &["daily-overtime"],
            ),
        ),
        (
            request("helper", vec![shift(6, 1380, 180, 0, false, false)], false),
            quote(
                vec![pay(6, 1380, 180, 240, 240, 0, 240, 60, 0, 0, 0, 9090)],
                240,
                9090,
                &["night-premium", "weekend-premium"],
            ),
        ),
        (
            request("lead", vec![shift(5, 600, 1080, 30, true, false)], true),
            quote(
                vec![pay(5, 600, 1080, 450, 450, 0, 0, 450, 450, 0, 0, 50625)],
                450,
                50625,
                &["weekend-premium", "holiday-rate"],
            ),
        ),
        (
            request("helper", vec![shift(1, 360, 900, 60, false, false)], false),
            quote(
                vec![pay(1, 360, 900, 480, 480, 0, 0, 0, 0, 0, 0, 14400)],
                480,
                14400,
                &[],
            ),
        ),
        (
            request("nurse", vec![shift(0, 720, 840, 0, false, true)], true),
            quote(
                vec![pay(0, 720, 840, 120, 120, 0, 0, 0, 0, 60, 0, 7200)],
                120,
                7200,
                &["callout-minimum"],
            ),
        ),
        (
            request(
                "helper",
                (0..6)
                    .map(|day| shift(day, 540, 1020, 0, false, false))
                    .collect(),
                false,
            ),
            quote(
                vec![
                    pay(0, 540, 1020, 480, 480, 0, 0, 0, 0, 0, 0, 14400),
                    pay(1, 540, 1020, 480, 480, 0, 0, 0, 0, 0, 0, 14400),
                    pay(2, 540, 1020, 480, 480, 0, 0, 0, 0, 0, 0, 14400),
                    pay(3, 540, 1020, 480, 480, 0, 0, 0, 0, 0, 0, 14400),
                    pay(4, 540, 1020, 480, 480, 0, 0, 0, 0, 0, 0, 14400),
                    pay(5, 540, 1020, 480, 0, 480, 0, 480, 0, 0, 0, 25200),
                ],
                2880,
                97200,
                &["weekly-overtime", "weekend-premium"],
            ),
        ),
        (
            request("helper", vec![shift(0, 1260, 300, 0, false, false)], false),
            quote(
                vec![pay(0, 1260, 300, 480, 480, 0, 420, 0, 0, 0, 0, 16920)],
                480,
                16920,
                &["night-premium"],
            ),
        ),
    ];
    for (given, expected) in cases {
        check(given, Some(expected));
    }

    let failures = [
        (request("unknown", vec![], false), "BAD_ROLE", None),
        (request("helper", vec![], false), "EMPTY_WEEK", None),
        (
            request("helper", vec![shift(0, 0, 60, 0, false, false); 15], false),
            "TOO_MANY_SHIFTS",
            None,
        ),
        (
            request("helper", vec![shift(7, 0, 60, 0, false, false)], false),
            "BAD_DAY",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, -1, 60, 0, false, false)], false),
            "BAD_START",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 0, 1440, 0, false, false)], false),
            "BAD_END",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 0, 60, 241, false, false)], false),
            "BAD_BREAK",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 0, 400, 400, false, true)], false),
            "BAD_BREAK",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 0, 961, 240, false, false)], false),
            "BAD_LENGTH",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 540, 540, 0, false, false)], false),
            "BAD_LENGTH",
            Some(0),
        ),
        (
            request("helper", vec![shift(0, 0, 60, 61, false, false)], false),
            "BREAK_TOO_LONG",
            Some(0),
        ),
        (
            request(
                "helper",
                vec![
                    shift(0, 0, 120, 0, false, false),
                    shift(0, 60, 180, 0, false, false),
                ],
                false,
            ),
            "OVERLAP",
            Some(1),
        ),
        (
            request(
                "helper",
                vec![
                    shift(0, 0, 961, 0, false, false),
                    shift(0, 60, 180, 0, false, false),
                    shift(0, 90, 200, 0, false, false),
                ],
                false,
            ),
            "BAD_LENGTH",
            Some(0),
        ),
    ];
    for (given, code, index) in failures {
        check(given, Some(error(code, index)));
    }
}

#[test]
fn checks_numeric_boundaries_midnights_and_interactions() {
    for (field, low, high, code) in [
        (0, 0, 6, "BAD_DAY"),
        (1, 0, 1439, "BAD_START"),
        (2, 0, 1439, "BAD_END"),
        (3, 0, 240, "BAD_BREAK"),
    ] {
        for index in 0_usize..=2 {
            for value in [low - 1, high + 1] {
                let mut rows = (0..index)
                    .map(|day| shift(day as i64 * 2, 0, 30, 0, false, false))
                    .collect::<Vec<_>>();
                let row = match field {
                    0 => shift(value, 0, 60, 0, false, false),
                    1 => shift(0, value, 60, 0, false, false),
                    2 => shift(0, 0, value, 0, false, false),
                    _ => shift(0, 0, 60, value, false, false),
                };
                rows.push(row);
                check(
                    request("helper", rows, false),
                    Some(error(code, Some(index))),
                );
            }
        }
    }
    let precedence = [
        (shift(7, 0, 60, 0, false, false), "BAD_DAY"),
        (shift(0, 1440, 1500, 0, false, false), "BAD_START"),
        (shift(0, 0, 1440, 241, false, false), "BAD_END"),
        (shift(0, 0, 60, 241, false, false), "BAD_BREAK"),
    ];
    for (row, code) in precedence {
        check(
            request("helper", vec![row], false),
            Some(error(code, Some(0))),
        );
    }
    for index in 1_usize..=2 {
        for row in [
            shift(6, 0, 961, 240, false, false),
            shift(6, 0, 60, 61, false, false),
        ] {
            let code = if row.end == 961 {
                "BAD_LENGTH"
            } else {
                "BREAK_TOO_LONG"
            };
            let mut rows = (0..index)
                .map(|day| shift(day as i64 * 2, 0, 30, 0, false, false))
                .collect::<Vec<_>>();
            rows.push(row);
            check(
                request("helper", rows, false),
                Some(error(code, Some(index))),
            );
        }
    }
    for (duration, unpaid, paid) in [
        (360, 60, 360),
        (361, 60, 301),
        (480, 0, 480),
        (481, 0, 481),
        (960, 240, 720),
    ] {
        let given = request(
            "helper",
            vec![shift(0, 0, duration % 1440, unpaid, false, false)],
            false,
        );
        check(given.clone(), None);
        if let Outcome::Quote(result) = oracle(&given) {
            assert_eq!(result.weekly_paid_minutes, paid);
        }
    }
    for (start, expected) in [(359, 1), (360, 0), (1319, 59), (1320, 60)] {
        let given = request(
            "helper",
            vec![shift(0, start, (start + 60) % 1440, 0, false, false)],
            false,
        );
        if let Outcome::Quote(result) = oracle(&given) {
            assert_eq!(result.shifts[0].night_minutes, expected);
        }
        check(given, None);
    }
    let overnight_holiday = request("lead", vec![shift(5, 1439, 1, 0, true, false)], false);
    if let Outcome::Quote(result) = oracle(&overnight_holiday) {
        assert_eq!(result.shifts[0].holiday_minutes, 2);
    }
    check(overnight_holiday, None);
    check(
        request("helper", vec![shift(0, 1380, 1439, 0, false, false)], false),
        None,
    );
    for spans in [
        vec![
            shift(0, 60, 120, 0, false, false),
            shift(6, 1380, 180, 0, false, false),
        ],
        vec![
            shift(6, 1380, 180, 0, false, false),
            shift(0, 60, 120, 0, false, false),
        ],
        vec![
            shift(0, 0, 60, 0, false, false),
            shift(0, 60, 120, 0, false, false),
        ],
    ] {
        check(request("helper", spans, false), None);
    }
    for spans in [
        vec![
            shift(0, 120, 240, 0, false, false),
            shift(6, 1380, 180, 0, false, false),
        ],
        vec![
            shift(6, 1380, 180, 0, false, false),
            shift(0, 120, 240, 0, false, false),
        ],
    ] {
        check(
            request("helper", spans, false),
            Some(error("OVERLAP", Some(1))),
        );
    }
    for count in [179, 180] {
        check(
            request("helper", vec![shift(0, 0, count, 0, false, true)], false),
            None,
        );
    }
    check(
        request("helper", vec![shift(0, 0, 60, 60, false, false)], false),
        None,
    );
    check(
        request("helper", vec![shift(0, 330, 810, 30, false, false)], false),
        None,
    );
    check(
        request(
            "helper",
            vec![
                shift(5, 600, 601, 0, false, false),
                shift(6, 600, 601, 0, false, false),
            ],
            false,
        ),
        None,
    );
    let per_shift = request(
        "helper",
        vec![
            shift(5, 600, 601, 0, false, false),
            shift(6, 600, 601, 0, false, false),
        ],
        false,
    );
    if let Outcome::Quote(result) = oracle(&per_shift) {
        assert_eq!(result.weekly_cents, 76);
    }
    check(per_shift, None);
    let half_cent = request("helper", vec![shift(5, 600, 601, 0, false, false)], false);
    if let Outcome::Quote(result) = oracle(&half_cent) {
        assert_eq!(result.shifts[0].cents, 38);
    }
    check(half_cent, None);
    let weekend_holiday = request("lead", vec![shift(5, 600, 601, 0, true, false)], false);
    if let Outcome::Quote(result) = oracle(&weekend_holiday) {
        assert_eq!(result.shifts[0].cents, 113);
    }
    check(weekend_holiday, None);
    let overlap_tie = request(
        "helper",
        vec![
            shift(0, 0, 120, 0, false, false),
            shift(0, 60, 120, 0, false, false),
            shift(0, 60, 120, 0, false, false),
        ],
        false,
    );
    check(overlap_tie, Some(error("OVERLAP", Some(1))));
    for (second, expected_bonus) in [(300, 0), (301, 500)] {
        let bonus_edge = request(
            "helper",
            vec![
                shift(0, 0, 299, 0, false, false),
                shift(1, 0, second, 0, false, false),
            ],
            true,
        );
        if let Outcome::Quote(result) = oracle(&bonus_edge) {
            assert_eq!(result.shifts[1].bonus_cents, expected_bonus);
        }
        check(bonus_edge, None);
    }
    let weekly_edge = request(
        "helper",
        vec![
            shift(4, 540, 1020, 0, false, false),
            shift(3, 540, 1020, 0, false, false),
            shift(2, 540, 1020, 0, false, false),
            shift(1, 540, 1020, 0, false, false),
            shift(0, 540, 1020, 0, false, false),
            shift(5, 540, 541, 0, false, false),
        ],
        false,
    );
    check(weekly_edge, None);
    let weekly_threshold = request(
        "helper",
        vec![
            shift(0, 540, 1020, 0, false, false),
            shift(1, 540, 1020, 0, false, false),
            shift(2, 540, 1020, 0, false, false),
            shift(3, 540, 1020, 0, false, false),
            shift(4, 0, 479, 0, false, false),
            shift(5, 0, 2, 0, false, false),
        ],
        false,
    );
    if let Outcome::Quote(result) = oracle(&weekly_threshold) {
        assert_eq!(result.shifts[5].overtime_minutes, 1);
    }
    check(weekly_threshold, None);
    let combined_overtime = request(
        "helper",
        (0..5)
            .map(|day| shift(day, 540, 1020, 0, false, false))
            .chain([shift(5, 540, 1021, 0, false, false)])
            .collect(),
        false,
    );
    if let Outcome::Quote(result) = oracle(&combined_overtime) {
        assert_eq!(&result.applied[..2], &["daily-overtime", "weekly-overtime"]);
    }
    check(combined_overtime, None);
    let callout_threshold = request(
        "helper",
        vec![
            shift(0, 0, 478, 0, false, false),
            shift(1, 0, 478, 0, false, false),
            shift(2, 0, 478, 0, false, false),
            shift(3, 0, 478, 0, false, false),
            shift(4, 0, 478, 0, false, false),
            shift(5, 0, 10, 0, false, true),
        ],
        false,
    );
    check(callout_threshold, None);
    let topup_not_weekly = request(
        "helper",
        vec![
            shift(0, 0, 460, 0, false, false),
            shift(1, 0, 460, 0, false, false),
            shift(2, 0, 460, 0, false, false),
            shift(3, 0, 460, 0, false, false),
            shift(4, 0, 460, 0, false, false),
            shift(5, 0, 10, 0, false, true),
            shift(6, 0, 1, 0, false, false),
        ],
        false,
    );
    check(topup_not_weekly, None);
    let max_rows = request(
        "helper",
        (0..7)
            .flat_map(|day| {
                [0, 100].map(move |start| shift(day, start, start + 30, 0, false, false))
            })
            .collect(),
        false,
    );
    check(max_rows, None);
    check(
        request(" Helper ", vec![shift(0, 600, 601, 0, false, false)], false),
        None,
    );
    check(
        request("helper", vec![shift(0, 0, 960, 0, false, true)], true),
        None,
    );
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

fn generated_request(rng: &mut Lcg, round: usize) -> Request {
    let count = (rng.next() % 14 + 1) as usize;
    let slot = 10080 / count as i64;
    let mut shifts = Vec::new();
    for index in 0..count {
        let maximum = 960.min(slot);
        let duration = if index == 0 && round % 7 == 0 {
            maximum
        } else {
            (rng.next() % maximum as u64 + 1) as i64
        };
        let latest = (slot - duration).max(0);
        let timeline = index as i64 * slot + (rng.next() % (latest as u64 + 1)) as i64;
        let start = timeline % 1440;
        let break_max = duration.min(240);
        shifts.push(shift(
            timeline / 1440,
            start,
            (start + duration) % 1440,
            (rng.next() % (break_max as u64 + 1)) as i64,
            rng.next() % 2 == 0,
            rng.next() % 2 == 0,
        ));
    }
    shifts.reverse();
    match round % 16 {
        0 => {
            let mut duplicate = shifts[0].clone();
            duplicate.break_minutes = 0;
            shifts.push(duplicate);
        }
        1 => shifts[0].day = 7,
        2 => shifts[0].start = 1440,
        3 => shifts[0].end = 1440,
        4 => shifts[0].break_minutes = 241,
        5 => {
            shifts[0].start = 0;
            shifts[0].end = 961;
            shifts[0].break_minutes = 0;
        }
        6 => {
            shifts[0].start = 0;
            shifts[0].end = 2;
            shifts[0].break_minutes = 3;
        }
        _ => {}
    }
    let role = ["helper", "nurse", "lead"][(rng.next() % 3) as usize];
    request(role, shifts, rng.next() % 2 == 0)
}

#[test]
fn matches_seeded_minute_oracle_for_thousands_of_requests() {
    let mut rng = Lcg(20_261_018);
    let mut valid = 0;
    let mut invalid = 0;
    let mut failures = std::collections::BTreeMap::new();
    let mut samples = Vec::new();
    for round in 0..4_000 {
        let given = generated_request(&mut rng, round);
        let expected = oracle(&given);
        if matches!(expected, Outcome::Quote(_)) {
            valid += 1;
        } else if let Outcome::Error { code, .. } = &expected {
            invalid += 1;
            *failures.entry(code.clone()).or_insert(0) += 1;
            if samples.len() < 4 {
                samples.push((code.clone(), given.clone()));
            }
        }
        assert_eq!(solution(&given), expected, "random case {round}: {given:?}");
    }
    assert!(
        valid * 2 >= valid + invalid,
        "random cases must be at least half valid: {valid} valid, {invalid} invalid, {failures:?}, {samples:?}"
    );
}
