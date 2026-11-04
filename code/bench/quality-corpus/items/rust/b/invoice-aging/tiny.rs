use std::collections::BTreeSet;

pub const BUCKETS: [&str; 5] = ["current", "1-30", "31-60", "61-90", "over-90"];
const BOUNDS: [i64; 4] = [1, 31, 61, 91];
const RATES: [i64; 5] = [0, 2, 5, 8, 10];
const LIMIT_CENTS: i64 = 100_000_000;
const MAX_INVOICES: usize = 1_000;
const BAD: InvoiceError = InvoiceError::InvalidInvoice;

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
    compose(rows(checked(invoices)?), totals(invoices))
}

fn compose(invoices: Vec<InvoiceRow>, totals: Totals) -> Outcome {
    Ok(Report { invoices, totals })
}

fn ordered(rows: Vec<InvoiceRow>) -> Vec<InvoiceRow> {
    BTreeSet::from_iter(rows).into_iter().collect()
}

fn rows(invoices: &[Invoice]) -> Vec<InvoiceRow> {
    ordered(invoices.iter().map(parts).collect())
}

fn parts(i: &Invoice) -> InvoiceRow {
    row_of(i.id.clone(), bucket_of(i), fee(i))
}

fn row_of(id: String, bucket: &'static str, fee: i64) -> InvoiceRow {
    InvoiceRow { id, bucket, fee }
}

fn bucket_of(i: &Invoice) -> &'static str {
    BUCKETS[at(i.days_overdue)]
}

fn fee(i: &Invoice) -> i64 {
    (i.balance_cents * RATES[at(i.days_overdue)] + 50) / 100
}

fn at(days: i64) -> usize {
    BOUNDS.iter().filter(|b| days >= **b).count()
}

fn checked(invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    guard(ok(invoices), invoices)
}

fn guard(holds: bool, invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    holds.then_some(invoices).ok_or(BAD)
}

fn ok(invoices: &[Invoice]) -> bool {
    invoices.len() <= MAX_INVOICES && named(invoices) && paid(invoices)
}

fn named(invoices: &[Invoice]) -> bool {
    invoices.iter().all(name_ok) && ids(invoices).len() == invoices.len()
}

fn name_ok(i: &Invoice) -> bool {
    !i.id.is_empty() && i.id.is_ascii()
}

fn ids(invoices: &[Invoice]) -> BTreeSet<&str> {
    invoices.iter().map(|i| i.id.as_str()).collect()
}

fn paid(invoices: &[Invoice]) -> bool {
    invoices.iter().all(|i| amount_ok(i.balance_cents))
}

fn amount_ok(cents: i64) -> bool {
    (0..=LIMIT_CENTS).contains(&cents)
}

fn totals(invoices: &[Invoice]) -> Totals {
    std::array::from_fn(|n| bucket_total(invoices, n))
}

fn bucket_total(invoices: &[Invoice], bucket: usize) -> i64 {
    invoices.iter().fold(0, |sum, i| sum + share(i, bucket))
}

fn share(i: &Invoice, bucket: usize) -> i64 {
    i.balance_cents * i64::from(at(i.days_overdue) == bucket)
}
