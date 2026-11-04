use std::collections::BTreeSet;

pub const BUCKETS: [&str; 5] = ["current", "1-30", "31-60", "61-90", "over-90"];
const BOUNDS: [i64; 4] = [1, 31, 61, 91];
const RATES: [i64; 5] = [0, 2, 5, 8, 10];
const LIMIT_CENTS: i64 = 100_000_000;
const MAX_INVOICES: usize = 1_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Invoice {
    pub id: String,
    pub days_overdue: i64,
    pub balance_cents: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct InvoiceRow {
    pub id: String,
    pub bucket: &'static str,
    pub fee: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Report {
    pub invoices: Vec<InvoiceRow>,
    pub totals: [i64; 5],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InvoiceError {
    InvalidInvoice,
}

type Outcome = Result<Report, InvoiceError>;

///
/// # Errors
///
/// Returns `Err(InvoiceError::InvalidInvoice)` when an id is empty, non-ASCII
/// or repeated, or a balance leaves the stated range.
/// Build an invoice aging report with each invoice bucket and fee, plus the
/// balance total for each bucket. Amounts are whole cents.
pub fn solution(invoices: &[Invoice]) -> Outcome {
    if !fields_ok(invoices) || !ids_ok(invoices) {
        return Err(InvoiceError::InvalidInvoice);
    }
    let buckets = invoice_buckets(invoices);
    let mut rows = invoice_rows(invoices, &buckets);
    rows.sort();
    Ok(Report {
        invoices: rows,
        totals: bucket_totals(invoices, &buckets),
    })
}

fn fields_ok(invoices: &[Invoice]) -> bool {
    invoices.len() <= MAX_INVOICES
        && invoices.iter().all(|i| {
            !i.id.is_empty() && i.id.is_ascii() && (0..=LIMIT_CENTS).contains(&i.balance_cents)
        })
}

fn ids_ok(invoices: &[Invoice]) -> bool {
    let ids: BTreeSet<&str> = invoices.iter().map(|i| i.id.as_str()).collect();
    ids.len() == invoices.len()
}

fn invoice_buckets(invoices: &[Invoice]) -> Vec<usize> {
    invoices
        .iter()
        .map(|invoice| {
            BOUNDS
                .iter()
                .filter(|bound| invoice.days_overdue >= **bound)
                .count()
        })
        .collect()
}

fn invoice_rows(invoices: &[Invoice], buckets: &[usize]) -> Vec<InvoiceRow> {
    invoices
        .iter()
        .zip(buckets)
        .map(|(invoice, &bucket)| InvoiceRow {
            id: invoice.id.clone(),
            bucket: BUCKETS[bucket],
            fee: (invoice.balance_cents * RATES[bucket] + 50) / 100,
        })
        .collect()
}

fn bucket_totals(invoices: &[Invoice], buckets: &[usize]) -> [i64; 5] {
    let mut totals = [0; 5];
    for (invoice, &bucket) in invoices.iter().zip(buckets) {
        totals[bucket] += invoice.balance_cents;
    }
    totals
}
