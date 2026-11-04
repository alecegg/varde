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
type Key<'a> = (i64, &'a str);
type Seat<'a> = (Key<'a>, usize);
type Calendar<'a> = (&'a [Slot], &'a [Interval]);
type Checked<'a> = Result<Calendar<'a>, CalendarError>;
type SlotList<'a> = Vec<&'a Slot>;
type KeySet<'a> = BTreeSet<Seat<'a>>;
const BAD: CalendarError = CalendarError::InvalidInterval;

///
/// # Errors
///
/// Returns `Err(CalendarError::InvalidInterval)` when an interval leaves the
/// day or does not advance.
/// Return the identifiers of available appointment slots after applying reservation overlap rules.
pub fn solution(calendar: Calendar<'_>) -> Outcome<'_> {
    Ok(slot_ids(sorted_keys(free_slots(valid_calendar(calendar)?))))
}

fn valid_calendar(calendar: Calendar<'_>) -> Checked<'_> {
    calendar_valid(calendar).then_some(calendar).ok_or(BAD)
}

fn calendar_valid(calendar: Calendar<'_>) -> bool {
    slots_valid(calendar) && reservations_valid(calendar)
}

fn slots_valid(calendar: Calendar<'_>) -> bool {
    calendar.0.iter().all(slot_valid)
}

fn slot_valid(slot: &Slot) -> bool {
    slot.start >= 0 && slot.end <= 1440 && slot.start < slot.end
}

fn reservations_valid(calendar: Calendar<'_>) -> bool {
    calendar.1.iter().all(reservation_valid)
}

fn reservation_valid(span: &Interval) -> bool {
    span.start >= 0 && span.end <= 1440 && span.start < span.end
}

fn free_slots((slots, spans): Calendar) -> SlotList {
    slots.iter().filter(|s| unreserved(s, spans)).collect()
}

fn unreserved(slot: &Slot, spans: &[Interval]) -> bool {
    spans.iter().all(|span| !conflicts_with(slot, span))
}

fn conflicts_with(slot: &Slot, span: &Interval) -> bool {
    slot.start < span.end && span.start < slot.end
}

fn sorted_keys(slots: SlotList<'_>) -> KeySet<'_> {
    slots.into_iter().enumerate().map(seated_slot).collect()
}

fn seated_slot((at, slot): (usize, &Slot)) -> Seat<'_> {
    (slot_key(slot), at)
}

fn slot_key(slot: &Slot) -> Key<'_> {
    (slot.start, slot.id.as_str())
}

fn slot_ids(keys: KeySet<'_>) -> Vec<&str> {
    keys.into_iter().map(|(key, _)| key.1).collect()
}
