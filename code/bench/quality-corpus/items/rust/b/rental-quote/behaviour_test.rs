use corpus::{solution, Booking, NightLine, Outcome, Quote, Request};
fn req() -> Request {
    Request {
        property_id: "CEDAR".into(),
        arrival: 10,
        departure: 11,
        adults: 2,
        children: 0,
        extras: vec![],
        bookings: vec![],
        promo_code: "".into(),
    }
}
fn booking(property: &str, start: i64, end: i64) -> Booking {
    Booking {
        property_id: property.into(),
        arrival: start,
        departure: end,
    }
}
fn fail(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}
fn rhu(n: i128, d: i128) -> i64 {
    ((2 * n + d) / (2 * d)) as i64
}

// Independent oracle: validation and pricing use direct day lookups and no implementation helpers.
fn oracle(r: &Request) -> Outcome {
    let prop = r.property_id.trim_matches(' ').to_ascii_uppercase();
    let extras: Vec<String> = r
        .extras
        .iter()
        .map(|x| x.trim_matches(' ').to_ascii_uppercase())
        .collect();
    let promo = r.promo_code.trim_matches(' ').to_ascii_uppercase();
    if prop != "CEDAR" && prop != "LAKE" {
        return fail("BAD_PROPERTY", None);
    }
    if !(1..=8).contains(&r.adults) {
        return fail("BAD_ADULTS", None);
    }
    if !(0..=8).contains(&r.children) {
        return fail("BAD_CHILDREN", None);
    }
    if !(0..=1_000_000).contains(&r.arrival)
        || !(0..=1_000_000).contains(&r.departure)
        || r.departure <= r.arrival
    {
        return fail("BAD_DAYS", None);
    }
    if extras.len() > 4 {
        return fail("BAD_EXTRA", None);
    }
    for i in 0..extras.len() {
        if (extras[i] != "PARKING" && extras[i] != "PET") || extras[..i].contains(&extras[i]) {
            return fail("BAD_EXTRA", Some(i));
        }
    }
    if r.bookings.len() > 100 {
        return fail("BAD_BOOKING", None);
    }
    let mut bs = Vec::new();
    for (i, b) in r.bookings.iter().enumerate() {
        let p = b.property_id.trim_matches(' ').to_ascii_uppercase();
        if (p != "CEDAR" && p != "LAKE")
            || !(0..=1_000_000).contains(&b.arrival)
            || !(0..=1_000_000).contains(&b.departure)
            || b.departure <= b.arrival
        {
            return fail("BAD_BOOKING", Some(i));
        }
        bs.push((p, b.arrival, b.departure));
    }
    let n = r.departure - r.arrival;
    if !(1..=30).contains(&n) {
        return fail("BAD_STAY", None);
    }
    if r.adults + r.children > if prop == "CEDAR" { 4 } else { 6 } {
        return fail("OVER_CAPACITY", None);
    }
    let mut counts = [0i64; 3];
    for day in r.arrival..r.departure {
        let p = day.rem_euclid(365);
        counts[if p < 120 {
            0
        } else if p < 240 {
            1
        } else {
            2
        }] += 1;
    }
    if (counts[0] > 0 && n < 1) || (counts[1] > 0 && n < 3) || (counts[2] > 0 && n < 2) {
        return fail("MIN_STAY", None);
    }
    for (i, (p, a, b)) in bs.iter().enumerate() {
        if p == &prop && r.arrival < *b && *a < r.departure {
            return fail("UNAVAILABLE", Some(i));
        }
    }
    if promo != "" && promo != "PCT10" && promo != "FIXED5000" && promo != "ONENIGHT" {
        return fail("BAD_PROMO", None);
    }
    let mut lines = Vec::<NightLine>::new();
    let mut subtotal = 0i128;
    for day in r.arrival..r.departure {
        let p = day.rem_euclid(365);
        let (season, base) = if p < 120 {
            ("LOW", 5000)
        } else if p < 240 {
            ("PEAK", 9000)
        } else {
            ("SHOULDER", 6500)
        };
        let weekend = if day.rem_euclid(7) == 4 || day.rem_euclid(7) == 5 {
            1500
        } else {
            0
        };
        let cents = base + weekend;
        subtotal += cents as i128;
        lines.push(NightLine {
            day,
            season: season.into(),
            base_cents: base,
            weekend_cents: weekend,
            night_cents: cents,
        });
    }
    let cleaning = 4500i64;
    let guest = (2000 * (r.adults - 2).max(0) + 1000 * r.children) * n;
    let tax = 800 * (r.adults + r.children) * n.min(5);
    let extras_fee: i64 = extras
        .iter()
        .map(|x| if x == "PARKING" { 1200 * n } else { 2500 })
        .sum();
    let pre = subtotal + cleaning as i128 + guest as i128 + tax as i128 + extras_fee as i128;
    let rate = if n >= 14 {
        15
    } else if n >= 7 {
        10
    } else {
        0
    };
    let long = rhu(subtotal * rate, 100) as i128;
    let rem = pre - long;
    let promo_cut = match promo.as_str() {
        "PCT10" => rhu(rem * 10, 100) as i128,
        "FIXED5000" => 5000i128.min(rem),
        "ONENIGHT" => lines.iter().map(|x| x.night_cents).min().unwrap_or(0) as i128,
        _ => 0,
    };
    let total = (rem - promo_cut) as i64;
    let deposit = total.min(10_000.max(rhu(total as i128 * 30, 100)));
    let flags = [
        (lines.iter().any(|x| x.weekend_cents > 0), "weekend"),
        (true, "cleaning"),
        (guest > 0, "extra-guests"),
        (tax > 0, "tourist-tax"),
        (extras.contains(&"PARKING".into()), "parking"),
        (extras.contains(&"PET".into()), "pet"),
        (long > 0, "long-stay"),
        (promo_cut > 0, "promo"),
        (total > 0, "deposit"),
    ];
    let applied = flags
        .iter()
        .filter(|x| x.0)
        .map(|x| x.1.to_string())
        .collect();
    let cancellation = if r.arrival >= 30 {
        "FLEX"
    } else if r.arrival >= 7 {
        "STANDARD"
    } else {
        "FIRM"
    };
    Outcome::Quote(Quote {
        nights: n,
        night_lines: lines,
        cleaning_fee: cleaning,
        extra_guest_fee: guest,
        tourist_tax: tax,
        extras_fee,
        long_stay_discount: long as i64,
        promo_discount: promo_cut as i64,
        total,
        deposit,
        balance_due: total - deposit,
        applied,
        cancellation: cancellation.into(),
    })
}
fn check(r: Request) {
    assert_eq!(solution(&r), oracle(&r), "{r:?}");
}
#[test]
fn contract_examples_and_boundaries() {
    let mut r = req();
    check(r.clone());
    r.arrival = 11;
    r.departure = 12;
    check(r.clone());
    r.arrival = 120;
    r.departure = 121;
    assert_eq!(solution(&r), fail("MIN_STAY", None));
    r.arrival = 120;
    r.departure = 123;
    check(r.clone());
    r.arrival = 14;
    r.departure = 21;
    check(r.clone());
    r = req();
    r.property_id = "LAKE".into();
    r.adults = 3;
    r.children = 2;
    r.departure = 12;
    r.extras = vec!["PARKING".into(), "PET".into()];
    check(r);
    for (arrival, departure, promo) in [
        (10, 11, "PCT10"),
        (120, 123, "FIXED5000"),
        (11, 12, "ONENIGHT"),
        (240, 247, ""),
        (364, 366, ""),
    ] {
        let mut x = req();
        x.arrival = arrival;
        x.departure = departure;
        x.promo_code = promo.into();
        check(x);
    }
    let mut x = req();
    x.property_id = " cedar ".into();
    x.promo_code = " pct10 ".into();
    check(x);
    for (a, b, code) in [
        (-1, 1, "BAD_DAYS"),
        (1_000_000, 1_000_001, "BAD_DAYS"),
        (10, 10, "BAD_DAYS"),
        (10, 42, "BAD_STAY"),
    ] {
        let mut x = req();
        x.arrival = a;
        x.departure = b;
        assert_eq!(solution(&x), fail(code, None));
    }
    for v in [9, 10] {
        let mut x = req();
        x.adults = v;
        assert_eq!(solution(&x), fail("BAD_ADULTS", None));
        let mut y = req();
        y.children = v;
        assert_eq!(solution(&y), fail("BAD_CHILDREN", None));
    }
    let mut x = req();
    x.extras = vec!["PET".into(), "BAD".into()];
    assert_eq!(solution(&x), fail("BAD_EXTRA", Some(1)));
    let mut x = req();
    x.extras = vec!["PET".into(), "PET".into()];
    assert_eq!(solution(&x), fail("BAD_EXTRA", Some(1)));
    let mut x = req();
    x.bookings = vec![booking("LAKE", 10, 11), booking("CEDAR", 10, 11)];
    assert_eq!(solution(&x), fail("UNAVAILABLE", Some(1)));
    let mut x = req();
    x.bookings = vec![booking("BAD", 4, 3); 101];
    assert_eq!(solution(&x), fail("BAD_BOOKING", None));
    let mut x = req();
    x.bookings = vec![booking("CEDAR", -1, 1)];
    assert_eq!(solution(&x), fail("BAD_BOOKING", Some(0)));
    let mut x = req();
    x.bookings = vec![booking("CEDAR", 0, 0)];
    assert_eq!(solution(&x), fail("BAD_BOOKING", Some(0)));
    for index in [1, 2] {
        let mut x = req();
        x.bookings = (0..=index)
            .map(|i| {
                if i == index {
                    booking("CEDAR", 0, 0)
                } else {
                    booking("LAKE", 20 + i as i64 * 2, 21 + i as i64 * 2)
                }
            })
            .collect();
        assert_eq!(solution(&x), fail("BAD_BOOKING", Some(index)));
    }
    for end in [1_000_000, 1_000_001] {
        let mut x = req();
        x.bookings = vec![booking("LAKE", 999_999, end)];
        assert_eq!(
            solution(&x),
            if end == 1_000_000 {
                oracle(&x)
            } else {
                fail("BAD_BOOKING", Some(0))
            }
        );
    }
    let mut x = req();
    x.adults = 4;
    x.children = 1;
    assert_eq!(solution(&x), fail("OVER_CAPACITY", None));
    let mut x = req();
    x.property_id = "LAKE".into();
    x.adults = 1;
    x.children = 6;
    assert_eq!(solution(&x), fail("OVER_CAPACITY", None));
    let mut x = req();
    x.arrival = 120;
    x.departure = 122;
    assert_eq!(solution(&x), fail("MIN_STAY", None));
    let mut x = req();
    x.arrival = 239;
    x.departure = 240;
    assert_eq!(solution(&x), fail("MIN_STAY", None));
    let mut x = req();
    x.arrival = 239;
    x.departure = 241;
    assert_eq!(solution(&x), fail("MIN_STAY", None));
    let mut x = req();
    x.arrival = 240;
    x.departure = 242;
    check(x);
    let mut x = req();
    x.bookings = (0..100)
        .map(|i| booking("LAKE", 100 + i * 2, 101 + i * 2))
        .collect();
    check(x);
    for start in [
        0, 6, 7, 13, 20, 30, 119, 120, 237, 239, 240, 363, 364, 365, 999_999,
    ] {
        let mut x = req();
        x.arrival = start;
        x.departure = start + 3;
        check(x);
    }
    for (arrival, cancellation) in [(6, "FIRM"), (7, "STANDARD"), (29, "STANDARD"), (30, "FLEX")] {
        let mut x = req();
        x.arrival = arrival;
        x.departure = arrival + 1;
        let Outcome::Quote(quote) = solution(&x) else {
            panic!("expected quote")
        };
        assert_eq!(quote.cancellation, cancellation);
    }
    for (a, b) in [(0, 1), (999_999, 1_000_000)] {
        let mut x = req();
        x.arrival = a;
        x.departure = b;
        check(x);
    }
    for (property, adults, children) in [
        (" cedar ", 2, 0),
        (" lake ", 6, 0),
        ("CEDAR", 1, 0),
        ("CEDAR", 8, 0),
        ("LAKE", 1, 8),
    ] {
        let mut x = req();
        x.property_id = property.into();
        x.adults = adults;
        x.children = children;
        check(x);
    }
    let mut x = req();
    x.extras = vec!["PARKING".into(); 5];
    assert_eq!(solution(&x), fail("BAD_EXTRA", None));
    let mut x = req();
    x.extras = vec![
        "PET".into(),
        "PARKING".into(),
        "PET".into(),
        "PARKING".into(),
    ];
    assert_eq!(solution(&x), fail("BAD_EXTRA", Some(2)));
    let mut x = req();
    x.bookings = vec![booking("LAKE", 10, 11); 101];
    assert_eq!(solution(&x), fail("BAD_BOOKING", None));
    for (a, b) in [(0, 1), (9, 10), (11, 12)] {
        let mut x = req();
        x.bookings = vec![booking("CEDAR", a, b)];
        check(x);
    }
    for end in [6, 7, 13, 14, 19, 30] {
        let mut x = req();
        x.arrival = 0;
        x.departure = end;
        check(x);
    }
    for promo in ["PCT10", "FIXED5000", "ONENIGHT"] {
        let mut x = req();
        x.arrival = 0;
        x.departure = 1;
        x.promo_code = promo.into();
        check(x);
    }
    let mut x = req();
    x.arrival = 0;
    x.departure = 19;
    let Outcome::Quote(q) = solution(&x) else {
        panic!("expected quote")
    };
    assert_eq!(q.deposit, 29888);
}
#[test]
fn seeded_random_valid_and_invalid_mix_matches_oracle() {
    use std::collections::BTreeSet;
    let mut state = 20261018u64;
    let mut next = || {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        state
    };
    let mut valid = 0;
    let mut invalid = 0;
    let (mut properties, mut promos, mut seasons, mut weekdays, mut errors) = (
        BTreeSet::new(),
        BTreeSet::new(),
        BTreeSet::new(),
        BTreeSet::new(),
        BTreeSet::new(),
    );
    for iteration in 0..6000 {
        let mut r = req();
        let prop = if next() % 2 == 0 { "CEDAR" } else { "LAKE" };
        r.property_id = prop.into();
        let phase = match next() % 3 {
            0 => next() % 80,
            1 => 120 + next() % 70,
            _ => 240 + next() % 80,
        };
        let year = (next() % 200) * 365;
        r.arrival = (year + phase) as i64;
        properties.insert(prop.to_string());
        seasons.insert(if phase < 120 {
            "LOW"
        } else if phase < 240 {
            "PEAK"
        } else {
            "SHOULDER"
        });
        weekdays.insert(r.arrival.rem_euclid(7));
        let min = if phase < 120 {
            1
        } else if phase < 240 {
            3
        } else {
            2
        };
        r.departure = r.arrival + min + (next() % ((31 - min) as u64)) as i64;
        let cap = if prop == "CEDAR" { 4 } else { 6 };
        let guests = 1 + (next() % cap as u64) as i64;
        r.adults = 1 + (next() % guests as u64) as i64;
        r.children = guests - r.adults;
        r.extras = match iteration % 3 {
            0 => vec!["PARKING".into()],
            1 => vec!["PET".into()],
            _ => vec![],
        };
        let promo = ["", "PCT10", "FIXED5000", "ONENIGHT"][iteration as usize % 4];
        r.promo_code = promo.into();
        promos.insert(promo);
        if iteration % 3 == 0 {
            match (iteration / 3) % 11 {
                0 => r.property_id = "UNKNOWN".into(),
                1 => r.adults = 0,
                2 => r.children = 9,
                3 => r.arrival = -1,
                4 => r.extras = vec!["BAD".into()],
                5 => r.bookings = vec![booking("CEDAR", -1, 1)],
                6 => r.departure = r.arrival + 31,
                7 => {
                    r.property_id = "LAKE".into();
                    r.adults = 1;
                    r.children = 6;
                }
                8 => {
                    r.arrival = (iteration as i64 / 3 / 11) * 365 + 120;
                    r.departure = r.arrival + 1;
                }
                9 => r.bookings = vec![booking(prop, r.arrival, r.departure)],
                _ => r.promo_code = "UNKNOWN".into(),
            }
            if let Outcome::Error { code, .. } = oracle(&r) {
                errors.insert(code);
            }
            invalid += 1;
        } else {
            valid += 1;
        }
        check(r);
    }
    println!("random summary: valid={valid}, invalid={invalid}, properties={properties:?}, promos={promos:?}, seasons={seasons:?}, weekdays={weekdays:?}, errors={errors:?}");
    assert!(valid >= 3000 && valid >= invalid);
    assert!(
        properties.len() == 2 && promos.len() == 4 && seasons.len() == 3 && weekdays.len() == 7
    );
    for code in [
        "BAD_PROPERTY",
        "BAD_ADULTS",
        "BAD_CHILDREN",
        "BAD_DAYS",
        "BAD_EXTRA",
        "BAD_BOOKING",
        "BAD_STAY",
        "OVER_CAPACITY",
        "MIN_STAY",
        "UNAVAILABLE",
        "BAD_PROMO",
    ] {
        assert!(errors.contains(code), "missing generated error {code}");
    }
}
