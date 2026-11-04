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

/// Return ordered shift pay rows or the first contract validation error.
pub fn solution(request: &Request) -> Outcome {
    let role = request.role.trim().to_ascii_lowercase();
    let base = if role == "helper" {
        1800_i128
    } else if role == "nurse" {
        2400_i128
    } else if role == "lead" {
        3000_i128
    } else {
        return Outcome::Error {
            code: "BAD_ROLE".to_string(),
            index: None,
        };
    };
    if request.shifts.is_empty() {
        return Outcome::Error {
            code: "EMPTY_WEEK".to_string(),
            index: None,
        };
    }
    if request.shifts.len() > 14 {
        return Outcome::Error {
            code: "TOO_MANY_SHIFTS".to_string(),
            index: None,
        };
    }
    let mut intervals = Vec::new();
    for (index, shift) in request.shifts.iter().enumerate() {
        if shift.day < 0 {
            return Outcome::Error {
                code: "BAD_DAY".to_string(),
                index: Some(index),
            };
        }
        if shift.day > 6 {
            return Outcome::Error {
                code: "BAD_DAY".to_string(),
                index: Some(index),
            };
        }
        if shift.start < 0 {
            return Outcome::Error {
                code: "BAD_START".to_string(),
                index: Some(index),
            };
        }
        if shift.start > 1439 {
            return Outcome::Error {
                code: "BAD_START".to_string(),
                index: Some(index),
            };
        }
        if shift.end < 0 {
            return Outcome::Error {
                code: "BAD_END".to_string(),
                index: Some(index),
            };
        }
        if shift.end > 1439 {
            return Outcome::Error {
                code: "BAD_END".to_string(),
                index: Some(index),
            };
        }
        if shift.break_minutes < 0 {
            return Outcome::Error {
                code: "BAD_BREAK".to_string(),
                index: Some(index),
            };
        }
        if shift.break_minutes > 240 {
            return Outcome::Error {
                code: "BAD_BREAK".to_string(),
                index: Some(index),
            };
        }
        let raw_length = (shift.end - shift.start).rem_euclid(1440);
        let length = if raw_length == 0 { 1440 } else { raw_length };
        if length < 1 {
            return Outcome::Error {
                code: "BAD_LENGTH".to_string(),
                index: Some(index),
            };
        }
        if length > 960 {
            return Outcome::Error {
                code: "BAD_LENGTH".to_string(),
                index: Some(index),
            };
        }
        if shift.break_minutes > length {
            return Outcome::Error {
                code: "BREAK_TOO_LONG".to_string(),
                index: Some(index),
            };
        }
        intervals.push((index, shift.day * 1440 + shift.start, length));
    }
    let mut collisions = Vec::new();
    for first_position in 0..intervals.len() {
        for second_position in (first_position + 1)..intervals.len() {
            let first = &intervals[first_position];
            let second = &intervals[second_position];
            for week_offset in [-10080_i64, 0, 10080] {
                let second_start = second.1 + week_offset;
                let common_start = first.1.max(second_start);
                let common_end = (first.1 + first.2).min(second_start + second.2);
                if common_start < common_end {
                    collisions.push((common_start, second.0));
                }
            }
        }
    }
    if let Some((_, index)) = collisions.into_iter().min() {
        return Outcome::Error {
            code: "OVERLAP".to_string(),
            index: Some(index),
        };
    }
    let mut rows = Vec::new();
    let mut weekly_paid_minutes = 0_i64;
    for shift in &request.shifts {
        let raw_length = (shift.end - shift.start).rem_euclid(1440);
        let duration = if raw_length == 0 { 1440 } else { raw_length };
        let unpaid = if duration > 360 {
            shift.break_minutes
        } else {
            0
        };
        let paid = duration - unpaid;
        let mut regular_minutes = 0_i64;
        let mut overtime_minutes = 0_i64;
        let mut night_minutes = 0_i64;
        let mut weekend_minutes = 0_i64;
        let mut holiday_minutes = 0_i64;
        let mut daily_used = false;
        let mut weekly_used = false;
        let mut exact_amount = 0_i128;
        for elapsed in 0..paid {
            let absolute_minute = shift.day * 1440 + shift.start + unpaid + elapsed;
            let calendar_day = absolute_minute.div_euclid(1440).rem_euclid(7);
            let local_minute = absolute_minute.rem_euclid(1440);
            let daily_overtime_start = 480_i64;
            let weekly_overtime_start = 2400_i64;
            let daily_overtime = elapsed >= daily_overtime_start;
            let paid_before_this_minute = weekly_paid_minutes + elapsed;
            let weekly_overtime = paid_before_this_minute >= weekly_overtime_start;
            let overtime = daily_overtime || weekly_overtime;
            let night = local_minute >= 1320 || local_minute < 360;
            let weekend = calendar_day >= 5;
            if overtime {
                overtime_minutes += 1;
            } else {
                regular_minutes += 1;
            }
            if night {
                night_minutes += 1;
            }
            if weekend {
                weekend_minutes += 1;
            }
            if shift.holiday {
                holiday_minutes += 1;
            }
            daily_used |= daily_overtime;
            weekly_used |= weekly_overtime;
            let base_rate_for_minute = base;
            let mut minute_rate = base_rate_for_minute;
            if overtime {
                minute_rate += base / 2;
            }
            if night {
                minute_rate += base / 5;
            }
            if weekend {
                minute_rate += base / 4;
            }
            if shift.holiday {
                minute_rate += base;
            }
            let paid_minute_amount = minute_rate;
            exact_amount += paid_minute_amount;
        }
        let missing_callout = 180 - paid;
        let callout_minutes = if shift.callout && missing_callout > 0 {
            missing_callout
        } else {
            0
        };
        exact_amount += base * i128::from(callout_minutes);
        let rounded_cents = ((2 * exact_amount + 60) / 120) as i64;
        rows.push((
            PayShift {
                day: shift.day,
                start: shift.start,
                end: shift.end,
                paid_minutes: paid,
                regular_minutes,
                overtime_minutes,
                night_minutes,
                weekend_minutes,
                holiday_minutes,
                callout_minutes,
                bonus_cents: 0,
                cents: rounded_cents,
            },
            daily_used,
            weekly_used,
            exact_amount,
        ));
        weekly_paid_minutes += paid;
    }
    if request.bonus && weekly_paid_minutes >= 600 {
        let last = rows.last_mut().unwrap();
        last.0.bonus_cents = 500;
        last.3 += 500 * 60;
        last.0.cents = ((2 * last.3 + 60) / 120) as i64;
    }
    let mut applied = Vec::new();
    if rows.iter().any(|row| row.1) {
        applied.push("daily-overtime".to_string());
    }
    if rows.iter().any(|row| row.2) {
        applied.push("weekly-overtime".to_string());
    }
    if rows.iter().any(|row| row.0.night_minutes > 0) {
        applied.push("night-premium".to_string());
    }
    if rows.iter().any(|row| row.0.weekend_minutes > 0) {
        applied.push("weekend-premium".to_string());
    }
    if rows.iter().any(|row| row.0.holiday_minutes > 0) {
        applied.push("holiday-rate".to_string());
    }
    if rows.iter().any(|row| row.0.callout_minutes > 0) {
        applied.push("callout-minimum".to_string());
    }
    if rows.iter().any(|row| row.0.bonus_cents > 0) {
        applied.push("bonus".to_string());
    }
    let weekly_cents = rows.iter().map(|row| row.0.cents).sum();
    let shifts = rows.into_iter().map(|row| row.0).collect();
    Outcome::Quote(Quote {
        shifts,
        weekly_paid_minutes,
        weekly_cents,
        applied,
    })
}
