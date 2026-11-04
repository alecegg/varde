use corpus::{solution, CalendarError, Interval, Slot};

fn slot(id: &str, start: i64, end: i64) -> Slot {
    Slot {
        id: id.to_string(),
        start,
        end,
    }
}

fn span(start: i64, end: i64) -> Interval {
    Interval { start, end }
}

/// The stated rules: every start must precede its end, and half-open spans overlap strictly.
fn reference<'a>(slots: &'a [Slot], reserved: &[Interval]) -> Option<Vec<&'a str>> {
    if slots
        .iter()
        .any(|s| s.start < 0 || s.end > 1440 || s.start >= s.end)
        || reserved
            .iter()
            .any(|r| r.start < 0 || r.end > 1440 || r.start >= r.end)
    {
        return None;
    }
    let mut free: Vec<(i64, &'a str)> = slots
        .iter()
        .filter(|s| {
            reserved
                .iter()
                .all(|r| s.end <= r.start || r.end <= s.start)
        })
        .map(|s| (s.start, s.id.as_str()))
        .collect();
    free.sort_unstable();
    Some(free.into_iter().map(|(_, id)| id).collect())
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }
}

fn ids(slots: &[Slot]) -> Vec<&str> {
    slots.iter().map(|s| s.id.as_str()).collect()
}

#[test]
fn matches_the_stated_cases() {
    let cases: Vec<(Vec<Slot>, Vec<Interval>, Vec<&str>)> = vec![
        (vec![], vec![], vec![]),
        (vec![slot("A", 540, 600)], vec![], vec!["A"]),
        (vec![slot("A", 540, 600)], vec![span(540, 600)], vec![]),
        (
            vec![slot("A", 480, 540), slot("B", 540, 600)],
            vec![span(540, 570)],
            vec!["A"],
        ),
        (vec![slot("A", 540, 600)], vec![span(570, 630)], vec![]),
        (
            vec![slot("B", 600, 660), slot("A", 540, 600)],
            vec![span(700, 720)],
            vec!["A", "B"],
        ),
        (
            vec![slot("B", 540, 600), slot("A", 540, 600)],
            vec![],
            vec!["A", "B"],
        ),
        (
            vec![slot("A", 0, 30), slot("B", 1410, 1440)],
            vec![span(30, 60)],
            vec!["A", "B"],
        ),
    ];
    for (slots, reserved, expected) in cases {
        assert_eq!(solution((&slots, &reserved)), Ok(expected), "{slots:?}");
    }
}

#[test]
fn rejects_intervals_that_do_not_advance() {
    let rejected: Vec<(Vec<Slot>, Vec<Interval>)> = vec![
        (vec![slot("A", 600, 600)], vec![]),
        (vec![slot("A", 700, 600)], vec![]),
        (vec![slot("A", 540, 600)], vec![span(800, 800)]),
        (vec![slot("A", 540, 600)], vec![span(900, 800)]),
        (
            vec![slot("A", 100, 500)],
            vec![span(200, 300), span(400, 400)],
        ),
    ];
    for (slots, reserved) in rejected {
        assert_eq!(
            solution((&slots, &reserved)),
            Err(CalendarError::InvalidInterval),
            "{slots:?}"
        );
    }
}

#[test]
fn touching_endpoints_do_not_overlap() {
    let slots = vec![slot("A", 480, 540), slot("B", 540, 600)];
    let reserved = vec![span(420, 480), span(600, 660), span(540, 541)];
    assert_eq!(solution((&slots, &reserved)), Ok(vec!["A"]));
    let before = vec![span(0, 480)];
    assert_eq!(solution((&slots, &before)), Ok(vec!["A", "B"]));
}

#[test]
fn matches_the_reference_on_random_calendars() {
    let mut rng = Rng(20_261_017);
    for round in 0..3_000 {
        let count = (rng.next() % 6) as usize;
        let mut slots = Vec::new();
        for index in 0..count {
            let length = (rng.next() % 60) as i64 + 1;
            let start = (rng.next() % (1_441 - length as u64)) as i64;
            slots.push(slot(&format!("S{round}-{index}"), start, start + length));
        }
        let reserved_count = (rng.next() % 4) as usize;
        let mut reserved = Vec::new();
        for _ in 0..reserved_count {
            let length = (rng.next() % 90) as i64 + 1;
            let start = (rng.next() % (1_441 - length as u64)) as i64;
            reserved.push(span(start, start + length));
        }
        assert_eq!(
            solution((&slots, &reserved)),
            Ok(reference(&slots, &reserved).unwrap()),
            "{slots:?} {reserved:?}"
        );
    }
}

#[test]
fn matches_the_reference_on_a_large_calendar() {
    let mut slots = Vec::with_capacity(1_000);
    for index in 0..1_000i64 {
        let start = (index * 977) % 1_380;
        slots.push(slot(&format!("Z{}", 1_000 - index), start, start + 45));
    }
    let reserved = vec![span(0, 100), span(500, 620), span(1_000, 1_100)];
    assert_eq!(
        solution((&slots, &reserved)),
        Ok(reference(&slots, &reserved).unwrap())
    );
    let sorted = solution((&slots, &reserved)).unwrap();
    assert!(sorted.len() < ids(&slots).len());
    let mut ordered = sorted.clone();
    ordered.sort_by_key(|id| {
        let slot = slots.iter().find(|s| s.id == *id).unwrap();
        (slot.start, slot.id.as_str())
    });
    assert_eq!(sorted, ordered);
}

#[test]
fn rejects_out_of_day_boundaries() {
    for (slots, reserved) in [
        (vec![slot("A", -1, 20)], vec![]),
        (vec![slot("A", 1400, 1441)], vec![]),
        (vec![slot("A", 10, 20)], vec![span(-1, 1)]),
        (vec![slot("A", 10, 20)], vec![span(1439, 1441)]),
    ] {
        assert_eq!(
            solution((&slots, &reserved)),
            Err(CalendarError::InvalidInterval)
        );
    }
}
