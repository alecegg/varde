use corpus::{solution, Line, Outcome, Quote, QuoteError, RawItem, Request};

fn item(sku: &str, qty: i64, price: &str) -> RawItem {
    RawItem {
        sku: sku.to_string(),
        qty,
        price: price.to_string(),
    }
}

fn request(items: Vec<RawItem>, tier: &str, coupon: &str, region: &str) -> Request {
    Request {
        items,
        tier: tier.to_string(),
        coupon: coupon.to_string(),
        region: region.to_string(),
    }
}

fn line(sku: &str, qty: i64, unit_cents: i64, line_cents: i64) -> Line {
    Line {
        sku: sku.to_string(),
        qty,
        unit_cents,
        line_cents,
    }
}

fn quote(
    lines: Vec<Line>,
    subtotal: i64,
    tier_discount: i64,
    coupon_discount: i64,
    shipping: i64,
    tax: i64,
    total: i64,
    applied: &[&str],
) -> Outcome {
    Outcome::Quote(Quote {
        lines,
        subtotal,
        tier_discount,
        coupon_discount,
        shipping,
        tax,
        total,
        applied: applied.iter().map(|s| s.to_string()).collect(),
    })
}

fn error(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error(QuoteError {
        code: code.to_string(),
        index,
    })
}

fn round_ratio(numerator: i128, denominator: i128) -> i128 {
    let whole = numerator / denominator;
    let remainder = numerator % denominator;
    whole + i128::from(remainder * 2 >= denominator)
}

fn price_cents(text: &str) -> Option<i128> {
    let has_decimal = text.contains('.');
    let mut pieces = text.split('.');
    let whole = pieces.next()?;
    let fraction = pieces.next().unwrap_or("");
    if pieces.next().is_some()
        || whole.is_empty()
        || whole.len() > 6
        || (has_decimal && fraction.is_empty())
        || fraction.len() > 2
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || !fraction.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    let units = whole.parse::<i128>().ok()?;
    let cents = match fraction.len() {
        0 => 0,
        1 => fraction.parse::<i128>().ok()? * 10,
        _ => fraction.parse::<i128>().ok()?,
    };
    let value = units * 100 + cents;
    (value > 0).then_some(value)
}

fn coupon_value(coupon: &str) -> Option<(bool, i128)> {
    if coupon == "FREESHIP" {
        return Some((true, 0));
    }
    for (prefix, max, is_percent) in [("PCT", 50, true), ("FIXED", 500, false)] {
        if let Some(suffix) = coupon.strip_prefix(prefix) {
            if suffix.is_empty()
                || suffix.starts_with('0')
                || !suffix.bytes().all(|b| b.is_ascii_digit())
            {
                return None;
            }
            let amount = suffix.parse::<i128>().ok()?;
            return (1..=max).contains(&amount).then_some((is_percent, amount));
        }
    }
    None
}

fn oracle(given: &Request) -> Outcome {
    if given.items.is_empty() {
        return error("EMPTY_ORDER", None);
    }
    if given.items.len() > 50 {
        return error("TOO_MANY_ITEMS", None);
    }

    let mut checked = Vec::with_capacity(given.items.len());
    for (index, raw) in given.items.iter().enumerate() {
        let sku = raw.sku.trim().to_ascii_uppercase();
        if !(3..=12).contains(&sku.len())
            || !sku
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'-')
        {
            return error("BAD_SKU", Some(index));
        }
        if !(1..=1000).contains(&raw.qty) {
            return error("BAD_QTY", Some(index));
        }
        let Some(cents) = price_cents(&raw.price) else {
            return error("BAD_PRICE", Some(index));
        };
        checked.push((sku, raw.qty, cents));
    }

    let mut merged: Vec<(String, i64, i128)> = Vec::new();
    for (index, (sku, qty, cents)) in checked.into_iter().enumerate() {
        if let Some((_, old_qty, old_cents)) = merged.iter_mut().find(|row| row.0 == sku) {
            if *old_cents != cents {
                return error("PRICE_CONFLICT", Some(index));
            }
            *old_qty += qty;
            if *old_qty > 1000 {
                return error("BAD_QTY", Some(index));
            }
        } else {
            merged.push((sku, qty, cents));
        }
    }

    let tier = given.tier.trim().to_ascii_lowercase();
    let coupon = given.coupon.trim().to_ascii_uppercase();
    let region = given.region.trim().to_ascii_uppercase();
    let tier_rate = match tier.as_str() {
        "basic" => 0,
        "silver" => 500,
        "gold" => 1000,
        _ => return error("BAD_TIER", None),
    };
    let coupon = match coupon_value(&coupon) {
        Some(value) => value,
        None if given.coupon.trim().is_empty() => (false, 0),
        None => return error("BAD_COUPON", None),
    };
    let (tax_rate, base_shipping, threshold) = match region.as_str() {
        "EU" => (2000, 800, 10000),
        "US" => (700, 500, 7500),
        "ASIA" => (1000, 1200, 15000),
        _ => return error("BAD_REGION", None),
    };

    merged.sort_by(|left, right| left.0.cmp(&right.0));
    let lines: Vec<Line> = merged
        .iter()
        .map(|(sku, qty, unit)| Line {
            sku: sku.clone(),
            qty: *qty,
            unit_cents: *unit as i64,
            line_cents: (*unit * i128::from(*qty)) as i64,
        })
        .collect();
    let subtotal: i128 = lines.iter().map(|row| i128::from(row.line_cents)).sum();
    let tier_discount = round_ratio(subtotal * tier_rate, 10_000);
    let after_tier = subtotal - tier_discount;
    let coupon_discount = if coupon.1 == 0 {
        0
    } else if coupon.0 {
        round_ratio(after_tier * coupon.1, 100)
    } else {
        (coupon.1 * 100).min(after_tier)
    };
    let net = after_tier - coupon_discount;
    let free_shipping = given.coupon.trim().eq_ignore_ascii_case("FREESHIP") || net >= threshold;
    let shipping = if free_shipping { 0 } else { base_shipping };
    let tax = round_ratio(net * tax_rate, 10_000);
    let mut applied = Vec::new();
    if tier_discount > 0 {
        applied.push("tier".to_string());
    }
    if coupon_discount > 0 {
        applied.push("coupon".to_string());
    }
    if shipping == 0 {
        applied.push("free-shipping".to_string());
    }
    if tax > 0 {
        applied.push("tax".to_string());
    }
    Outcome::Quote(Quote {
        lines,
        subtotal: subtotal as i64,
        tier_discount: tier_discount as i64,
        coupon_discount: coupon_discount as i64,
        shipping,
        tax: tax as i64,
        total: (net + i128::from(shipping) + tax) as i64,
        applied,
    })
}

fn assert_matches(given: &Request) {
    assert_eq!(solution(given), oracle(given), "request: {given:?}");
}

#[test]
fn matches_the_seven_worked_example_groups() {
    let cases = [
        (
            request(
                vec![item(" ab-12 ", 2, "10.00"), item("CD-34", 1, "5.50")],
                "Silver",
                "",
                "us",
            ),
            quote(
                vec![line("AB-12", 2, 1000, 2000), line("CD-34", 1, 550, 550)],
                2550,
                128,
                0,
                500,
                170,
                3092,
                &["tier", "tax"],
            ),
        ),
        (
            request(vec![item("X1X", 10, "20.00")], "gold", "pct10", "EU"),
            quote(
                vec![line("X1X", 10, 2000, 20000)],
                20000,
                2000,
                1800,
                0,
                3240,
                19440,
                &["tier", "coupon", "free-shipping", "tax"],
            ),
        ),
        (
            request(
                vec![item("aaa", 3, "1.00"), item("AAA", 4, "1")],
                "basic",
                "FIXED5",
                "ASIA",
            ),
            quote(
                vec![line("AAA", 7, 100, 700)],
                700,
                0,
                500,
                1200,
                20,
                1420,
                &["coupon", "tax"],
            ),
        ),
        (
            request(vec![item("ZZZ", 1, "0.01")], "silver", " freeship ", "EU"),
            quote(
                vec![line("ZZZ", 1, 1, 1)],
                1,
                0,
                0,
                0,
                0,
                1,
                &["free-shipping"],
            ),
        ),
        (
            request(vec![item("RND", 1, "2.50")], "basic", "", "US"),
            quote(
                vec![line("RND", 1, 250, 250)],
                250,
                0,
                0,
                500,
                18,
                768,
                &["tax"],
            ),
        ),
        (
            request(vec![item("CAP", 1, "3.00")], "basic", "FIXED500", "US"),
            quote(
                vec![line("CAP", 1, 300, 300)],
                300,
                0,
                300,
                500,
                0,
                500,
                &["coupon"],
            ),
        ),
    ];
    for (given, expected) in cases {
        assert_eq!(solution(&given), expected, "request: {given:?}");
        assert_matches(&given);
    }

    let failures = [
        (
            request(vec![], "basic", "", "EU"),
            error("EMPTY_ORDER", None),
        ),
        (
            request(vec![item("a", 1, "1")], "basic", "", "EU"),
            error("BAD_SKU", Some(0)),
        ),
        (
            request(vec![item("ABC", 0, "1")], "basic", "", "EU"),
            error("BAD_QTY", Some(0)),
        ),
        (
            request(vec![item("ABC", 1, "1.234")], "basic", "", "EU"),
            error("BAD_PRICE", Some(0)),
        ),
        (
            request(
                vec![item("ABC", 1, "1"), item("abc", 1, "2")],
                "basic",
                "",
                "EU",
            ),
            error("PRICE_CONFLICT", Some(1)),
        ),
        (
            request(
                vec![item("ABC", 600, "1"), item("abc", 500, "1.0")],
                "basic",
                "",
                "EU",
            ),
            error("BAD_QTY", Some(1)),
        ),
        (
            request(
                vec![item("ABC", 500, "1"), item("abc", 501, "1.00")],
                "basic",
                "",
                "EU",
            ),
            error("BAD_QTY", Some(1)),
        ),
        (
            request(
                vec![item("ABC", 600, "1"), item("abc", 500, "2")],
                "basic",
                "",
                "EU",
            ),
            error("PRICE_CONFLICT", Some(1)),
        ),
        (
            request(vec![item("ABC", 1, "1")], "platinum", "", "EU"),
            error("BAD_TIER", None),
        ),
        (
            request(vec![item("ABC", 1, "1")], "platinum", "PCT0", "MARS"),
            error("BAD_TIER", None),
        ),
        (
            request(vec![item("ABC", 1, "1")], "basic", "PCT0", "EU"),
            error("BAD_COUPON", None),
        ),
        (
            request(vec![item("ABC", 1, "1")], "basic", "", "MARS"),
            error("BAD_REGION", None),
        ),
        (
            request(vec![item("ABC", 1, "0")], "basic", "", "EU"),
            error("BAD_PRICE", Some(0)),
        ),
        (
            request(vec![item("ABC", 1, "0.00")], "basic", "", "EU"),
            error("BAD_PRICE", Some(0)),
        ),
    ];
    for (given, expected) in failures {
        assert_eq!(solution(&given), expected, "request: {given:?}");
        assert_matches(&given);
    }
}

#[test]
fn checks_all_validation_precedence_and_text_boundaries() {
    let mut cases = Vec::new();
    for sku in ["AB", "ABCDEFGHIJKLM", "AB_", "AB ", "ÄBC"] {
        cases.push((
            request(vec![item(sku, 1, "1")], "basic", "", "EU"),
            error("BAD_SKU", Some(0)),
        ));
    }
    for qty in [0, -1, 1001] {
        cases.push((
            request(vec![item("ABC", qty, "1")], "basic", "", "EU"),
            error("BAD_QTY", Some(0)),
        ));
    }
    for price in [
        "0", "0.00", "1.234", "abc", "", "1234567", "1000000", ".50", ".5", "1.", "+1", "-1", " 1",
        "1 ", "1 0", "1,5", "1a", "1e3",
    ] {
        cases.push((
            request(vec![item("ABC", 1, price)], "basic", "", "EU"),
            error("BAD_PRICE", Some(0)),
        ));
    }
    for coupon in [
        "PCT0", "PCT51", "PCT07", "FIXED0", "FIXED501", "FIXED05", "PCT", "PCTX", "FIXED1A",
        "PCT-5", "PCT5.0", "FIXED 5", "OTHER",
    ] {
        cases.push((
            request(vec![item("ABC", 1, "1")], "basic", coupon, "EU"),
            error("BAD_COUPON", None),
        ));
    }
    cases.extend([
        (
            request(vec![item("ABC", 1, "1"); 51], "bad", "", "EU"),
            error("TOO_MANY_ITEMS", None),
        ),
        (
            request(
                vec![
                    item("ABC", 1, "1"),
                    item("BAD", 0, "bad"),
                    item("BAD", 1, "1"),
                ],
                "basic",
                "",
                "EU",
            ),
            error("BAD_QTY", Some(1)),
        ),
        (
            request(
                vec![
                    item("ABC", 1, "1"),
                    item("abc", 1, "2"),
                    item("bad", 0, "1"),
                ],
                "basic",
                "",
                "EU",
            ),
            error("BAD_QTY", Some(2)),
        ),
        (
            request(
                vec![item("ABC", 1, "1"), item("abc", 0, "2")],
                "basic",
                "",
                "EU",
            ),
            error("BAD_QTY", Some(1)),
        ),
        (
            request(vec![item("ABC", 1, "1")], "bad", "PCT0", "MARS"),
            error("BAD_TIER", None),
        ),
        (
            request(vec![item("ABC", 1, "1")], "basic", "PCT0", "MARS"),
            error("BAD_COUPON", None),
        ),
        (
            request(
                vec![item("ABC", 1, "1"), item("abc", 1, "2")],
                "bad",
                "PCT0",
                "MARS",
            ),
            error("PRICE_CONFLICT", Some(1)),
        ),
        (
            request(vec![item("ABC", 1, "1")], "basic", "", "mars"),
            error("BAD_REGION", None),
        ),
    ]);
    for (given, expected) in cases {
        assert_eq!(solution(&given), expected, "request: {given:?}");
        assert_matches(&given);
    }
}

#[test]
fn matches_rounding_shipping_merge_sort_and_size_boundaries() {
    let ties = [
        request(vec![item("TIE", 1, "0.10")], "silver", "", "EU"),
        request(vec![item("TIE", 1, "0.05")], "basic", "PCT10", "US"),
        request(vec![item("TIE", 1, "0.50")], "basic", "", "US"),
    ];
    let expected = [
        quote(
            vec![line("TIE", 1, 10, 10)],
            10,
            1,
            0,
            800,
            2,
            811,
            &["tier", "tax"],
        ),
        quote(
            vec![line("TIE", 1, 5, 5)],
            5,
            0,
            1,
            500,
            0,
            504,
            &["coupon"],
        ),
        quote(
            vec![line("TIE", 1, 50, 50)],
            50,
            0,
            0,
            500,
            4,
            554,
            &["tax"],
        ),
    ];
    for (given, expected) in ties.into_iter().zip(expected) {
        assert_eq!(solution(&given), expected, "request: {given:?}");
        assert_matches(&given);
    }

    for (region, threshold) in [("EU", 10_000), ("US", 7_500), ("ASIA", 15_000)] {
        for amount in [threshold - 1, threshold] {
            let given = request(
                vec![item(
                    "EDGE",
                    1,
                    &format!("{}.{:02}", amount / 100, amount % 100),
                )],
                "basic",
                "",
                region,
            );
            assert_matches(&given);
        }
    }
    for quantities in [(500, 500), (999, 1)] {
        assert_matches(&request(
            vec![
                item("ABC", quantities.0, "1"),
                item("abc", quantities.1, "1.00"),
            ],
            "basic",
            "",
            "EU",
        ));
    }
    for (region, threshold) in [("EU", 10_000), ("US", 7_500), ("ASIA", 15_000)] {
        let subtotal = threshold * 112 / 100;
        let given = request(
            vec![item(
                "EDGE",
                1,
                &format!("{}.{:02}", subtotal / 100, subtotal % 100),
            )],
            "gold",
            "PCT10",
            region,
        );
        match oracle(&given) {
            Outcome::Quote(expected) => {
                assert!(expected.subtotal >= threshold);
                assert!(expected.subtotal - expected.tier_discount >= threshold);
                assert!(
                    expected.subtotal - expected.tier_discount - expected.coupon_discount
                        < threshold
                );
                assert!(expected.shipping > 0);
            }
            other => panic!("unexpected oracle result: {other:?}"),
        }
        assert_matches(&given);
    }

    let sorted = request(
        vec![
            item("a1x", 1, "1"),
            item("A1X", 1, "1"),
            item("A-1", 1, "1"),
            item("A01", 1, "1"),
        ],
        "basic",
        "",
        "EU",
    );
    assert_matches(&sorted);
    let fifty = request(
        (0..50)
            .map(|index| item(&format!("S{index:02}"), index as i64 + 1, "1.25"))
            .collect(),
        "gold",
        "PCT7",
        "ASIA",
    );
    assert_matches(&fifty);
}

struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }

    fn choose<'a>(&mut self, values: &'a [&'a str]) -> &'a str {
        values[(self.next() as usize) % values.len()]
    }
}

#[test]
fn matches_the_independent_oracle_on_seeded_random_ascii_requests() {
    let mut rng = Lcg(20_261_017);
    let skus = [
        "A-1",
        "A1B",
        "x9-y",
        "SKU-7",
        "ABC",
        "Q-42",
        "ab",
        "ABCDEFGHIJKLM",
        "AB_",
        " ",
    ];
    let prices = [
        "0.01",
        "1",
        "1.2",
        "12.34",
        "999999.99",
        "0",
        "1.234",
        "bad",
        "1234567",
        "",
        "1,5",
        "1a",
        "1e3",
        "+1",
        "-1",
        "1 0",
        "1.",
        ".5",
    ];
    let quantities = [1, 2, 10, 999, 1000, 0, -1, 1001];
    let tiers = ["basic", "silver", "gold", "platinum", " Silver "];
    let coupons = [
        "", "PCT1", "PCT7", "PCT50", "PCT0", "PCT07", "FIXED1", "FIXED500", "FIXED501", "FREESHIP",
        " pct10 ", "PCTX", "FIXED1A", "PCT-5", "PCT5.0", "FIXED 5",
    ];
    let regions = ["EU", "US", "ASIA", "MARS", " us "];
    for round in 0..4_000 {
        let count = (rng.next() % 7) as usize;
        let mut rows = Vec::with_capacity(count);
        for _ in 0..count {
            rows.push(item(
                rng.choose(&skus),
                quantities[(rng.next() as usize) % quantities.len()],
                rng.choose(&prices),
            ));
        }
        let given = request(
            rows,
            rng.choose(&tiers),
            rng.choose(&coupons),
            rng.choose(&regions),
        );
        assert_eq!(
            solution(&given),
            oracle(&given),
            "random case {round}: {given:?}"
        );
    }
}

#[test]
fn handles_domain_maximum_values_without_overflow() {
    let maximum_items = || {
        (0..50)
            .map(|index| item(&format!("S{index:02}"), 1000, "999999.99"))
            .collect()
    };

    for (tier, coupon, region) in [
        ("basic", "", "EU"),
        ("silver", "PCT50", "US"),
        ("gold", "FIXED500", "ASIA"),
        ("gold", "FREESHIP", "EU"),
    ] {
        assert_matches(&request(maximum_items(), tier, coupon, region));
    }
}
