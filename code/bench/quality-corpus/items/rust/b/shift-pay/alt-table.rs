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

#[derive(Clone, Copy)]
enum Signal {
    Daily,
    Weekly,
    Night,
    Weekend,
    Holiday,
    Callout,
    Bonus,
}
#[derive(Clone, Copy)]
struct Rule {
    signal: Signal,
    numerator: i128,
    denominator: i128,
    label: &'static str,
}
const RULES: [Rule; 7] = [
    Rule {
        signal: Signal::Daily,
        numerator: 0,
        denominator: 1,
        label: "daily-overtime",
    },
    Rule {
        signal: Signal::Weekly,
        numerator: 0,
        denominator: 1,
        label: "weekly-overtime",
    },
    Rule {
        signal: Signal::Night,
        numerator: 1,
        denominator: 5,
        label: "night-premium",
    },
    Rule {
        signal: Signal::Weekend,
        numerator: 1,
        denominator: 4,
        label: "weekend-premium",
    },
    Rule {
        signal: Signal::Holiday,
        numerator: 1,
        denominator: 1,
        label: "holiday-rate",
    },
    Rule {
        signal: Signal::Callout,
        numerator: 0,
        denominator: 1,
        label: "callout-minimum",
    },
    Rule {
        signal: Signal::Bonus,
        numerator: 0,
        denominator: 1,
        label: "bonus",
    },
];
const FIELDS: [(i64, i64, &str); 4] = [
    (0, 6, "BAD_DAY"),
    (0, 1439, "BAD_START"),
    (0, 1439, "BAD_END"),
    (0, 240, "BAD_BREAK"),
];
struct Interval {
    index: usize,
    start: i64,
    duration: i64,
}
type Facts = [bool; 7];
struct PricedShift {
    row: PayShift,
    daily_overtime: bool,
    weekly_overtime: bool,
}
pub fn solution(request: &Request) -> Outcome {
    let base = match request_base(request) {
        Ok(v) => v,
        Err(e) => return e,
    };
    let intervals = match validate_shifts(&request.shifts) {
        Ok(v) => v,
        Err((code, index)) => return failure(code, Some(index)),
    };
    if let Some(index) = overlap_error(&intervals) {
        return failure("OVERLAP", Some(index));
    }
    complete(quote_week(request, base), request.bonus)
}
fn request_base(request: &Request) -> Result<i128, Outcome> {
    let rate = match request.role.trim().to_ascii_lowercase().as_str() {
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
    Ok(rate)
}
fn failure(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn validate_shifts(shifts: &[Shift]) -> Result<Vec<Interval>, (&'static str, usize)> {
    let mut out = Vec::new();
    for (index, row) in shifts.iter().enumerate() {
        let duration = validate_shift(row, index)?;
        out.push(Interval {
            index,
            start: row.day * 1440 + row.start,
            duration,
        });
    }
    Ok(out)
}
fn validate_shift(row: &Shift, index: usize) -> Result<i64, (&'static str, usize)> {
    check_fields(row, index)?;
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
fn check_fields(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    for (value, (low, high, code)) in [row.day, row.start, row.end, row.break_minutes]
        .into_iter()
        .zip(FIELDS)
    {
        if !(low..=high).contains(&value) {
            return Err((code, index));
        }
    }
    Ok(())
}
fn overlap_error(rows: &[Interval]) -> Option<usize> {
    let mut conflicts = Vec::new();
    for left in 0..rows.len() {
        for right in left + 1..rows.len() {
            conflicts.extend(overlap_hits(&rows[left], &rows[right]));
        }
    }
    conflicts.into_iter().min().map(|(_, index)| index)
}
fn overlap_hits(a: &Interval, b: &Interval) -> Vec<(i64, usize)> {
    [-10080_i64, 0, 10080]
        .into_iter()
        .filter_map(|week| {
            let begins = a.start.max(b.start + week);
            let ends = (a.start + a.duration).min(b.start + week + b.duration);
            (begins < ends).then_some((begins, b.index))
        })
        .collect()
}
fn quote_week(request: &Request, base: i128) -> Vec<PricedShift> {
    let mut prior = 0;
    let mut priced = Vec::new();
    for row in &request.shifts {
        let current = price_shift(row, base, prior);
        prior += current.row.paid_minutes;
        priced.push(current);
    }
    priced
}
fn price_shift(row: &Shift, base: i128, prior: i64) -> PricedShift {
    let (span, paid) = paid_span(row);
    let mut result = blank_row(row, paid);
    let mut earned = 0;
    for worked in 0..paid {
        let facts = facts_at(row, prior, span - paid, worked);
        earned += minute_amount(base, &facts);
        record(&mut result, &facts);
    }
    finish_pay_row(&mut result, row, base, earned);
    PricedShift {
        row: result,
        daily_overtime: paid > 480,
        weekly_overtime: prior + paid > 2400,
    }
}
fn paid_span(row: &Shift) -> (i64, i64) {
    let raw_span = (row.end - row.start).rem_euclid(1440);
    let span = if raw_span == 0 { 1440 } else { raw_span };
    let unpaid = if span > 360 { row.break_minutes } else { 0 };
    (span, span - unpaid)
}
fn blank_row(row: &Shift, paid: i64) -> PayShift {
    PayShift {
        day: row.day,
        start: row.start,
        end: row.end,
        paid_minutes: paid,
        regular_minutes: 0,
        overtime_minutes: 0,
        night_minutes: 0,
        weekend_minutes: 0,
        holiday_minutes: 0,
        callout_minutes: 0,
        bonus_cents: 0,
        cents: 0,
    }
}
fn finish_pay_row(result: &mut PayShift, row: &Shift, base: i128, earned: i128) {
    let paid = result.paid_minutes;
    result.callout_minutes = if row.callout { (180 - paid).max(0) } else { 0 };
    result.cents = ((2 * (earned + base * i128::from(result.callout_minutes)) + 60) / 120) as i64;
}
fn facts_at(row: &Shift, prior: i64, unpaid: i64, worked: i64) -> Facts {
    let minute = row.day * 1440 + row.start + unpaid + worked;
    let clock = minute.rem_euclid(1440);
    [
        worked >= 480,
        prior + worked >= 2400,
        clock >= 1320 || clock < 360,
        minute.div_euclid(1440).rem_euclid(7) >= 5,
        row.holiday,
        false,
        false,
    ]
}
fn minute_amount(base: i128, f: &Facts) -> i128 {
    let mut amount = base;
    for rule in RULES {
        if f[rule.signal as usize] {
            amount += base * rule.numerator / rule.denominator;
        }
    }
    if f[Signal::Daily as usize] || f[Signal::Weekly as usize] {
        amount += base / 2;
    }
    amount
}
fn record(row: &mut PayShift, f: &Facts) {
    if f[Signal::Daily as usize] || f[Signal::Weekly as usize] {
        row.overtime_minutes += 1;
    } else {
        row.regular_minutes += 1;
    }
    row.night_minutes += i64::from(f[Signal::Night as usize]);
    row.weekend_minutes += i64::from(f[Signal::Weekend as usize]);
    row.holiday_minutes += i64::from(f[Signal::Holiday as usize]);
}
fn complete(mut rows: Vec<PricedShift>, bonus: bool) -> Outcome {
    let paid = rows.iter().map(|r| r.row.paid_minutes).sum();
    award_bonus(&mut rows, bonus, paid);
    let applied = active_rules(&rows);
    let cents = rows.iter().map(|r| r.row.cents).sum();
    Outcome::Quote(Quote {
        shifts: rows.into_iter().map(|r| r.row).collect(),
        weekly_paid_minutes: paid,
        weekly_cents: cents,
        applied,
    })
}
fn award_bonus(rows: &mut [PricedShift], bonus: bool, paid: i64) {
    if bonus && paid >= 600 {
        if let Some(last) = rows.last_mut() {
            last.row.bonus_cents = 500;
            last.row.cents = ((2 * (i128::from(last.row.cents) * 60 + 30000) + 60) / 120) as i64;
        }
    }
}
fn active_rules(rows: &[PricedShift]) -> Vec<String> {
    RULES
        .iter()
        .filter(|rule| rows.iter().any(|r| row_uses(rule.signal, r)))
        .map(|rule| rule.label.to_owned())
        .collect()
}
fn row_uses(signal: Signal, r: &PricedShift) -> bool {
    match signal {
        Signal::Daily => r.daily_overtime,
        Signal::Weekly => r.weekly_overtime,
        Signal::Night => r.row.night_minutes > 0,
        Signal::Weekend => r.row.weekend_minutes > 0,
        Signal::Holiday => r.row.holiday_minutes > 0,
        Signal::Callout => r.row.callout_minutes > 0,
        Signal::Bonus => r.row.bonus_cents > 0,
    }
}
