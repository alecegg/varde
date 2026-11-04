#[derive(Debug, Clone, PartialEq)]
pub struct Shift {
    pub day: i64,
    pub start: i64,
    pub end: i64,
    pub break_minutes: i64,
    pub holiday: bool,
    pub callout: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Request {
    pub role: String,
    pub shifts: Vec<Shift>,
    pub bonus: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PayShift {
    pub day: i64,
    pub start: i64,
    pub end: i64,
    pub paid_minutes: i64,
    pub regular_minutes: i64,
    pub overtime_minutes: i64,
    pub night_minutes: i64,
    pub weekend_minutes: i64,
    pub holiday_minutes: i64,
    pub callout_minutes: i64,
    pub bonus_cents: i64,
    pub cents: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Quote {
    pub shifts: Vec<PayShift>,
    pub weekly_paid_minutes: i64,
    pub weekly_cents: i64,
    pub applied: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Quote(Quote),
    Error { code: String, index: Option<usize> },
}

struct Interval {
    index: usize,
    start: i64,
    duration: i64,
}

struct PricedShift {
    row: PayShift,
    daily_overtime: bool,
    weekly_overtime: bool,
}

const RULE_NAMES: [&str; 7] = [
    "daily-overtime",
    "weekly-overtime",
    "night-premium",
    "weekend-premium",
    "holiday-rate",
    "callout-minimum",
    "bonus",
];

/// Return ordered shift pay rows or the first contract validation error.
pub fn solution(request: &Request) -> Outcome {
    let base = match request_base(request) {
        Ok(base) => base,
        Err(error) => return error,
    };
    let intervals = match validate_shifts(&request.shifts) {
        Ok(rows) => rows,
        Err((code, index)) => return failure(code, Some(index)),
    };
    if let Some(index) = overlap_error(&intervals) {
        return failure("OVERLAP", Some(index));
    }
    price_week(request, base)
}

fn request_base(request: &Request) -> Result<i128, Outcome> {
    let role = request.role.trim().to_ascii_lowercase();
    let base = match role.as_str() {
        "helper" => 1800,
        "nurse" => 2400,
        "lead" => 3000,
        _ => return Err(failure("BAD_ROLE", None)),
    };
    if request.shifts.is_empty() {
        return Err(failure("EMPTY_WEEK", None));
    }
    if request.shifts.len() > 14 {
        return Err(failure("TOO_MANY_SHIFTS", None));
    }
    Ok(base)
}

fn failure(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.to_string(),
        index,
    }
}

fn validate_shifts(shifts: &[Shift]) -> Result<Vec<Interval>, (&'static str, usize)> {
    let mut intervals = Vec::with_capacity(shifts.len());
    for (index, row) in shifts.iter().enumerate() {
        let duration = validate_shift(row, index)?;
        intervals.push(Interval {
            index,
            start: row.day * 1440 + row.start,
            duration,
        });
    }
    Ok(intervals)
}

fn validate_shift(row: &Shift, index: usize) -> Result<i64, (&'static str, usize)> {
    validate_clock_fields(row, index)?;
    let duration = shift_duration(row);
    if !(1..=960).contains(&duration) {
        return Err(("BAD_LENGTH", index));
    }
    if row.break_minutes > duration {
        return Err(("BREAK_TOO_LONG", index));
    }
    Ok(duration)
}

fn validate_clock_fields(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    for (valid, code) in [
        ((0..=6).contains(&row.day), "BAD_DAY"),
        ((0..=1439).contains(&row.start), "BAD_START"),
        ((0..=1439).contains(&row.end), "BAD_END"),
        ((0..=240).contains(&row.break_minutes), "BAD_BREAK"),
    ] {
        if !valid {
            return Err((code, index));
        }
    }
    Ok(())
}

fn shift_duration(row: &Shift) -> i64 {
    let duration = (row.end - row.start).rem_euclid(1440);
    if duration == 0 {
        1440
    } else {
        duration
    }
}

fn overlap_error(intervals: &[Interval]) -> Option<usize> {
    let mut collisions = Vec::new();
    for left in 0..intervals.len() {
        for right in (left + 1)..intervals.len() {
            for offset in [-10080_i64, 0, 10080] {
                if let Some(start) = overlap_start(&intervals[left], &intervals[right], offset) {
                    collisions.push((start, intervals[right].index));
                }
            }
        }
    }
    collisions.into_iter().min().map(|(_, index)| index)
}

fn overlap_start(left: &Interval, right: &Interval, offset: i64) -> Option<i64> {
    let start = left.start.max(right.start + offset);
    let end = (left.start + left.duration).min(right.start + offset + right.duration);
    (start < end).then_some(start)
}

fn price_week(request: &Request, base: i128) -> Outcome {
    let mut weekly_prior = 0_i64;
    let shifts: Vec<_> = request
        .shifts
        .iter()
        .map(|row| {
            let (unpaid, paid, top_up) = paid_window(row);
            let (counts, amount, daily, weekly) =
                price_minutes(row, base, weekly_prior, unpaid, paid);
            let priced = priced_row(
                row,
                paid,
                counts,
                amount + base * i128::from(top_up),
                top_up,
                daily,
                weekly,
            );
            weekly_prior += paid;
            priced
        })
        .collect();
    finish_week(shifts, request.bonus, weekly_prior)
}

fn paid_window(row: &Shift) -> (i64, i64, i64) {
    let duration = shift_duration(row);
    let unpaid = row.break_minutes * i64::from(duration > 360);
    let paid = duration - unpaid;
    (unpaid, paid, i64::from(row.callout) * (180 - paid).max(0))
}

fn finish_week(mut shifts: Vec<PricedShift>, bonus: bool, weekly_paid: i64) -> Outcome {
    if bonus && weekly_paid >= 600 {
        let last = shifts.last_mut().unwrap();
        last.row.bonus_cents = 500;
        last.row.cents = ((2 * (last.row.cents as i128 * 60 + 500 * 60) + 60) / 120) as i64;
    }
    let active = rule_flags(&shifts);
    assemble_quote(shifts, weekly_paid, active)
}

fn priced_row(
    row: &Shift,
    paid: i64,
    counts: [i64; 5],
    amount: i128,
    top_up: i64,
    daily_overtime: bool,
    weekly_overtime: bool,
) -> PricedShift {
    PricedShift {
        row: PayShift {
            day: row.day,
            start: row.start,
            end: row.end,
            paid_minutes: paid,
            regular_minutes: counts[0],
            overtime_minutes: counts[1],
            night_minutes: counts[2],
            weekend_minutes: counts[3],
            holiday_minutes: counts[4],
            callout_minutes: top_up,
            bonus_cents: 0,
            cents: ((2 * amount + 60) / 120) as i64,
        },
        daily_overtime,
        weekly_overtime,
    }
}

fn price_minutes(
    row: &Shift,
    base: i128,
    weekly_prior: i64,
    unpaid: i64,
    paid: i64,
) -> ([i64; 5], i128, bool, bool) {
    let mut counts = [0_i64; 5];
    let mut amount = 0_i128;
    for worked in 0..paid {
        let (day, clock) = minute_position(row, unpaid, worked);
        let (overtime, night, weekend) = minute_flags(worked, weekly_prior, day, clock);
        amount += minute_rate(base, overtime, night, weekend, row.holiday);
        record_minute(&mut counts, overtime, night, weekend, row.holiday);
    }
    (counts, amount, paid > 480, weekly_prior + paid > 2400)
}

fn minute_flags(worked: i64, weekly_prior: i64, day: i64, clock: i64) -> (bool, bool, bool) {
    (
        worked >= 480 || weekly_prior + worked >= 2400,
        clock >= 1320 || clock < 360,
        day >= 5,
    )
}

fn record_minute(counts: &mut [i64; 5], overtime: bool, night: bool, weekend: bool, holiday: bool) {
    counts[usize::from(overtime)] += 1;
    counts[2] += i64::from(night);
    counts[3] += i64::from(weekend);
    counts[4] += i64::from(holiday);
}

fn minute_position(row: &Shift, unpaid: i64, worked: i64) -> (i64, i64) {
    let minute = row.day * 1440 + row.start + unpaid + worked;
    (
        minute.div_euclid(1440).rem_euclid(7),
        minute.rem_euclid(1440),
    )
}

fn minute_rate(base: i128, overtime: bool, night: bool, weekend: bool, holiday: bool) -> i128 {
    base + base * i128::from(overtime) / 2
        + base * i128::from(night) / 5
        + base * i128::from(weekend) / 4
        + base * i128::from(holiday)
}

fn assemble_quote(shifts: Vec<PricedShift>, weekly_paid: i64, active: [bool; 7]) -> Outcome {
    let applied = RULE_NAMES
        .into_iter()
        .zip(active)
        .filter_map(|(name, active)| active.then(|| name.to_string()))
        .collect();
    let weekly_cents = shifts.iter().map(|row| row.row.cents).sum();
    Outcome::Quote(Quote {
        shifts: shifts.into_iter().map(|row| row.row).collect(),
        weekly_paid_minutes: weekly_paid,
        weekly_cents,
        applied,
    })
}

fn rule_flags(shifts: &[PricedShift]) -> [bool; 7] {
    let mut active = [false; 7];
    for row in shifts {
        active[0] |= row.daily_overtime;
        active[1] |= row.weekly_overtime;
        active[2] |= row.row.night_minutes > 0;
        active[3] |= row.row.weekend_minutes > 0;
        active[4] |= row.row.holiday_minutes > 0;
        active[5] |= row.row.callout_minutes > 0;
        active[6] |= row.row.bonus_cents > 0;
    }
    active
}
