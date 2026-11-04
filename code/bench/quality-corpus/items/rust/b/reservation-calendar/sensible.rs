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
type Unreserved<'a> = Vec<(i64, &'a str)>;

///
/// # Errors
///
/// Returns `Err(CalendarError::InvalidInterval)` when an interval leaves the
/// day or does not advance.
/// Return the identifiers of available appointment slots after applying reservation overlap rules.
pub fn solution(calendar: Calendar<'_>) -> Outcome<'_> {
    if !slots_valid(calendar.0) || !reservations_valid(calendar.1) {
        return Err(CalendarError::InvalidInterval);
    }
    Ok(ordered_ids(unreserved_slots(calendar.0, calendar.1)))
}

fn slots_valid(slots: &[Slot]) -> bool {
    slots
        .iter()
        .all(|slot| slot.start >= 0 && slot.end <= 1440 && slot.start < slot.end)
}

fn reservations_valid(reserved: &[Interval]) -> bool {
    reserved
        .iter()
        .all(|span| span.start >= 0 && span.end <= 1440 && span.start < span.end)
}

fn unreserved_slots<'a>(slots: &'a [Slot], reserved: &[Interval]) -> Unreserved<'a> {
    slots
        .iter()
        .filter(|slot| {
            reserved
                .iter()
                .all(|span| slot.end <= span.start || span.end <= slot.start)
        })
        .map(|slot| (slot.start, slot.id.as_str()))
        .collect()
}

fn ordered_ids(mut pairs: Vec<(i64, &str)>) -> Vec<&str> {
    pairs.sort_unstable();
    pairs.into_iter().map(|(_, id)| id).collect()
}
