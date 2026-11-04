use std::collections::BTreeSet;

pub const BUCKETS: [&str; 5] = ["current", "1-30", "31-60", "61-90", "over-90"];
const BOUNDS: [i64; 4] = [1, 31, 61, 91];
const RATES: [i64; 5] = [0, 2, 5, 8, 10];
const LIMIT_CENTS: i64 = 100_000_000;
const MAX_INVOICES: usize = 1_000;
const REJECTED: InvoiceError = InvoiceError::InvalidInvoice;

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
    report(sorted(accepted(invoices)?), totals_of(invoices))
}

fn report(invoices: Vec<InvoiceRow>, totals: Totals) -> Outcome {
    Ok(Report { invoices, totals })
}

fn sorted(invoices: &[Invoice]) -> Vec<InvoiceRow> {
    in_order(invoices.iter().map(described).collect())
}

fn in_order(rows: Vec<InvoiceRow>) -> Vec<InvoiceRow> {
    BTreeSet::from_iter(rows).into_iter().collect()
}

fn described(i: &Invoice) -> InvoiceRow {
    row_from(i.id.clone(), bucket_label(i), invoice_fee(i))
}

fn row_from(id: String, bucket: &'static str, fee: i64) -> InvoiceRow {
    InvoiceRow { id, bucket, fee }
}

fn bucket_label(i: &Invoice) -> &'static str {
    BUCKETS[bucket_index(i.days_overdue)]
}

fn invoice_fee(i: &Invoice) -> i64 {
    (i.balance_cents * RATES[bucket_index(i.days_overdue)] + 50) / 100
}

fn bucket_index(days: i64) -> usize {
    BOUNDS.iter().filter(|b| days >= **b).count()
}

fn accepted(invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    decided(holds(invoices), invoices)
}

fn decided(holds: bool, invoices: &[Invoice]) -> Result<&[Invoice], InvoiceError> {
    holds.then_some(invoices).ok_or(REJECTED)
}

fn holds(invoices: &[Invoice]) -> bool {
    invoices.len() <= MAX_INVOICES && named_ok(invoices) && amounts_ok(invoices)
}

fn named_ok(invoices: &[Invoice]) -> bool {
    invoices.iter().all(identifier_valid) && identifiers(invoices).len() == invoices.len()
}

fn identifier_valid(i: &Invoice) -> bool {
    !i.id.is_empty() && i.id.is_ascii()
}

fn identifiers(invoices: &[Invoice]) -> BTreeSet<&str> {
    invoices.iter().map(|i| i.id.as_str()).collect()
}

fn amounts_ok(invoices: &[Invoice]) -> bool {
    invoices.iter().all(|i| balance_valid(i.balance_cents))
}

fn balance_valid(cents: i64) -> bool {
    (0..=LIMIT_CENTS).contains(&cents)
}

fn totals_of(invoices: &[Invoice]) -> Totals {
    std::array::from_fn(|n| bucket_balance(invoices, n))
}

fn bucket_balance(invoices: &[Invoice], bucket: usize) -> i64 {
    invoices.iter().fold(0, |sum, i| sum + share_of(i, bucket))
}

fn share_of(i: &Invoice, bucket: usize) -> i64 {
    i.balance_cents * i64::from(bucket_index(i.days_overdue) == bucket)
}
