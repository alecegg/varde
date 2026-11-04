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
    let slots = calendar.0;
    let reservations = calendar.1;
    let slot_count = slots.len();
    let reservation_count = reservations.len();
    let mut valid = true;
    let mut slot_index = 0;
    while slot_index < slot_count {
        let slot = &slots[slot_index];
        let start_is_inside_day = slot.start >= DAY_START;
        let end_is_inside_day = slot.end <= DAY_END;
        let interval_has_length = slot.start < slot.end;
        let slot_is_valid = start_is_inside_day && end_is_inside_day && interval_has_length;
        if !slot_is_valid {
            valid = false;
        }
        slot_index += 1;
    }
    let mut reservation_index = 0;
    while reservation_index < reservation_count {
        let span = &reservations[reservation_index];
        let start_is_inside_day = span.start >= DAY_START;
        let end_is_inside_day = span.end <= DAY_END;
        let interval_has_length = span.start < span.end;
        let span_is_valid = start_is_inside_day && end_is_inside_day && interval_has_length;
        if !span_is_valid {
            valid = false;
        }
        reservation_index += 1;
    }
    if !valid {
        return Err(CalendarError::InvalidInterval);
    }
    let mut available: Vec<(i64, &str)> = Vec::new();
    let mut slot_index = 0;
    while slot_index < slot_count {
        let slot = &slots[slot_index];
        let overlaps_any_reservation = reservations.iter().any(|span| {
            let starts_before_span_ends = slot.start < span.end;
            let ends_after_span_starts = span.start < slot.end;
            starts_before_span_ends && ends_after_span_starts
        });
        let free_of_reservations = !overlaps_any_reservation;
        if free_of_reservations {
            let sort_minute = slot.start;
            let sort_identifier = slot.id.as_str();
            available.push((sort_minute, sort_identifier));
        }
        slot_index += 1;
    }
    let mut outer = 1;
    while outer < available.len() {
        let mut inner = outer;
        while inner > 0 {
            let previous = &available[inner - 1];
            let current = &available[inner];
            let current_comes_first = (current.0, current.1) < (previous.0, previous.1);
            if !current_comes_first {
                break;
            }
            available.swap(inner - 1, inner);
            inner -= 1;
        }
        outer += 1;
    }
    let mut identifiers: Vec<&str> = Vec::with_capacity(available.len());
    for (_, identifier) in available {
        identifiers.push(identifier);
    }
    Ok(identifiers)
}
