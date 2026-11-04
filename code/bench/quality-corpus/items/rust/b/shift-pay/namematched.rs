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

struct WorkTotals {
    amount: i128,
    counts: [i64; 5],
    daily: bool,
    weekly: bool,
}

struct RowData {
    day: i64,
    start: i64,
    end: i64,
    paid: i64,
    counts: [i64; 5],
    extra: i64,
    cents: i64,
}

struct WorkPlan<'a> {
    shift: &'a Shift,
    base: i128,
    prior: i64,
    paid: i64,
    unpaid: i64,
}

/// Return ordered shift pay rows or the first contract validation error.
#[rustfmt::skip]
pub fn solution(request: &Request) -> Outcome {
    let base = match validate_request(request) { Ok(rate) => rate, Err(error) => return error };
    let (mut rows, paid) = price_all_shifts(&request.shifts, base);
    if request.bonus && paid >= 600 { apply_weekly_bonus(&mut rows); }
    assemble_weekly_quote(rows, paid)
}

#[rustfmt::skip]
fn validate_request(request: &Request) -> Result<i128, Outcome> {
    let Some(base) = base_rate_for_role(&request.role) else {
        return Err(error_outcome("BAD_ROLE", None));
    };
    if let Some(error) = validate_week_request(request) { return Err(error); }
    if let Some(error) = validate_shift_overlaps(request) { return Err(error); }
    Ok(base)
}

fn validate_shift_overlaps(request: &Request) -> Option<Outcome> {
    let intervals = match validate_all_shifts(&request.shifts) {
        Ok(rows) => rows,
        Err((code, index)) => return Some(error_outcome(code, Some(index))),
    };
    overlap_index(&intervals).map(|index| error_outcome("OVERLAP", Some(index)))
}

fn error_outcome(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.to_string(),
        index,
    }
}

fn base_rate_for_role(role: &str) -> Option<i128> {
    match role.trim().to_ascii_lowercase().as_str() {
        "helper" => Some(1800),
        "nurse" => Some(2400),
        "lead" => Some(3000),
        _ => None,
    }
}

fn validate_week_request(request: &Request) -> Option<Outcome> {
    if request.shifts.is_empty() {
        return Some(error_outcome("EMPTY_WEEK", None));
    }
    if request.shifts.len() > 14 {
        return Some(error_outcome("TOO_MANY_SHIFTS", None));
    }
    None
}

fn validate_all_shifts(shifts: &[Shift]) -> Result<Vec<Interval>, (&'static str, usize)> {
    shifts
        .iter()
        .enumerate()
        .map(|(i, row)| validate_one_shift(row, i))
        .collect()
}

fn validate_one_shift(row: &Shift, index: usize) -> Result<Interval, (&'static str, usize)> {
    validate_clock_fields(row, index)?;
    let duration = check_shift_span(row, index)?;
    Ok(Interval {
        index,
        start: absolute_shift_start(row),
        duration,
    })
}

fn validate_clock_fields(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    validate_day_and_start(row, index)?;
    validate_end_and_break(row, index)?;
    Ok(())
}

fn validate_day_and_start(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    day_is_valid(row.day).map_err(|code| (code, index))?;
    start_is_valid(row.start).map_err(|code| (code, index))
}

fn validate_end_and_break(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    end_is_valid(row.end).map_err(|code| (code, index))?;
    break_is_valid(row.break_minutes).map_err(|code| (code, index))
}

fn check_shift_span(row: &Shift, index: usize) -> Result<i64, (&'static str, usize)> {
    let duration = duration_minutes(row);
    duration_and_break_valid(duration, row.break_minutes).map_err(|code| (code, index))?;
    Ok(duration)
}

fn day_is_valid(day: i64) -> Result<(), &'static str> {
    (0..=6).contains(&day).then_some(()).ok_or("BAD_DAY")
}

fn start_is_valid(start: i64) -> Result<(), &'static str> {
    (0..=1439).contains(&start).then_some(()).ok_or("BAD_START")
}

fn end_is_valid(end: i64) -> Result<(), &'static str> {
    (0..=1439).contains(&end).then_some(()).ok_or("BAD_END")
}

fn break_is_valid(minutes: i64) -> Result<(), &'static str> {
    (0..=240)
        .contains(&minutes)
        .then_some(())
        .ok_or("BAD_BREAK")
}

fn duration_minutes(row: &Shift) -> i64 {
    clock_duration(row.start, row.end)
}

fn clock_duration(start: i64, end: i64) -> i64 {
    (end - start).rem_euclid(1440).max(1) + i64::from(end == start) * 1439
}

fn duration_and_break_valid(duration: i64, unpaid: i64) -> Result<(), &'static str> {
    if !(1..=960).contains(&duration) {
        return Err("BAD_LENGTH");
    }
    if unpaid > duration {
        return Err("BREAK_TOO_LONG");
    }
    Ok(())
}

fn absolute_shift_start(row: &Shift) -> i64 {
    absolute_minute(row.day, row.start)
}

fn absolute_minute(day: i64, start: i64) -> i64 {
    day * 1440 + start
}

fn overlap_index(intervals: &[Interval]) -> Option<usize> {
    earliest_overlap(intervals).map(|(_, index)| index)
}

fn earliest_overlap(intervals: &[Interval]) -> Option<(i64, usize)> {
    let mut earliest = None;
    for left in 0..intervals.len() {
        earliest = earlier_collision(earliest, overlap_after_index(intervals, left));
    }
    earliest
}

fn overlap_after_index(intervals: &[Interval], left: usize) -> Option<(i64, usize)> {
    (left + 1..intervals.len())
        .filter_map(|right| earliest_collision(&intervals[left], &intervals[right]))
        .min()
}

fn earliest_collision(a: &Interval, b: &Interval) -> Option<(i64, usize)> {
    [-10080, 0, 10080]
        .into_iter()
        .filter_map(|offset| collision_start(a, b, offset))
        .min()
}

fn collision_start(a: &Interval, b: &Interval, offset: i64) -> Option<(i64, usize)> {
    let start = a.start.max(b.start + offset);
    let end = (a.start + a.duration).min(b.start + offset + b.duration);
    (start < end).then_some((start, b.index))
}

fn earlier_collision(old: Option<(i64, usize)>, new: Option<(i64, usize)>) -> Option<(i64, usize)> {
    old.into_iter().chain(new).min()
}

fn price_all_shifts(shifts: &[Shift], base: i128) -> (Vec<PricedShift>, i64) {
    let mut paid = 0;
    let mut rows = Vec::with_capacity(shifts.len());
    for row in shifts {
        let priced = price_one_shift(row, base, paid);
        paid += priced.row.paid_minutes;
        rows.push(priced);
    }
    (rows, paid)
}

fn price_one_shift(row: &Shift, base: i128, prior: i64) -> PricedShift {
    let (paid, work) = calculate_shift_work(row, base, prior);
    finish_shift_price(row, base, paid, work)
}

fn finish_shift_price(row: &Shift, base: i128, paid: i64, work: WorkTotals) -> PricedShift {
    let extra = callout_top_up(row.callout, paid);
    let amount = work.amount + base * i128::from(extra);
    PricedShift {
        row: assemble_pay_shift(row, paid, work.counts, extra, amount),
        daily_overtime: work.daily,
        weekly_overtime: work.weekly,
    }
}

#[rustfmt::skip]
fn calculate_shift_work(row: &Shift, base: i128, prior: i64) -> (i64, WorkTotals) {
    let (paid, unpaid) = paid_work_interval(row);
    let plan = WorkPlan { shift: row, base, prior, paid, unpaid };
    (paid, total_worked_pay(plan))
}

fn paid_work_interval(row: &Shift) -> (i64, i64) {
    let duration = duration_minutes(row);
    let unpaid = if duration > 360 { row.break_minutes } else { 0 };
    (duration - unpaid, unpaid)
}

fn total_worked_pay(plan: WorkPlan<'_>) -> WorkTotals {
    let mut totals = blank_work_totals();
    for worked in 0..plan.paid {
        record_paid_minute(&plan, worked, &mut totals);
    }
    totals
}

fn blank_work_totals() -> WorkTotals {
    WorkTotals {
        amount: 0,
        counts: [0; 5],
        daily: false,
        weekly: false,
    }
}

fn record_paid_minute(plan: &WorkPlan<'_>, worked: i64, totals: &mut WorkTotals) {
    let flags = classify_paid_minute(plan, worked);
    count_worked_minutes(totals, flags);
    count_clock_premiums(totals, flags);
    record_overtime_thresholds(totals, flags);
    totals.amount += minute_pay_amount(plan.base, flags);
}

fn classify_paid_minute(plan: &WorkPlan<'_>, worked: i64) -> (bool, bool, bool, bool, bool) {
    let (minute, day) = absolute_worked_minute(plan.shift, worked, plan.unpaid);
    (
        worked >= 480,
        plan.prior + worked >= 2400,
        is_night_minute(minute),
        is_weekend_day(day),
        plan.shift.holiday,
    )
}

fn count_worked_minutes(totals: &mut WorkTotals, flags: (bool, bool, bool, bool, bool)) {
    totals.counts[usize::from(flags.0 || flags.1)] += 1;
}

fn count_clock_premiums(totals: &mut WorkTotals, flags: (bool, bool, bool, bool, bool)) {
    totals.counts[2] += i64::from(flags.2);
    totals.counts[3] += i64::from(flags.3);
    totals.counts[4] += i64::from(flags.4);
}

fn record_overtime_thresholds(totals: &mut WorkTotals, flags: (bool, bool, bool, bool, bool)) {
    totals.daily |= flags.0;
    totals.weekly |= flags.1;
}

fn absolute_worked_minute(row: &Shift, worked: i64, unpaid: i64) -> (i64, i64) {
    let absolute = row.day * 1440 + row.start + unpaid + worked;
    (
        absolute.rem_euclid(1440),
        absolute.div_euclid(1440).rem_euclid(7),
    )
}

fn is_night_minute(clock: i64) -> bool {
    clock >= 1320 || clock < 360
}

fn is_weekend_day(day: i64) -> bool {
    day.rem_euclid(7) >= 5
}

fn minute_pay_amount(base: i128, flags: (bool, bool, bool, bool, bool)) -> i128 {
    base + base * i128::from(flags.0 || flags.1) / 2
        + base * i128::from(flags.2) / 5
        + base * i128::from(flags.3) / 4
        + base * i128::from(flags.4)
}

fn callout_top_up(callout: bool, paid: i64) -> i64 {
    callout_extra_minutes(callout, paid)
}

fn callout_extra_minutes(callout: bool, paid: i64) -> i64 {
    if callout {
        (180 - paid).max(0)
    } else {
        0
    }
}

#[rustfmt::skip]
fn assemble_pay_shift(
    row: &Shift, paid: i64, totals: [i64; 5], extra: i64, exact: i128
) -> PayShift {
    let cents = round_amount(exact);
    build_pay_shift(pay_shift_data(row, paid, totals, extra, cents))
}

#[rustfmt::skip]
fn pay_shift_data(row: &Shift, paid: i64, counts: [i64; 5], extra: i64, cents: i64) -> RowData {
    RowData { day: row.day, start: row.start, end: row.end, paid, counts, extra, cents }
}

#[rustfmt::skip]
fn build_pay_shift(data: RowData) -> PayShift {
    let RowData { day, start, end, paid, counts, extra, cents } = data;
    let [regular_minutes, overtime_minutes, night_minutes, weekend_minutes, holiday_minutes] =
        counts;
    PayShift {
        day, start, end, paid_minutes: paid, regular_minutes, overtime_minutes,
        night_minutes, weekend_minutes, holiday_minutes, callout_minutes: extra,
        bonus_cents: 0, cents,
    }
}

fn round_amount(amount: i128) -> i64 {
    half_up_to_cents(amount, 60)
}

fn half_up_to_cents(numerator: i128, denominator: i128) -> i64 {
    ((2 * numerator + denominator) / (2 * denominator)) as i64
}

fn apply_weekly_bonus(rows: &mut [PricedShift]) {
    let last = rows.last_mut().unwrap();
    last.row.bonus_cents = 500;
    last.row.cents += 500;
}

fn assemble_weekly_quote(rows: Vec<PricedShift>, paid: i64) -> Outcome {
    let applied = collect_applied_rules(&rows);
    let cents = sum_shift_cents(&rows);
    Outcome::Quote(Quote {
        shifts: rows.into_iter().map(|row| row.row).collect(),
        weekly_paid_minutes: paid,
        weekly_cents: cents,
        applied,
    })
}

fn sum_shift_cents(rows: &[PricedShift]) -> i64 {
    rows.iter().map(|row| row.row.cents).sum()
}

fn collect_applied_rules(rows: &[PricedShift]) -> Vec<String> {
    let mut names = Vec::new();
    collect_overtime_rules(&mut names, rows);
    collect_premium_rules(&mut names, rows);
    collect_extra_rules(&mut names, rows);
    names
}

fn collect_overtime_rules(names: &mut Vec<String>, rows: &[PricedShift]) {
    append_active_rule(names, has_daily_overtime(rows), "daily-overtime");
    append_active_rule(names, has_weekly_overtime(rows), "weekly-overtime");
}

fn collect_premium_rules(names: &mut Vec<String>, rows: &[PricedShift]) {
    append_active_rule(names, has_positive_shift_count(rows, 2), "night-premium");
    append_active_rule(names, has_positive_shift_count(rows, 3), "weekend-premium");
    append_active_rule(names, has_positive_shift_count(rows, 4), "holiday-rate");
}

fn collect_extra_rules(names: &mut Vec<String>, rows: &[PricedShift]) {
    append_active_rule(names, has_positive_shift_count(rows, 5), "callout-minimum");
    append_active_rule(names, has_positive_shift_count(rows, 6), "bonus");
}

fn append_active_rule(names: &mut Vec<String>, active: bool, name: &str) {
    if active {
        names.push(name.to_string());
    }
}

fn has_daily_overtime(rows: &[PricedShift]) -> bool {
    rows.iter().any(|row| row.daily_overtime)
}

fn has_weekly_overtime(rows: &[PricedShift]) -> bool {
    rows.iter().any(|row| row.weekly_overtime)
}

fn has_positive_shift_count(rows: &[PricedShift], field: usize) -> bool {
    rows.iter().any(|row| match field {
        2 => row.row.night_minutes > 0,
        3 => row.row.weekend_minutes > 0,
        4 => row.row.holiday_minutes > 0,
        5 => row.row.callout_minutes > 0,
        _ => row.row.bonus_cents > 0,
    })
}
