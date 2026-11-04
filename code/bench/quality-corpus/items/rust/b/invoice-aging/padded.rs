use std::collections::BTreeSet;

pub const BUCKETS: [&str; 5] = ["current", "1-30", "31-60", "61-90", "over-90"];
const BOUNDS: [i64; 4] = [1, 31, 61, 91];
const RATES: [i64; 5] = [0, 2, 5, 8, 10];
const LIMIT_CENTS: i64 = 100_000_000;
const MAX_INVOICES: usize = 1_000;

type Totals = [i64; 5];

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
    assemble(gathered(ensure_valid(invoices)?), accumulated(invoices))
}

fn assemble(invoices: Vec<InvoiceRow>, totals: Totals) -> Result<Report, InvoiceError> {
    Ok(Report { invoices, totals })
}

fn gathered(invoices: &[Invoice]) -> Vec<InvoiceRow> {
    let collected: Vec<InvoiceRow> = invoices.iter().map(describe).collect();
    in_order(collected)
}

fn in_order(rows: Vec<InvoiceRow>) -> Vec<InvoiceRow> {
    let unique: BTreeSet<InvoiceRow> = BTreeSet::from_iter(rows);
    unique.into_iter().collect()
}

fn describe(invoice: &Invoice) -> InvoiceRow {
    let identifier = invoice.id.clone();
    let bucket = bucket_name(invoice);
    let fee = rounded_fee(invoice);
    row(identifier, bucket, fee)
}

fn row(identifier: String, bucket: &'static str, fee: i64) -> InvoiceRow {
    InvoiceRow {
        id: identifier,
        bucket,
        fee,
    }
}

fn bucket_name(invoice: &Invoice) -> &'static str {
    let number = bucket_number(invoice.days_overdue);
    BUCKETS[number]
}

fn rounded_fee(invoice: &Invoice) -> i64 {
    let bucket = bucket_number(invoice.days_overdue);
    let percent = RATES[bucket];
    let exact = invoice.balance_cents * percent;
    (exact + 50) / 100
}

fn bucket_number(days_overdue: i64) -> usize {
    let mut passed = 0;
    for bound in BOUNDS {
        if days_overdue >= bound {
            passed += 1;
        }
    }
    passed
}

fn ensure_valid(invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    let accepted = rules_hold(invoices);
    decide(accepted, invoices)
}

fn decide(accepted: bool, invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    let invalid = InvoiceError::InvalidInvoice;
    if accepted {
        return Ok(invoices);
    }
    Err(invalid)
}

fn rules_hold(invoices: &[Invoice]) -> bool {
    let within_limit = invoices.len() <= MAX_INVOICES;
    let names_fit = names_ok(invoices);
    let amounts_fit = amounts_within(invoices);
    within_limit && names_fit && amounts_fit
}

fn names_ok(invoices: &[Invoice]) -> bool {
    let every_name = invoices.iter().all(name_valid);
    let distinct = identifier_set(invoices).len() == invoices.len();
    every_name && distinct
}

fn name_valid(invoice: &Invoice) -> bool {
    let has_text = !invoice.id.is_empty();
    let ascii_text = invoice.id.is_ascii();
    has_text && ascii_text
}

fn identifier_set(invoices: &[Invoice]) -> BTreeSet<&str> {
    let mut seen = BTreeSet::new();
    for invoice in invoices {
        seen.insert(invoice.id.as_str());
    }
    seen
}

fn amounts_within(invoices: &[Invoice]) -> bool {
    let mut amounts = invoices.iter().map(|invoice| invoice.balance_cents);
    amounts.all(in_bounds)
}

fn in_bounds(amount: i64) -> bool {
    let negative = amount < 0;
    let above_limit = amount > LIMIT_CENTS;
    !negative && !above_limit
}

fn accumulated(invoices: &[Invoice]) -> Totals {
    let mut sums = [0; 5];
    for (bucket, sum) in sums.iter_mut().enumerate() {
        *sum = bucket_sum(invoices, bucket);
    }
    sums
}

fn bucket_sum(invoices: &[Invoice], bucket: usize) -> i64 {
    let mut running = 0;
    for invoice in invoices {
        running += share_of(invoice, bucket);
    }
    running
}

fn share_of(invoice: &Invoice, bucket: usize) -> i64 {
    let in_bucket = bucket_number(invoice.days_overdue) == bucket;
    if in_bucket {
        return invoice.balance_cents;
    }
    0
}
