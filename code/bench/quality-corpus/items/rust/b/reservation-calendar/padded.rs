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
type Key<'a> = (i64, &'a str);
type Seat<'a> = (Key<'a>, usize);
type Calendar<'a> = (&'a [Slot], &'a [Interval]);

///
/// # Errors
///
/// Returns `Err(CalendarError::InvalidInterval)` when an interval leaves the
/// day or does not advance.
/// Return the identifiers of available appointment slots after applying reservation overlap rules.
pub fn solution(calendar: Calendar<'_>) -> Outcome<'_> {
    let valid = validated_calendar(calendar)?;
    Ok(identifiers(keys_of(unblocked(valid))))
}

fn validated_calendar(calendar: Calendar<'_>) -> Result<Calendar<'_>, CalendarError> {
    let valid = calendar_ok(calendar);
    if valid {
        return Ok(calendar);
    }
    Err(CalendarError::InvalidInterval)
}

fn calendar_ok(calendar: Calendar<'_>) -> bool {
    let appointments_ok = appointments_valid(calendar);
    let bookings_ok = bookings_valid(calendar);
    appointments_ok && bookings_ok
}

fn appointments_valid(calendar: Calendar<'_>) -> bool {
    let invalid_appointment = calendar.0.iter().find(|slot| !appointment_valid(slot));
    invalid_appointment.is_none()
}

fn appointment_valid(slot: &Slot) -> bool {
    let lower_bound_ok = slot.start >= 0;
    let upper_bound_ok = slot.end <= 1440;
    let interval_ok = slot.start < slot.end;
    lower_bound_ok && upper_bound_ok && interval_ok
}

fn bookings_valid(calendar: Calendar<'_>) -> bool {
    let invalid_booking = calendar.1.iter().find(|span| !booking_valid(span));
    invalid_booking.is_none()
}

fn booking_valid(span: &Interval) -> bool {
    let lower_bound_ok = span.start >= 0;
    let upper_bound_ok = span.end <= 1440;
    let interval_ok = span.start < span.end;
    lower_bound_ok && upper_bound_ok && interval_ok
}

fn unblocked(calendar: Calendar<'_>) -> Vec<&Slot> {
    let mut result = Vec::new();
    for slot in calendar.0 {
        if clear(slot, calendar.1) {
            result.push(slot);
        }
    }
    result
}

fn clear(slot: &Slot, spans: &[Interval]) -> bool {
    let collision = spans.iter().find(|span| crosses(slot, span));
    collision.is_none()
}

fn crosses(slot: &Slot, span: &Interval) -> bool {
    let starts_early = slot.start < span.end;
    let finishes_late = span.start < slot.end;
    starts_early && finishes_late
}

fn keys_of(slots: Vec<&Slot>) -> Vec<Seat<'_>> {
    let mut result = Vec::new();
    for (at, slot) in slots.into_iter().enumerate() {
        let seat = seat_for(slot, at);
        result.push(seat);
    }
    result.sort_unstable();
    result
}

fn seat_for(slot: &Slot, at: usize) -> Seat<'_> {
    let key = key_for(slot);
    (key, at)
}

fn key_for(slot: &Slot) -> Key<'_> {
    let beginning = slot.start;
    let identifier = slot.id.as_str();
    (beginning, identifier)
}

fn identifiers(seats: Vec<Seat<'_>>) -> Vec<&str> {
    let mut result = Vec::with_capacity(seats.len());
    for (key, _) in seats {
        result.push(key.1);
    }
    result
}
