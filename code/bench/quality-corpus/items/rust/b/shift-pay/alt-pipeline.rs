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
    finish(price_week(request, base), request.bonus)
}
fn request_base(request: &Request) -> Result<i128, Outcome> {
    let base = match request.role.trim().to_ascii_lowercase().as_str() {
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
        code: code.into(),
        index,
    }
}
fn validate_shifts(shifts: &[Shift]) -> Result<Vec<Interval>, (&'static str, usize)> {
    shifts
        .iter()
        .enumerate()
        .map(|(index, row)| {
            let duration = validate_shift(row, index)?;
            Ok(Interval {
                index,
                start: row.day * 1440 + row.start,
                duration,
            })
        })
        .collect()
}
fn validate_shift(row: &Shift, index: usize) -> Result<i64, (&'static str, usize)> {
    validate_clock(row, index)?;
    let span = (row.end - row.start).rem_euclid(1440);
    let duration = if span == 0 { 1440 } else { span };
    if !(1..=960).contains(&duration) {
        return Err(("BAD_LENGTH", index));
    }
    if row.break_minutes > duration {
        return Err(("BREAK_TOO_LONG", index));
    }
    Ok(duration)
}
fn validate_clock(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    for (ok, code) in [
        ((0..=6).contains(&row.day), "BAD_DAY"),
        ((0..=1439).contains(&row.start), "BAD_START"),
        ((0..=1439).contains(&row.end), "BAD_END"),
        ((0..=240).contains(&row.break_minutes), "BAD_BREAK"),
    ] {
        if !ok {
            return Err((code, index));
        }
    }
    Ok(())
}
fn overlap_error(intervals: &[Interval]) -> Option<usize> {
    intervals
        .iter()
        .enumerate()
        .flat_map(|(i, left)| {
            intervals.iter().skip(i + 1).flat_map(move |right| {
                [-10080_i64, 0, 10080]
                    .into_iter()
                    .filter_map(move |offset| {
                        let start = left.start.max(right.start + offset);
                        let end =
                            (left.start + left.duration).min(right.start + offset + right.duration);
                        (start < end).then_some((start, right.index))
                    })
            })
        })
        .min()
        .map(|(_, index)| index)
}
fn price_week(request: &Request, base: i128) -> Vec<PricedShift> {
    request
        .shifts
        .iter()
        .scan(0_i64, |prior, row| {
            let (_, paid) = paid_minutes(row);
            let item = price_shift(row, base, *prior, paid);
            *prior += paid;
            Some(item)
        })
        .collect()
}
fn paid_minutes(row: &Shift) -> (i64, i64) {
    let span = (row.end - row.start).rem_euclid(1440);
    let duration = if span == 0 { 1440 } else { span };
    (
        duration,
        duration - row.break_minutes * i64::from(duration > 360),
    )
}
fn price_shift(row: &Shift, base: i128, prior: i64, paid: i64) -> PricedShift {
    let (duration, _) = paid_minutes(row);
    let flags: Vec<[bool; 4]> = (0..paid)
        .map(|offset| minute_flags(row, prior, duration - paid, offset))
        .collect();
    let amount = flags.iter().map(|f| minute_amount(base, *f)).sum();
    PricedShift {
        row: make_pay_row(row, paid, count_minutes(&flags), amount, base),
        daily_overtime: paid > 480,
        weekly_overtime: prior + paid > 2400,
    }
}
fn make_pay_row(row: &Shift, paid: i64, totals: [i64; 5], amount: i128, base: i128) -> PayShift {
    let callout = if row.callout { (180 - paid).max(0) } else { 0 };
    PayShift {
        day: row.day,
        start: row.start,
        end: row.end,
        paid_minutes: paid,
        regular_minutes: totals[0],
        overtime_minutes: totals[1],
        night_minutes: totals[2],
        weekend_minutes: totals[3],
        holiday_minutes: totals[4],
        callout_minutes: callout,
        bonus_cents: 0,
        cents: ((2 * (amount + base * i128::from(callout)) + 60) / 120) as i64,
    }
}
fn minute_flags(row: &Shift, prior: i64, unpaid: i64, offset: i64) -> [bool; 4] {
    let absolute = row.day * 1440 + row.start + unpaid + offset;
    let clock = absolute.rem_euclid(1440);
    [
        offset >= 480 || prior + offset >= 2400,
        clock >= 1320 || clock < 360,
        absolute.div_euclid(1440).rem_euclid(7) >= 5,
        row.holiday,
    ]
}
fn count_minutes(minutes: &[[bool; 4]]) -> [i64; 5] {
    let mut totals = [0_i64; 5];
    for flags in minutes {
        totals[usize::from(flags[0])] += 1;
        for (slot, enabled) in flags[1..].iter().enumerate() {
            totals[slot + 2] += i64::from(*enabled);
        }
    }
    totals
}
fn minute_amount(base: i128, flags: [bool; 4]) -> i128 {
    base + base * i128::from(flags[0]) / 2
        + base * i128::from(flags[1]) / 5
        + base * i128::from(flags[2]) / 4
        + base * i128::from(flags[3])
}
fn finish(mut rows: Vec<PricedShift>, bonus: bool) -> Outcome {
    let paid = rows.iter().map(|r| r.row.paid_minutes).sum();
    add_bonus(&mut rows, bonus, paid);
    let applied = applied_rules(&rows);
    let cents = rows.iter().map(|r| r.row.cents).sum();
    Outcome::Quote(Quote {
        shifts: rows.into_iter().map(|r| r.row).collect(),
        weekly_paid_minutes: paid,
        weekly_cents: cents,
        applied,
    })
}
fn add_bonus(rows: &mut [PricedShift], bonus: bool, paid: i64) {
    if bonus && paid >= 600 {
        if let Some(last) = rows.last_mut() {
            last.row.bonus_cents = 500;
            last.row.cents = ((2 * (i128::from(last.row.cents) * 60 + 30000) + 60) / 120) as i64;
        }
    }
}
fn applied_rules(rows: &[PricedShift]) -> Vec<String> {
    RULE_NAMES
        .iter()
        .zip(rule_flags(rows))
        .filter_map(|(name, used)| used.then(|| (*name).to_string()))
        .collect()
}
fn rule_flags(rows: &[PricedShift]) -> [bool; 7] {
    [
        rows.iter().any(|r| r.daily_overtime),
        rows.iter().any(|r| r.weekly_overtime),
        rows.iter().any(|r| r.row.night_minutes > 0),
        rows.iter().any(|r| r.row.weekend_minutes > 0),
        rows.iter().any(|r| r.row.holiday_minutes > 0),
        rows.iter().any(|r| r.row.callout_minutes > 0),
        rows.iter().any(|r| r.row.bonus_cents > 0),
    ]
}
