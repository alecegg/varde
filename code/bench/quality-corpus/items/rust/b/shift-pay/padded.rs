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
    exact_amount: i128,
    daily_overtime: bool,
    weekly_overtime: bool,
}

struct WorkTotals {
    regular: i64,
    overtime: i64,
    night: i64,
    weekend: i64,
    holiday: i64,
    amount: i128,
}

struct MinuteFlags {
    overtime: bool,
    night: bool,
    weekend: bool,
}

/// Return ordered shift pay rows or the first contract validation error.
pub fn solution(request: &Request) -> Outcome {
    let Some(base) = role_rate(&request.role) else {
        return failure("BAD_ROLE", None);
    };
    if let Some(error) = check_request(request) {
        return failure(error, None);
    }
    let intervals = match validate_week(&request.shifts) {
        Ok(validated) => validated,
        Err((code, index)) => return failure(code, Some(index)),
    };
    if let Some(index) = overlap_error(&intervals) {
        return failure("OVERLAP", Some(index));
    }
    let (priced, weekly_paid, applied) = price_week(request, base);
    assemble_quote(priced, weekly_paid, applied)
}

fn role_rate(input_role: &str) -> Option<i128> {
    let trimmed_role = input_role.trim();
    let normalized_role = trimmed_role.to_ascii_lowercase();
    match normalized_role.as_str() {
        "helper" => Some(1800_i128),
        "nurse" => Some(2400_i128),
        "lead" => Some(3000_i128),
        _ => None,
    }
}

fn check_request(request: &Request) -> Option<&'static str> {
    let no_shifts = request.shifts.is_empty();
    if no_shifts {
        return Some("EMPTY_WEEK");
    }
    let too_many_shifts = request.shifts.len() > 14;
    if too_many_shifts {
        return Some("TOO_MANY_SHIFTS");
    }
    None
}

fn check_clock_fields(row: &Shift, index: usize) -> Option<(&'static str, usize)> {
    let fields = [
        (row.day, 6, "BAD_DAY"),
        (row.start, 1439, "BAD_START"),
        (row.end, 1439, "BAD_END"),
        (row.break_minutes, 240, "BAD_BREAK"),
    ];
    for (value, maximum, code) in fields {
        if value < 0 || value > maximum {
            return Some((code, index));
        }
    }
    None
}

fn shift_duration(row: &Shift) -> i64 {
    let clock_span = (row.end - row.start).rem_euclid(1440);
    if clock_span == 0 {
        1440
    } else {
        clock_span
    }
}

fn check_length(duration: i64, index: usize) -> Option<(&'static str, usize)> {
    if !(1..=960).contains(&duration) {
        return Some(("BAD_LENGTH", index));
    }
    None
}

fn check_break_length(row: &Shift, duration: i64, index: usize) -> Option<(&'static str, usize)> {
    if row.break_minutes > duration {
        return Some(("BREAK_TOO_LONG", index));
    }
    None
}

fn validate_week(shifts: &[Shift]) -> Result<Vec<Interval>, (&'static str, usize)> {
    let mut intervals = Vec::with_capacity(shifts.len());
    for (index, row) in shifts.iter().enumerate() {
        let duration = shift_duration(row);
        let problem = check_clock_fields(row, index)
            .or_else(|| check_length(duration, index))
            .or_else(|| check_break_length(row, duration, index));
        if let Some(problem) = problem {
            return Err(problem);
        }
        intervals.push(Interval {
            index,
            start: row.day * 1440 + row.start,
            duration,
        });
    }
    Ok(intervals)
}

fn overlap_start(left: &Interval, right: &Interval, offset: i64) -> Option<i64> {
    let right_start = right.start + offset;
    let beginning = left.start.max(right_start);
    let left_end = left.start + left.duration;
    let right_end = right_start + right.duration;
    if beginning < left_end.min(right_end) {
        Some(beginning)
    } else {
        None
    }
}

fn overlap_error(intervals: &[Interval]) -> Option<usize> {
    let mut collisions = Vec::new();
    for left_position in 0..intervals.len() {
        for right_position in (left_position + 1)..intervals.len() {
            let left = &intervals[left_position];
            let right = &intervals[right_position];
            for offset in [-10080_i64, 0, 10080] {
                if let Some(beginning) = overlap_start(left, right, offset) {
                    collisions.push((beginning, right.index));
                }
            }
        }
    }
    collisions.into_iter().min().map(|(_, index)| index)
}

fn minute_flags(absolute_minute: i64, offset: i64, weekly_prior: i64) -> MinuteFlags {
    let local_day = absolute_minute.div_euclid(1440).rem_euclid(7);
    let local_clock = absolute_minute.rem_euclid(1440);
    let daily_overtime = offset >= 480;
    let weekly_overtime = weekly_prior + offset >= 2400;
    let overtime = daily_overtime || weekly_overtime;
    let night = local_clock >= 1320 || local_clock < 360;
    let weekend = local_day >= 5;
    MinuteFlags {
        overtime,
        night,
        weekend,
    }
}

fn minute_rate(base: i128, flags: &MinuteFlags, holiday: bool) -> i128 {
    let overtime_addition = if flags.overtime { base / 2 } else { 0 };
    let night_addition = if flags.night { base / 5 } else { 0 };
    let weekend_addition = if flags.weekend { base / 4 } else { 0 };
    let holiday_addition = if holiday { base } else { 0 };
    base + overtime_addition + night_addition + weekend_addition + holiday_addition
}

fn add_worked_minute(totals: &mut WorkTotals, flags: &MinuteFlags, holiday: bool, base: i128) {
    if flags.overtime {
        totals.overtime += 1;
    } else {
        totals.regular += 1;
    }
    if flags.night {
        totals.night += 1;
    }
    if flags.weekend {
        totals.weekend += 1;
    }
    if holiday {
        totals.holiday += 1;
    }
    totals.amount += minute_rate(base, flags, holiday);
}

fn price_worked_minutes(
    row: &Shift,
    base: i128,
    prior: i64,
    paid_start: i64,
    paid: i64,
) -> WorkTotals {
    let mut totals = WorkTotals {
        regular: 0,
        overtime: 0,
        night: 0,
        weekend: 0,
        holiday: 0,
        amount: 0,
    };
    for offset in 0..paid {
        let absolute = paid_start + offset;
        let flags = minute_flags(absolute, offset, prior);
        add_worked_minute(&mut totals, &flags, row.holiday, base);
    }
    totals
}

fn pay_shift_record(row: &Shift, paid: i64, totals: &WorkTotals, callout: i64) -> PayShift {
    let cents = ((2 * totals.amount + 60) / 120) as i64;
    PayShift {
        day: row.day,
        start: row.start,
        end: row.end,
        paid_minutes: paid,
        regular_minutes: totals.regular,
        overtime_minutes: totals.overtime,
        night_minutes: totals.night,
        weekend_minutes: totals.weekend,
        holiday_minutes: totals.holiday,
        callout_minutes: callout,
        bonus_cents: 0,
        cents,
    }
}

fn price_shift(row: &Shift, base: i128, weekly_prior: i64) -> PricedShift {
    let duration = shift_duration(row);
    let unpaid = if duration > 360 { row.break_minutes } else { 0 };
    let paid = duration - unpaid;
    let paid_start = row.day * 1440 + row.start + unpaid;
    let mut totals = price_worked_minutes(row, base, weekly_prior, paid_start, paid);
    let callout_minutes = if row.callout && paid < 180 {
        180 - paid
    } else {
        0
    };
    totals.amount += base * i128::from(callout_minutes);
    PricedShift {
        row: pay_shift_record(row, paid, &totals, callout_minutes),
        exact_amount: totals.amount,
        daily_overtime: paid > 480,
        weekly_overtime: weekly_prior + paid > 2400,
    }
}

fn collect_applied(active: &mut [bool; 7], priced: &PricedShift) {
    active[0] |= priced.daily_overtime;
    active[1] |= priced.weekly_overtime;
    active[2] |= priced.row.night_minutes > 0;
    active[3] |= priced.row.weekend_minutes > 0;
    active[4] |= priced.row.holiday_minutes > 0;
    active[5] |= priced.row.callout_minutes > 0;
    active[6] |= priced.row.bonus_cents > 0;
}

fn apply_weekly_bonus(rows: &mut [PricedShift], weekly_paid: i64, requested: bool) -> bool {
    if !requested || weekly_paid < 600 {
        return false;
    }
    if let Some(last) = rows.last_mut() {
        last.row.bonus_cents = 500;
        last.exact_amount += 500 * 60;
        last.row.cents = ((2 * last.exact_amount + 60) / 120) as i64;
        return true;
    }
    false
}

fn price_week(request: &Request, base: i128) -> (Vec<PricedShift>, i64, [bool; 7]) {
    let mut rows = Vec::with_capacity(request.shifts.len());
    let mut weekly_paid = 0_i64;
    let mut applied = [false; 7];
    for shift in &request.shifts {
        let priced = price_shift(shift, base, weekly_paid);
        weekly_paid += priced.row.paid_minutes;
        collect_applied(&mut applied, &priced);
        rows.push(priced);
    }
    applied[6] |= apply_weekly_bonus(&mut rows, weekly_paid, request.bonus);
    (rows, weekly_paid, applied)
}

fn applied_names(active: [bool; 7]) -> Vec<String> {
    let names = [
        "daily-overtime",
        "weekly-overtime",
        "night-premium",
        "weekend-premium",
        "holiday-rate",
        "callout-minimum",
        "bonus",
    ];
    let mut applied = Vec::new();
    for (position, name) in names.iter().enumerate() {
        if active[position] {
            applied.push((*name).to_string());
        }
    }
    applied
}

fn assemble_quote(rows: Vec<PricedShift>, weekly_paid: i64, active: [bool; 7]) -> Outcome {
    let applied = applied_names(active);
    let weekly_cents = rows.iter().map(|priced| priced.row.cents).sum();
    let shifts = rows.into_iter().map(|priced| priced.row).collect();
    Outcome::Quote(Quote {
        shifts,
        weekly_paid_minutes: weekly_paid,
        weekly_cents,
        applied,
    })
}

fn failure(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.to_string(),
        index,
    }
}
