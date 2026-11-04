use corpus::{solution, Invoice, InvoiceError, InvoiceRow, Report};

fn cents(text: &str) -> i64 {
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    let units: i64 = whole.parse().unwrap();
    let hundredths: i64 = format!("{fraction:0<2}")[..2].parse().unwrap();
    units * 100 + hundredths
}

fn invoice(id: &str, days_overdue: i64, balance: &str) -> Invoice {
    Invoice {
        id: id.to_string(),
        days_overdue,
        balance_cents: cents(balance),
    }
}

fn row(id: &str, bucket: &'static str, fee: &str) -> InvoiceRow {
    InvoiceRow {
        id: id.to_string(),
        bucket,
        fee: cents(fee),
    }
}

fn report(invoices: Vec<InvoiceRow>, totals: [&str; 5]) -> Report {
    Report {
        invoices,
        totals: totals.map(cents),
    }
}

fn name(bucket: usize) -> &'static str {
    ["current", "1-30", "31-60", "61-90", "over-90"][bucket]
}

/// The stated rules, totalled with this test's own loops over whole cents.
fn reference(invoices: &[Invoice]) -> Result<Report, InvoiceError> {
    if invoices.len() > 1_000 {
        return Err(InvoiceError::InvalidInvoice);
    }
    let mut seen: Vec<&str> = Vec::new();
    for item in invoices {
        let bad_id = item.id.is_empty() || !item.id.is_ascii();
        let bad_amount = item.balance_cents < 0 || item.balance_cents > 100_000_000;
        if bad_id || bad_amount || seen.contains(&item.id.as_str()) {
            return Err(InvoiceError::InvalidInvoice);
        }
        seen.push(item.id.as_str());
    }
    let mut rows: Vec<InvoiceRow> = Vec::new();
    for item in invoices {
        let bucket = if item.days_overdue <= 0 {
            0
        } else if item.days_overdue <= 30 {
            1
        } else if item.days_overdue <= 60 {
            2
        } else if item.days_overdue <= 90 {
            3
        } else {
            4
        };
        let percent = [0, 2, 5, 8, 10][bucket];
        rows.push(InvoiceRow {
            id: item.id.clone(),
            bucket: name(bucket),
            fee: (item.balance_cents * percent + 50) / 100,
        });
    }
    rows.sort_by(|left, right| left.id.cmp(&right.id));
    let mut totals = [0; 5];
    for (bucket, total) in totals.iter_mut().enumerate() {
        for item in invoices {
            let days = item.days_overdue;
            let place = if days <= 0 {
                0
            } else if days <= 30 {
                1
            } else if days <= 60 {
                2
            } else if days <= 90 {
                3
            } else {
                4
            };
            if place == bucket {
                *total += item.balance_cents;
            }
        }
    }
    Ok(Report {
        invoices: rows,
        totals,
    })
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

#[test]
fn matches_the_stated_cases() {
    let cases: Vec<(Vec<Invoice>, Report)> = vec![
        (vec![], report(vec![], ["0", "0", "0", "0", "0"])),
        (
            vec![invoice("A", 0, "100")],
            report(vec![row("A", "current", "0")], ["100", "0", "0", "0", "0"]),
        ),
        (
            vec![invoice("A", 1, "100")],
            report(vec![row("A", "1-30", "2")], ["0", "100", "0", "0", "0"]),
        ),
        (
            vec![invoice("A", 30, "100")],
            report(vec![row("A", "1-30", "2")], ["0", "100", "0", "0", "0"]),
        ),
        (
            vec![invoice("A", 31, "200")],
            report(vec![row("A", "31-60", "10")], ["0", "0", "200", "0", "0"]),
        ),
        (
            vec![invoice("A", 60, "50")],
            report(vec![row("A", "31-60", "2.5")], ["0", "0", "50", "0", "0"]),
        ),
        (
            vec![invoice("A", 61, "100")],
            report(vec![row("A", "61-90", "8")], ["0", "0", "0", "100", "0"]),
        ),
        (
            vec![invoice("A", 90, "50")],
            report(vec![row("A", "61-90", "4")], ["0", "0", "0", "50", "0"]),
        ),
        (
            vec![invoice("A", 91, "300")],
            report(vec![row("A", "over-90", "30")], ["0", "0", "0", "0", "300"]),
        ),
        (
            vec![invoice("B", -2, "40")],
            report(vec![row("B", "current", "0")], ["40", "0", "0", "0", "0"]),
        ),
        (
            vec![
                invoice("B", -2, "40"),
                invoice("A", 31, "80"),
                invoice("C", 5, "50"),
            ],
            report(
                vec![
                    row("A", "31-60", "4"),
                    row("B", "current", "0"),
                    row("C", "1-30", "1"),
                ],
                ["40", "50", "80", "0", "0"],
            ),
        ),
    ];
    for (given, expected) in cases {
        assert_eq!(solution(&given), Ok(expected), "{given:?}");
    }
}

#[test]
fn reads_amounts_as_the_decimal_they_were_written_as() {
    let cases: Vec<(Vec<Invoice>, Report)> = vec![
        (
            vec![invoice("A", 31, "40.05")],
            report(vec![row("A", "31-60", "2")], ["0", "0", "40.05", "0", "0"]),
        ),
        (
            vec![invoice("A", 1, "16.60")],
            report(vec![row("A", "1-30", "0.33")], ["0", "16.6", "0", "0", "0"]),
        ),
        (
            vec![invoice("A", 1, "0.25")],
            report(vec![row("A", "1-30", "0.01")], ["0", "0.25", "0", "0", "0"]),
        ),
        (
            vec![invoice("A", 91, "1000000")],
            report(
                vec![row("A", "over-90", "100000")],
                ["0", "0", "0", "0", "1000000"],
            ),
        ),
    ];
    for (given, expected) in cases {
        assert_eq!(solution(&given), Ok(expected), "{given:?}");
    }
}

#[test]
fn rejects_invoices_outside_the_stated_domain() {
    let rejected: Vec<Vec<Invoice>> = vec![
        vec![invoice("", 1, "10")],
        vec![invoice("naïve", 1, "10")],
        vec![invoice("A", 1, "10"), invoice("A", -1, "20")],
        vec![invoice("A", 1, "-1")],
        vec![invoice("A", 1, "1000000.01")],
        (0..1_001)
            .map(|index| invoice(&format!("Z{index}"), index - 5, "10"))
            .collect(),
    ];
    for given in rejected {
        assert_eq!(
            solution(&given),
            Err(InvoiceError::InvalidInvoice),
            "{:?}",
            given.len()
        );
    }
}

#[test]
fn matches_the_reference_on_random_invoices() {
    let mut rng = Rng(20_261_017);
    for round in 0..4 {
        let count = 600 + (rng.next() % 300) as usize;
        let mut invoices = Vec::with_capacity(count);
        for index in 0..count {
            let cents = (rng.next() % 100_000_001) as i64;
            let days = (rng.next() % 231) as i64 - 30;
            let id = format!("X{:05}-{round}-{index}", count - index);
            invoices.push(Invoice {
                id,
                days_overdue: days,
                balance_cents: cents,
            });
        }
        let order: Vec<&str> = invoices.iter().map(|item| item.id.as_str()).collect();
        let mut sorted = order.clone();
        sorted.sort_unstable();
        assert_ne!(order, sorted);
        assert_eq!(solution(&invoices), reference(&invoices), "{round}");
    }
}

#[test]
fn matches_the_reference_on_the_largest_stated_batch() {
    let mut invoices = Vec::with_capacity(1_000);
    for index in 0..1_000i64 {
        invoices.push(Invoice {
            id: format!("Q{:04}", 1_000 - index),
            days_overdue: index % 120 - 10,
            balance_cents: (index * 97_531) % 100_000_001,
        });
    }
    assert_eq!(solution(&invoices), reference(&invoices));
    let reported = solution(&invoices).unwrap();
    assert_eq!(reported.invoices.len(), 1_000);
    let mut ordered: Vec<&str> = reported.invoices.iter().map(|r| r.id.as_str()).collect();
    let expected: Vec<String> = (1..=1_000).map(|n| format!("Q{n:04}")).collect();
    assert_eq!(ordered, expected);
    ordered.reverse();
    assert_ne!(ordered, expected);
}
