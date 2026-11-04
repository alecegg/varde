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
    if invoices.len() > MAX_INVOICES {
        return Err(InvoiceError::InvalidInvoice);
    }
    let mut seen_ids: BTreeSet<&str> = BTreeSet::new();
    for invoice in invoices {
        let has_identifier = !invoice.id.is_empty();
        let identifier_is_ascii = invoice.id.is_ascii();
        let amount_is_inside_range = (0..=LIMIT_CENTS).contains(&invoice.balance_cents);
        let is_acceptable = has_identifier && identifier_is_ascii && amount_is_inside_range;
        if !is_acceptable {
            return Err(InvoiceError::InvalidInvoice);
        }
        let is_new_identifier = seen_ids.insert(invoice.id.as_str());
        if !is_new_identifier {
            return Err(InvoiceError::InvalidInvoice);
        }
    }
    let mut buckets: Vec<usize> = Vec::with_capacity(invoices.len());
    for invoice in invoices {
        let bucket = BOUNDS
            .iter()
            .filter(|bound| invoice.days_overdue >= **bound)
            .count();
        buckets.push(bucket);
    }
    let mut totals = [0; 5];
    for (index, total) in totals.iter_mut().enumerate() {
        let mut running = 0;
        for (invoice, &bucket) in invoices.iter().zip(&buckets) {
            let belongs_to_bucket = bucket == index;
            if belongs_to_bucket {
                running += invoice.balance_cents;
            }
        }
        *total = running;
    }
    let mut rows: Vec<InvoiceRow> = Vec::with_capacity(invoices.len());
    for (invoice, &bucket) in invoices.iter().zip(&buckets) {
        let rate_percent = RATES[bucket];
        let unrounded_fee = invoice.balance_cents * rate_percent;
        let rounded_fee = (unrounded_fee + 50) / 100;
        let bucket_name = BUCKETS[bucket];
        let row = InvoiceRow {
            id: invoice.id.clone(),
            bucket: bucket_name,
            fee: rounded_fee,
        };
        rows.push(row);
    }
    rows.sort();
    let report = Report {
        invoices: rows,
        totals,
    };
    Ok(report)
}
