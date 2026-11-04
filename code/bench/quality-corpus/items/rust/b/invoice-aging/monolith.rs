pub const BUCKETS: [&str; 5] = ["current", "1-30", "31-60", "61-90", "over-90"];
const RATES: [i64; 5] = [0, 2, 5, 8, 10];
const PERCENT_SCALE: i64 = 100;
const HALF_CENT: i64 = 50;
const LIMIT_CENTS: i64 = 100_000_000;
const MAX_INVOICES: usize = 1_000;
const LOWEST_CENTS: i64 = 0;
const EMPTY_TOTALS: [i64; 5] = [0; 5];

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
    let mut valid = true;
    if invoices.len() > MAX_INVOICES {
        valid = false;
    }
    for invoice in invoices {
        let identifier_is_present = !invoice.id.is_empty();
        if !identifier_is_present {
            valid = false;
        }
    }
    for invoice in invoices {
        let identifier_is_ascii = invoice.id.is_ascii();
        if !identifier_is_ascii {
            valid = false;
        }
    }
    for (index, invoice) in invoices.iter().enumerate() {
        let identifier = invoice.id.as_str();
        let duplicate_scan_start = index + 1;
        for other in &invoices[duplicate_scan_start..] {
            let same_identifier = other.id == identifier;
            if same_identifier {
                valid = false;
            }
        }
    }
    for invoice in invoices {
        let balance_is_not_negative = invoice.balance_cents >= LOWEST_CENTS;
        if !balance_is_not_negative {
            valid = false;
        }
    }
    for invoice in invoices {
        let balance_is_within_limit = invoice.balance_cents <= LIMIT_CENTS;
        if !balance_is_within_limit {
            valid = false;
        }
    }
    if !valid {
        return Err(InvoiceError::InvalidInvoice);
    }
    let mut buckets: Vec<usize> = Vec::with_capacity(invoices.len());
    for invoice in invoices {
        let mut bucket = 0;
        if invoice.days_overdue > 0 {
            bucket = 1;
        }
        if invoice.days_overdue > 30 {
            bucket = 2;
        }
        if invoice.days_overdue > 60 {
            bucket = 3;
        }
        if invoice.days_overdue > 90 {
            bucket = 4;
        }
        buckets.push(bucket);
    }
    let mut totals: Totals = EMPTY_TOTALS;
    for (index, slot_total) in totals.iter_mut().enumerate() {
        let mut bucket_total = 0;
        for (invoice, &bucket) in invoices.iter().zip(&buckets) {
            let belongs_to_bucket = bucket == index;
            if !belongs_to_bucket {
                continue;
            }
            bucket_total += invoice.balance_cents;
        }
        *slot_total = bucket_total;
    }
    let mut rows: Vec<InvoiceRow> = Vec::with_capacity(invoices.len());
    for invoice in invoices {
        let mut bucket = 0;
        if invoice.days_overdue > 0 {
            bucket = 1;
        }
        if invoice.days_overdue > 30 {
            bucket = 2;
        }
        if invoice.days_overdue > 60 {
            bucket = 3;
        }
        if invoice.days_overdue > 90 {
            bucket = 4;
        }
        let rate_percent = RATES[bucket];
        let fee_before_rounding = invoice.balance_cents * rate_percent;
        let fee = (fee_before_rounding + HALF_CENT) / PERCENT_SCALE;
        let identifier = invoice.id.clone();
        let bucket_name = BUCKETS[bucket];
        rows.push(InvoiceRow {
            id: identifier,
            bucket: bucket_name,
            fee,
        });
    }
    let row_count = rows.len();
    let mut sorted_rows: Vec<InvoiceRow> = Vec::with_capacity(row_count);
    for row in rows {
        let mut position = sorted_rows.len();
        for (index, existing) in sorted_rows.iter().enumerate() {
            let compared_identifier = existing.id.as_str();
            let goes_before = row.id.as_str() < compared_identifier;
            if goes_before {
                position = index;
                break;
            }
        }
        sorted_rows.insert(position, row);
    }
    let report = Report {
        invoices: sorted_rows,
        totals,
    };
    Ok(report)
}
