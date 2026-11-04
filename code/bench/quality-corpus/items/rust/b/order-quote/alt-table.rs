use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub items: Vec<RawItem>,
    pub tier: String,
    pub coupon: String,
    pub region: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawItem {
    pub sku: String,
    pub qty: i64,
    pub price: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Line {
    pub sku: String,
    pub qty: i64,
    pub unit_cents: i64,
    pub line_cents: i64,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Quote {
    pub lines: Vec<Line>,
    pub subtotal: i64,
    pub tier_discount: i64,
    pub coupon_discount: i64,
    pub shipping: i64,
    pub tax: i64,
    pub total: i64,
    pub applied: Vec<String>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuoteError {
    pub code: String,
    pub index: Option<usize>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Quote(Quote),
    Error(QuoteError),
}

const TIER_BP: [(&str, i64); 3] = [("basic", 0), ("silver", 500), ("gold", 1000)];
const REGIONS: [(&str, i64, i64, i64); 3] = [
    ("EU", 800, 10000, 2000),
    ("US", 500, 7500, 700),
    ("ASIA", 1200, 15000, 1000),
];
const COUPON_KINDS: [(&str, bool, i64); 3] = [
    ("PCT", true, 50),
    ("FIXED", false, 500),
    ("FREESHIP", false, 0),
];
struct Pricing {
    lines: Vec<Line>,
    subtotal: i128,
    tier: i128,
    coupon: i128,
    net: i128,
}
const CHECKS: [(usize, &str); 2] = [(0, "BAD_SKU"), (1, "BAD_QTY")];

fn bad_sku(item: &RawItem) -> bool {
    !(3..=12).contains(&item.sku.len())
        || !item
            .sku
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'-')
}
fn bad_qty(item: &RawItem) -> bool {
    let quantity = item.qty;
    !(1..=1000).contains(&quantity)
}
macro_rules! error {
    ($code:expr, $index:expr) => {
        QuoteError {
            code: $code.into(),
            index: $index,
        }
    };
}
fn valid_price(text: &str) -> Option<(&str, &str)> {
    let (whole, frac) = text.split_once('.').unwrap_or((text, ""));
    if whole.is_empty()
        || whole.len() > 6
        || frac.len() > 2
        || text.matches('.').count() > 1
        || (text.contains('.') && frac.is_empty())
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || !frac.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    Some((whole, frac))
}
fn decimal_cents(whole: &str, frac: &str) -> Option<i128> {
    let tail = match frac.len() {
        0 => 0,
        1 => frac.parse::<i128>().ok()? * 10,
        _ => frac.parse::<i128>().ok()?,
    };
    let value = whole.parse::<i128>().ok()? * 100 + tail;
    (value > 0).then_some(value)
}
fn coupon_value(value: &str) -> Option<(bool, i64)> {
    for (prefix, percent, limit) in COUPON_KINDS {
        if prefix == "FREESHIP" && value == prefix {
            return Some((percent, limit));
        }
        if let Some(number) = value.strip_prefix(prefix) {
            if number.is_empty()
                || number.starts_with('0')
                || !number.bytes().all(|b| b.is_ascii_digit())
            {
                return None;
            }
            let amount = number.parse::<i64>().ok()?;
            return (amount <= limit).then_some((percent, amount));
        }
    }
    None
}
fn normalize(request: &Request) -> (Vec<RawItem>, String, String, String) {
    (
        request
            .items
            .iter()
            .map(|item| RawItem {
                sku: item.sku.trim().to_ascii_uppercase(),
                qty: item.qty,
                price: item.price.clone(),
            })
            .collect(),
        request.tier.trim().to_ascii_lowercase(),
        request.coupon.trim().to_ascii_uppercase(),
        request.region.trim().to_ascii_uppercase(),
    )
}
fn validate_rows(rows: &[RawItem]) -> Result<Vec<i128>, QuoteError> {
    let mut prices = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        prices.push(validate_row(row, index)?);
    }
    Ok(prices)
}
fn validate_row(row: &RawItem, index: usize) -> Result<i128, QuoteError> {
    let invalid = [bad_sku(row), bad_qty(row)];
    for (rule, code) in CHECKS {
        if invalid[rule] {
            return Err(error!(code, Some(index)));
        }
    }
    let (whole, fraction) =
        valid_price(&row.price).ok_or_else(|| error!("BAD_PRICE", Some(index)))?;
    decimal_cents(whole, fraction).ok_or_else(|| error!("BAD_PRICE", Some(index)))
}
fn merge_rows(
    rows: &[RawItem],
    prices: Vec<i128>,
) -> Result<BTreeMap<String, (i64, i128)>, QuoteError> {
    let mut merged = BTreeMap::<String, (i64, i128)>::new();
    for (index, (row, price)) in rows.iter().zip(prices).enumerate() {
        merge_one(&mut merged, row, price, index)?;
    }
    Ok(merged)
}
fn merge_one(
    merged: &mut BTreeMap<String, (i64, i128)>,
    row: &RawItem,
    price: i128,
    index: usize,
) -> Result<(), QuoteError> {
    if let Some((qty, prior)) = merged.get_mut(&row.sku) {
        if *prior != price {
            return Err(error!("PRICE_CONFLICT", Some(index)));
        }
        *qty += row.qty;
        if *qty > 1000 {
            return Err(error!("BAD_QTY", Some(index)));
        }
    } else {
        merged.insert(row.sku.clone(), (row.qty, price));
    }
    Ok(())
}
fn tier_rate(tier: &str) -> Result<i64, QuoteError> {
    TIER_BP
        .iter()
        .find(|row| row.0 == tier)
        .map(|row| row.1)
        .ok_or_else(|| error!("BAD_TIER", None))
}
fn validate_options(
    tier: &str,
    coupon: &str,
    region: &str,
) -> Result<(i64, i64, i64, i64), QuoteError> {
    let tier_bp = tier_rate(tier)?;
    if !coupon.is_empty() && coupon_value(coupon).is_none() {
        return Err(error!("BAD_COUPON", None));
    }
    let (_, base, threshold, tax_bp) = REGIONS
        .iter()
        .find(|entry| entry.0 == region)
        .copied()
        .ok_or_else(|| error!("BAD_REGION", None))?;
    Ok((tier_bp, base, threshold, tax_bp))
}
fn price_grouped(
    grouped: BTreeMap<String, (i64, i128)>,
    tier_bp: i64,
    coupon: &str,
    base: i64,
    threshold: i64,
    tax_bp: i64,
) -> Quote {
    let (lines, subtotal) = make_lines(grouped);
    let (tier, coupon_cut, net) = apply_discounts(subtotal, tier_bp, coupon);
    finish_quote(
        Pricing {
            lines,
            subtotal,
            tier,
            coupon: coupon_cut,
            net,
        },
        coupon,
        base,
        threshold,
        tax_bp,
    )
}
fn make_lines(grouped: BTreeMap<String, (i64, i128)>) -> (Vec<Line>, i128) {
    let lines: Vec<Line> = grouped
        .into_iter()
        .map(|(sku, (qty, price))| Line {
            sku,
            qty,
            unit_cents: price as i64,
            line_cents: (price * i128::from(qty)) as i64,
        })
        .collect();
    let subtotal: i128 = lines.iter().map(|line| i128::from(line.line_cents)).sum();
    (lines, subtotal)
}
fn apply_discounts(subtotal: i128, tier_bp: i64, coupon: &str) -> (i128, i128, i128) {
    let tier = (subtotal * i128::from(tier_bp) + 5000) / 10000;
    let after_tier = subtotal - tier;
    let coupon_cut = match coupon_value(coupon) {
        Some((true, amount)) => (after_tier * i128::from(amount) + 50) / 100,
        Some((false, amount)) => (i128::from(amount) * 100).min(after_tier),
        None => 0,
    };
    let net = after_tier - coupon_cut;
    (tier, coupon_cut, net)
}
fn finish_quote(priced: Pricing, coupon: &str, base: i64, threshold: i64, tax_bp: i64) -> Quote {
    let shipping = if coupon == "FREESHIP" || priced.net >= i128::from(threshold) {
        0
    } else {
        base
    };
    let tax = (priced.net * i128::from(tax_bp) + 5000) / 10000;
    let applied = applied_labels(priced.tier, priced.coupon, shipping, tax);
    quote_fields(priced, shipping, tax, applied)
}
fn applied_labels(tier: i128, coupon: i128, shipping: i64, tax: i128) -> Vec<String> {
    let mut applied = Vec::new();
    if tier > 0 {
        applied.push("tier".into());
    }
    if coupon > 0 {
        applied.push("coupon".into());
    }
    if shipping == 0 {
        applied.push("free-shipping".into());
    }
    if tax > 0 {
        applied.push("tax".into());
    }
    applied
}
fn quote_fields(priced: Pricing, shipping: i64, tax: i128, applied: Vec<String>) -> Quote {
    Quote {
        lines: priced.lines,
        subtotal: priced.subtotal as i64,
        tier_discount: priced.tier as i64,
        coupon_discount: priced.coupon as i64,
        shipping,
        tax: tax as i64,
        total: (priced.net + i128::from(shipping) + tax) as i64,
        applied,
    }
}
fn check_count(rows: &[RawItem]) -> Result<(), QuoteError> {
    if rows.is_empty() {
        return Err(error!("EMPTY_ORDER", None));
    }
    if rows.len() > 50 {
        return Err(error!("TOO_MANY_ITEMS", None));
    }
    Ok(())
}

/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let result = (|| -> Result<Quote, QuoteError> {
        let (rows, tier, coupon, region) = normalize(request);
        check_count(&rows)?;
        let prices = validate_rows(&rows)?;
        let grouped = merge_rows(&rows, prices)?;
        let (tier_bp, base, threshold, tax_bp) = validate_options(&tier, &coupon, &region)?;
        Ok(price_grouped(
            grouped, tier_bp, &coupon, base, threshold, tax_bp,
        ))
    })();
    result.map(Outcome::Quote).unwrap_or_else(Outcome::Error)
}
