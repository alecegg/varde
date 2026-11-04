use std::collections::BTreeSet;

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

const BAD: CalendarError = CalendarError::InvalidInterval;

type Key<'a> = (i64, &'a str);
type Seat<'a> = (Key<'a>, usize);
type Seats<'a> = BTreeSet<Seat<'a>>;
type Calendar<'a> = (&'a [Slot], &'a [Interval]);
type SlotRefs<'a> = Vec<&'a Slot>;

///
/// # Errors
///
/// Returns `Err(CalendarError::InvalidInterval)` when an interval leaves the
/// day or does not advance.
/// Return the identifiers of available appointment slots after applying reservation overlap rules.
pub fn solution(calendar: Calendar<'_>) -> Outcome<'_> {
    Ok(ids(rank(free(checked(calendar)?))))
}

fn checked(calendar: Calendar<'_>) -> Result<Calendar<'_>, CalendarError> {
    spans_ok(calendar).then_some(calendar).ok_or(BAD)
}

fn spans_ok(calendar: Calendar<'_>) -> bool {
    slots_ok(calendar) && ranges_ok(calendar)
}

fn slots_ok(calendar: Calendar<'_>) -> bool {
    calendar.0.iter().all(slot_ok)
}

fn slot_ok(slot: &Slot) -> bool {
    slot.start >= 0 && slot.end <= 1440 && slot.start < slot.end
}

fn ranges_ok(calendar: Calendar<'_>) -> bool {
    calendar.1.iter().all(span_ok)
}

fn span_ok(span: &Interval) -> bool {
    span.start >= 0 && span.end <= 1440 && span.start < span.end
}

fn free((slots, spans): Calendar) -> SlotRefs {
    slots.iter().filter(|s| is_free(s, spans)).collect()
}

fn is_free(slot: &Slot, reserved: &[Interval]) -> bool {
    !reserved.iter().any(|span| overlaps(slot, span))
}

fn overlaps(slot: &Slot, span: &Interval) -> bool {
    slot.start < span.end && span.start < slot.end
}

fn rank(slots: Vec<&Slot>) -> Seats<'_> {
    slots.into_iter().enumerate().map(seated).collect()
}

fn seated((at, slot): (usize, &Slot)) -> Seat<'_> {
    (key_of(slot), at)
}

fn key_of(slot: &Slot) -> Key<'_> {
    (slot.start, slot.id.as_str())
}

fn ids(keys: Seats<'_>) -> Vec<&str> {
    keys.into_iter().map(|(key, _)| key.1).collect()
}
