#[derive(Debug)]
pub struct Slot {
    pub id: String,
    pub start: i64,
    pub end: i64,
}

#[derive(Debug)]
pub struct Interval {
    pub start: i64,
    pub end: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub enum CalendarError {
    InvalidInterval,
}

type Outcome<'a> = Result<Vec<&'a str>, CalendarError>;
type Calendar<'a> = (&'a [Slot], &'a [Interval]);
const DAY_START: i64 = 0;
const DAY_END: i64 = 1440;

///
/// # Errors
///
/// Returns `Err(CalendarError::InvalidInterval)` when an interval leaves the
/// day or does not advance.
/// Return the identifiers of available appointment slots after applying reservation overlap rules.
pub fn solution(calendar: Calendar<'_>) -> Outcome<'_> {
    let mut valid = true;
    for slot in calendar.0 {
        let start_is_inside_day = slot.start >= DAY_START;
        let end_is_inside_day = slot.end <= DAY_END;
        let interval_has_length = slot.start < slot.end;
        let slot_is_valid = start_is_inside_day && end_is_inside_day && interval_has_length;
        valid = valid && slot_is_valid;
    }
    for span in calendar.1 {
        let start_is_inside_day = span.start >= DAY_START;
        let end_is_inside_day = span.end <= DAY_END;
        let interval_has_length = span.start < span.end;
        let span_is_valid = start_is_inside_day && end_is_inside_day && interval_has_length;
        valid = valid && span_is_valid;
    }
    if !valid {
        return Err(CalendarError::InvalidInterval);
    }
    let capacity = calendar.0.len();
    let mut available: Vec<(i64, &str)> = Vec::with_capacity(capacity);
    for slot in calendar.0 {
        let free_of_reservations = calendar.1.iter().all(|span| {
            let starts_before_span_ends = slot.start < span.end;
            let ends_after_span_starts = span.start < slot.end;
            let overlaps = starts_before_span_ends && ends_after_span_starts;
            !overlaps
        });
        if free_of_reservations {
            let sort_minute = slot.start;
            let sort_identifier = slot.id.as_str();
            available.push((sort_minute, sort_identifier));
        }
    }
    available.sort_unstable();
    let identifiers: Vec<&str> = available.into_iter().map(|(_, id)| id).collect();
    Ok(identifiers)
}
