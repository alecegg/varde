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
struct PayEngine<'a> {
    request: &'a Request,
    base: i128,
    weekly_paid: i64,
    rows: Vec<PricedShift>,
    daily_seen: bool,
    weekly_seen: bool,
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
        Ok(rate) => rate,
        Err(error) => return error,
    };
    let intervals = match validate_shifts(&request.shifts) {
        Ok(rows) => rows,
        Err((code, index)) => return failure(code, Some(index)),
    };
    if let Some(index) = overlap_error(&intervals) {
        return failure("OVERLAP", Some(index));
    }
    PayEngine {
        request,
        base,
        weekly_paid: 0,
        rows: Vec::with_capacity(request.shifts.len()),
        daily_seen: false,
        weekly_seen: false,
    }
    .run()
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
    let mut result = Vec::with_capacity(shifts.len());
    for (index, row) in shifts.iter().enumerate() {
        let duration = validate_shift(row, index)?;
        result.push(Interval {
            index,
            start: row.day * 1440 + row.start,
            duration,
        });
    }
    Ok(result)
}
fn validate_shift(row: &Shift, index: usize) -> Result<i64, (&'static str, usize)> {
    check_fields(row, index)?;
    let duration = shift_duration(row);
    if !(1..=960).contains(&duration) {
        return Err(("BAD_LENGTH", index));
    }
    if row.break_minutes > duration {
        return Err(("BREAK_TOO_LONG", index));
    }
    Ok(duration)
}
fn check_fields(row: &Shift, index: usize) -> Result<(), (&'static str, usize)> {
    for (value, range, code) in [
        (row.day, 0..=6, "BAD_DAY"),
        (row.start, 0..=1439, "BAD_START"),
        (row.end, 0..=1439, "BAD_END"),
        (row.break_minutes, 0..=240, "BAD_BREAK"),
    ] {
        if !range.contains(&value) {
            return Err((code, index));
        }
    }
    Ok(())
}
fn shift_duration(row: &Shift) -> i64 {
    let span = (row.end - row.start).rem_euclid(1440);
    if span == 0 {
        1440
    } else {
        span
    }
}
fn overlap_error(intervals: &[Interval]) -> Option<usize> {
    let mut earliest: Option<(i64, usize)> = None;
    for (i, a) in intervals.iter().enumerate() {
        for b in intervals.iter().skip(i + 1) {
            if let Some(found) = earliest_pair_hit(a, b) {
                if earliest.map_or(true, |prior| found < prior) {
                    earliest = Some(found);
                }
            }
        }
    }
    earliest.map(|(_, index)| index)
}
fn earliest_pair_hit(a: &Interval, b: &Interval) -> Option<(i64, usize)> {
    [-10080_i64, 0, 10080]
        .into_iter()
        .filter_map(|offset| {
            let start = a.start.max(b.start + offset);
            let end = (a.start + a.duration).min(b.start + offset + b.duration);
            (start < end).then_some((start, b.index))
        })
        .min()
}

impl PayEngine<'_> {
    fn run(mut self) -> Outcome {
        for shift_index in 0..self.request.shifts.len() {
            let row = &self.request.shifts[shift_index];
            let priced = self.price_shift(row);
            self.daily_seen |= priced.daily_overtime;
            self.weekly_seen |= priced.weekly_overtime;
            self.weekly_paid += priced.row.paid_minutes;
            self.rows.push(priced);
        }
        self.apply_bonus();
        let applied = self.applied_rules();
        self.quote(applied)
    }
    fn price_shift(&self, row: &Shift) -> PricedShift {
        let duration = shift_duration(row);
        let unpaid = if duration > 360 { row.break_minutes } else { 0 };
        let paid = duration - unpaid;
        let mut pay = blank_pay_row(row, paid);
        let mut earned = 0;
        for worked in 0..paid {
            let facts = self.minute_facts(row, unpaid, worked);
            earned += self.amount_for(&facts);
            record_minute(&mut pay, &facts);
        }
        PricedShift {
            row: build_pay_row(pay, row, paid, self.base, earned),
            daily_overtime: paid > 480,
            weekly_overtime: self.weekly_paid + paid > 2400,
        }
    }
    fn minute_facts(&self, row: &Shift, unpaid: i64, worked: i64) -> MinuteFacts {
        let minute = row.day * 1440 + row.start + unpaid + worked;
        let clock = minute.rem_euclid(1440);
        MinuteFacts {
            overtime: worked >= 480 || self.weekly_paid + worked >= 2400,
            night: clock >= 1320 || clock < 360,
            weekend: minute.div_euclid(1440).rem_euclid(7) >= 5,
            holiday: row.holiday,
        }
    }
    fn amount_for(&self, facts: &MinuteFacts) -> i128 {
        self.base
            + self.base * i128::from(facts.overtime) / 2
            + self.base * i128::from(facts.night) / 5
            + self.base * i128::from(facts.weekend) / 4
            + self.base * i128::from(facts.holiday)
    }
    fn apply_bonus(&mut self) {
        if !self.request.bonus || self.weekly_paid < 600 {
            return;
        }
        if let Some(last) = self.rows.last_mut() {
            last.row.bonus_cents = 500;
            last.row.cents = ((2 * (i128::from(last.row.cents) * 60 + 30000) + 60) / 120) as i64;
        }
    }
    fn quote(self, applied: Vec<String>) -> Outcome {
        let cents = self.rows.iter().map(|r| r.row.cents).sum();
        Outcome::Quote(Quote {
            shifts: self.rows.into_iter().map(|r| r.row).collect(),
            weekly_paid_minutes: self.weekly_paid,
            weekly_cents: cents,
            applied,
        })
    }
    fn applied_rules(&self) -> Vec<String> {
        RULE_NAMES
            .iter()
            .enumerate()
            .filter_map(|(index, name)| self.rule_used(index).then(|| (*name).to_owned()))
            .collect()
    }
    fn rule_used(&self, index: usize) -> bool {
        match index {
            0 => self.daily_seen,
            1 => self.weekly_seen,
            2 => self.rows.iter().any(|r| r.row.night_minutes > 0),
            3 => self.rows.iter().any(|r| r.row.weekend_minutes > 0),
            4 => self.rows.iter().any(|r| r.row.holiday_minutes > 0),
            5 => self.rows.iter().any(|r| r.row.callout_minutes > 0),
            _ => self.rows.iter().any(|r| r.row.bonus_cents > 0),
        }
    }
}
fn blank_pay_row(row: &Shift, paid: i64) -> PayShift {
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
fn build_pay_row(mut pay: PayShift, row: &Shift, paid: i64, base: i128, earned: i128) -> PayShift {
    pay.callout_minutes = if row.callout { (180 - paid).max(0) } else { 0 };
    pay.cents = ((2 * (earned + base * i128::from(pay.callout_minutes)) + 60) / 120) as i64;
    pay
}
struct MinuteFacts {
    overtime: bool,
    night: bool,
    weekend: bool,
    holiday: bool,
}
fn record_minute(row: &mut PayShift, facts: &MinuteFacts) {
    if facts.overtime {
        row.overtime_minutes += 1;
    } else {
        row.regular_minutes += 1;
    }
    row.night_minutes += i64::from(facts.night);
    row.weekend_minutes += i64::from(facts.weekend);
    row.holiday_minutes += i64::from(facts.holiday);
}
