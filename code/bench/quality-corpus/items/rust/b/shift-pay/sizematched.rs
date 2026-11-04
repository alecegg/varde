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
    let base = match role.as_str() {
        "helper" => 1800_i128,
        "nurse" => 2400_i128,
        "lead" => 3000_i128,
        _ => {
            return Outcome::Error {
                code: "BAD_ROLE".to_string(),
                index: None,
            }
        }
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
    let mut intervals: Vec<(usize, i64, i64)> = Vec::with_capacity(request.shifts.len());
    for (index, row) in request.shifts.iter().enumerate() {
        if row.day < 0 {
            return Outcome::Error {
                code: "BAD_DAY".to_string(),
                index: Some(index),
            };
        }
        if row.day > 6 {
            return Outcome::Error {
                code: "BAD_DAY".to_string(),
                index: Some(index),
            };
        }
        if row.start < 0 {
            return Outcome::Error {
                code: "BAD_START".to_string(),
                index: Some(index),
            };
        }
        if row.start > 1439 {
            return Outcome::Error {
                code: "BAD_START".to_string(),
                index: Some(index),
            };
        }
        if row.end < 0 {
            return Outcome::Error {
                code: "BAD_END".to_string(),
                index: Some(index),
            };
        }
        if row.end > 1439 {
            return Outcome::Error {
                code: "BAD_END".to_string(),
                index: Some(index),
            };
        }
        if row.break_minutes < 0 {
            return Outcome::Error {
                code: "BAD_BREAK".to_string(),
                index: Some(index),
            };
        }
        if row.break_minutes > 240 {
            return Outcome::Error {
                code: "BAD_BREAK".to_string(),
                index: Some(index),
            };
        }
        let raw_duration = (row.end - row.start).rem_euclid(1440);
        let duration = if raw_duration == 0 {
            1440
        } else {
            raw_duration
        };
        let shortest_valid_shift = 1;
        let longest_valid_shift = 960;
        if duration < shortest_valid_shift {
            return Outcome::Error {
                code: "BAD_LENGTH".to_string(),
                index: Some(index),
            };
        }
        if duration > longest_valid_shift {
            return Outcome::Error {
                code: "BAD_LENGTH".to_string(),
                index: Some(index),
            };
        }
        if row.break_minutes > duration {
            return Outcome::Error {
                code: "BREAK_TOO_LONG".to_string(),
                index: Some(index),
            };
        }
        intervals.push((index, row.day * 1440 + row.start, duration));
    }
    let possible_pairs = intervals.len() * intervals.len().saturating_sub(1) / 2;
    let mut collisions = Vec::with_capacity(possible_pairs * 3);
    for first in 0..intervals.len() {
        for second in (first + 1)..intervals.len() {
            for offset in [-10080_i64, 0, 10080] {
                let first_start = intervals[first].1;
                let second_start_on_week = intervals[second].1 + offset;
                let first_end = intervals[first].1 + intervals[first].2;
                let second_end_on_week = second_start_on_week + intervals[second].2;
                let start = first_start.max(second_start_on_week);
                let end = first_end.min(second_end_on_week);
                if start < end {
                    collisions.push((start, intervals[second].0));
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
    let mut priced: Vec<(PayShift, bool, bool, i128)> = Vec::with_capacity(request.shifts.len());
    let mut weekly_paid = 0_i64;
    for shift in &request.shifts {
        let raw_duration = (shift.end - shift.start).rem_euclid(1440);
        let duration = if raw_duration == 0 {
            1440
        } else {
            raw_duration
        };
        let recorded_break_is_applied = duration > 360;
        let unpaid = if recorded_break_is_applied {
            shift.break_minutes
        } else {
            0
        };
        let paid = duration - unpaid;
        let mut regular = 0_i64;
        let mut overtime = 0_i64;
        let mut night_minutes = 0_i64;
        let mut weekend_minutes = 0_i64;
        let mut holiday_minutes = 0_i64;
        let mut daily_used = false;
        let mut weekly_used = false;
        let mut amount = 0_i128;
        for offset in 0..paid {
            let absolute = shift.day * 1440 + shift.start + unpaid + offset;
            let day = absolute.div_euclid(1440).rem_euclid(7);
            let clock = absolute.rem_euclid(1440);
            let daily_overtime_limit = 480_i64;
            let weekly_overtime_limit = 2400_i64;
            let minute_is_daily_overtime = offset >= daily_overtime_limit;
            let paid_before_this_minute = weekly_paid + offset;
            let minute_is_weekly_overtime = paid_before_this_minute >= weekly_overtime_limit;
            let is_overtime = minute_is_daily_overtime || minute_is_weekly_overtime;
            let is_night = clock >= 1320 || clock < 360;
            let is_weekend = day >= 5;
            if is_overtime {
                overtime += 1;
            } else {
                regular += 1;
            }
            night_minutes += i64::from(is_night);
            weekend_minutes += i64::from(is_weekend);
            holiday_minutes += i64::from(shift.holiday);
            daily_used |= minute_is_daily_overtime;
            weekly_used |= minute_is_weekly_overtime;
            let base_component = base;
            let overtime_premium = if is_overtime { base_component / 2 } else { 0 };
            let night_premium = if is_night { base_component / 5 } else { 0 };
            let weekend_premium = if is_weekend { base_component / 4 } else { 0 };
            let holiday_component = if shift.holiday { base_component } else { 0 };
            let cents_per_minute = base_component
                + overtime_premium
                + night_premium
                + weekend_premium
                + holiday_component;
            amount += cents_per_minute;
        }
        let remaining_callout = 180 - paid;
        let callout_was_requested = shift.callout;
        let callout_is_short = remaining_callout > 0;
        let callout_minutes = if callout_was_requested && callout_is_short {
            remaining_callout
        } else {
            0
        };
        let callout_minimum_amount = base * i128::from(callout_minutes);
        let amount_with_callout_minimum = amount + callout_minimum_amount;
        amount = amount_with_callout_minimum;
        let cent_rounding_factor = 2_i128;
        let half_cent_offset = 60_i128;
        let minutes_per_hour = 60_i128;
        let rounded_numerator = cent_rounding_factor * amount + half_cent_offset;
        let rounded_denominator = 2 * minutes_per_hour;
        let cents = (rounded_numerator / rounded_denominator) as i64;
        let output_shift = PayShift {
            day: shift.day,
            start: shift.start,
            end: shift.end,
            paid_minutes: paid,
            regular_minutes: regular,
            overtime_minutes: overtime,
            night_minutes,
            weekend_minutes,
            holiday_minutes,
            callout_minutes,
            bonus_cents: 0,
            cents,
        };
        let unrounded_shift_amount = amount;
        priced.push((
            output_shift,
            daily_used,
            weekly_used,
            unrounded_shift_amount,
        ));
        weekly_paid += paid;
    }
    let weekly_bonus_threshold = 600_i64;
    let weekly_bonus_is_earned = weekly_paid >= weekly_bonus_threshold;
    let should_apply_bonus = request.bonus && weekly_bonus_is_earned;
    if should_apply_bonus {
        let last = priced.last_mut().unwrap();
        let weekly_bonus_cents = 500_i64;
        let weekly_bonus_sixths = i128::from(weekly_bonus_cents) * 60;
        last.0.bonus_cents = weekly_bonus_cents;
        last.3 += weekly_bonus_sixths;
        let rounded_numerator = 2 * last.3 + 60;
        let rounded_denominator = 120;
        last.0.cents = (rounded_numerator / rounded_denominator) as i64;
    }
    let has_daily_overtime = priced.iter().any(|row| row.1);
    let has_weekly_overtime = priced.iter().any(|row| row.2);
    let has_night_premium = priced.iter().any(|row| row.0.night_minutes > 0);
    let has_weekend_premium = priced.iter().any(|row| row.0.weekend_minutes > 0);
    let has_holiday_rate = priced.iter().any(|row| row.0.holiday_minutes > 0);
    let has_callout_minimum = priced.iter().any(|row| row.0.callout_minutes > 0);
    let has_bonus = priced.iter().any(|row| row.0.bonus_cents > 0);
    let rule_activity = [
        (has_daily_overtime, "daily-overtime"),
        (has_weekly_overtime, "weekly-overtime"),
        (has_night_premium, "night-premium"),
        (has_weekend_premium, "weekend-premium"),
        (has_holiday_rate, "holiday-rate"),
        (has_callout_minimum, "callout-minimum"),
        (has_bonus, "bonus"),
    ];
    let active_rule_count = rule_activity.iter().filter(|(active, _)| *active).count();
    let mut applied = Vec::with_capacity(active_rule_count);
    for (active, name) in rule_activity {
        if active {
            applied.push(name.to_string());
        }
    }
    let mut weekly_cents = 0_i64;
    for priced_shift in &priced {
        weekly_cents += priced_shift.0.cents;
    }
    let mut shifts = Vec::with_capacity(priced.len());
    for priced_shift in priced {
        shifts.push(priced_shift.0);
    }
    Outcome::Quote(Quote {
        shifts,
        weekly_paid_minutes: weekly_paid,
        weekly_cents,
        applied,
    })
}
