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

struct Normalized {
    items: Vec<RawItem>,
    tier: String,
    coupon: String,
    region: String,
}

struct CheckedItem {
    sku: String,
    qty: i64,
    cents: i128,
}

struct Priced {
    lines: Vec<Line>,
    subtotal: i128,
}

struct Adjusted {
    subtotal: i128,
    tier_discount: i128,
    coupon_discount: i128,
    net: i128,
}

macro_rules! quote_error {
    ($code:expr, $index:expr) => {
        QuoteError {
            code: $code.to_string(),
            index: $index,
        }
    };
}

macro_rules! invalid_item {
    ($code:expr, $index:expr) => {
        return Err(quote_error!($code, Some($index)))
    };
}

/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let request = normalise(request);
    let items = match validate(&request.items) {
        Ok(items) => items,
        Err(error) => return Outcome::Error(error),
    };
    let items = match prepare_items(items, &request) {
        Ok(items) => items,
        Err(error) => return Outcome::Error(error),
    };
    let priced = price_lines(items);
    let adjusted = adjust(&priced, &request.tier, &request.coupon);
    finish(priced.lines, adjusted, &request)
}

fn normalise(request: &Request) -> Normalized {
    Normalized {
        items: request
            .items
            .iter()
            .map(|item| RawItem {
                sku: item.sku.trim().to_ascii_uppercase(),
                qty: item.qty,
                price: item.price.clone(),
            })
            .collect(),
        tier: request.tier.trim().to_ascii_lowercase(),
        coupon: request.coupon.trim().to_ascii_uppercase(),
        region: request.region.trim().to_ascii_uppercase(),
    }
}

fn validate(items: &[RawItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    if items.is_empty() {
        return Err(quote_error!("EMPTY_ORDER", None));
    }
    if items.len() > 50 {
        return Err(quote_error!("TOO_MANY_ITEMS", None));
    }
    items
        .iter()
        .enumerate()
        .map(|(index, item)| validate_item(item, index))
        .collect()
}

fn validate_item(item: &RawItem, index: usize) -> Result<CheckedItem, QuoteError> {
    if !valid_sku(&item.sku) {
        invalid_item!("BAD_SKU", index);
    }
    if !(1..=1000).contains(&item.qty) {
        invalid_item!("BAD_QTY", index);
    }
    if !valid_price_text(&item.price) {
        invalid_item!("BAD_PRICE", index);
    }
    let cents = price_cents(&item.price);
    if cents == 0 {
        invalid_item!("BAD_PRICE", index);
    }
    Ok(CheckedItem {
        sku: item.sku.clone(),
        qty: item.qty,
        cents,
    })
}

fn valid_sku(sku: &str) -> bool {
    (3..=12).contains(&sku.len())
        && sku
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'-')
}

fn valid_price_text(text: &str) -> bool {
    let mut parts = text.split('.');
    let Some(whole) = parts.next() else {
        return false;
    };
    let fraction = parts.next().unwrap_or("");
    !(parts.next().is_some()
        || whole.is_empty()
        || whole.len() > 6
        || (text.contains('.') && fraction.is_empty())
        || fraction.len() > 2
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit()))
}

fn price_cents(text: &str) -> i128 {
    let mut parts = text.split('.');
    let whole = parts.next().unwrap().parse::<i128>().unwrap();
    let fraction = parts.next().unwrap_or("");
    let fraction_cents = match fraction.len() {
        0 => 0,
        1 => fraction.parse::<i128>().unwrap() * 10,
        _ => fraction.parse::<i128>().unwrap(),
    };
    whole * 100 + fraction_cents
}

fn prepare_items(
    items: Vec<CheckedItem>,
    request: &Normalized,
) -> Result<Vec<CheckedItem>, QuoteError> {
    let items = merge_items(items)?;
    validate_options(request)?;
    Ok(items)
}

fn merge_items(items: Vec<CheckedItem>) -> Result<Vec<CheckedItem>, QuoteError> {
    let mut merged = BTreeMap::<String, (i64, i128)>::new();
    for (index, item) in items.into_iter().enumerate() {
        merge_one(&mut merged, item, index)?;
    }
    Ok(merged
        .into_iter()
        .map(|(sku, (qty, cents))| CheckedItem { sku, qty, cents })
        .collect())
}

fn merge_one(
    merged: &mut BTreeMap<String, (i64, i128)>,
    item: CheckedItem,
    index: usize,
) -> Result<(), QuoteError> {
    if let Some((qty, cents)) = merged.get_mut(&item.sku) {
        if *cents != item.cents {
            return Err(quote_error!("PRICE_CONFLICT", Some(index)));
        }
        *qty += item.qty;
        if *qty > 1000 {
            return Err(quote_error!("BAD_QTY", Some(index)));
        }
    } else {
        merged.insert(item.sku, (item.qty, item.cents));
    }
    Ok(())
}

fn validate_options(request: &Normalized) -> Result<(), QuoteError> {
    if !["basic", "silver", "gold"].contains(&request.tier.as_str()) {
        return Err(quote_error!("BAD_TIER", None));
    }
    if !request.coupon.is_empty() && coupon_value(&request.coupon).is_none() {
        return Err(quote_error!("BAD_COUPON", None));
    }
    if !["EU", "US", "ASIA"].contains(&request.region.as_str()) {
        return Err(quote_error!("BAD_REGION", None));
    }
    Ok(())
}

fn coupon_value(coupon: &str) -> Option<(bool, i128)> {
    if coupon == "FREESHIP" {
        return Some((true, 0));
    }
    let percent = coupon.starts_with("PCT");
    let suffix = coupon.strip_prefix(if percent { "PCT" } else { "FIXED" })?;
    let maximum = if percent { 50 } else { 500 };
    if suffix.starts_with('0') || !suffix.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    let amount = suffix.parse::<i128>().ok()?;
    (amount <= maximum).then_some((percent, amount))
}

fn price_lines(items: Vec<CheckedItem>) -> Priced {
    let lines: Vec<Line> = items
        .into_iter()
        .map(|item| Line {
            sku: item.sku,
            qty: item.qty,
            unit_cents: item.cents as i64,
            line_cents: (item.cents * i128::from(item.qty)) as i64,
        })
        .collect();
    let subtotal = lines.iter().map(|line| i128::from(line.line_cents)).sum();
    Priced { lines, subtotal }
}

fn adjust(priced: &Priced, tier: &str, coupon: &str) -> Adjusted {
    let rate = match tier {
        "basic" => 0,
        "silver" => 500,
        "gold" => 1000,
        _ => unreachable!("validated tier"),
    };
    let tier_discount = round_half_up(priced.subtotal * rate, 10_000);
    let after_tier = priced.subtotal - tier_discount;
    let coupon_discount = coupon_discount(after_tier, coupon);
    Adjusted {
        subtotal: priced.subtotal,
        tier_discount,
        coupon_discount,
        net: after_tier - coupon_discount,
    }
}

fn coupon_discount(net: i128, coupon: &str) -> i128 {
    match coupon_value(coupon) {
        Some((true, amount)) => round_half_up(net * amount, 100),
        Some((false, amount)) => (amount * 100).min(net),
        None => 0,
    }
}

fn finish(lines: Vec<Line>, adjusted: Adjusted, request: &Normalized) -> Outcome {
    let (tax_rate, base_shipping, threshold) = region_info(&request.region);
    let shipping = if request.coupon == "FREESHIP" || adjusted.net >= threshold {
        0
    } else {
        base_shipping
    };
    let tax = round_half_up(adjusted.net * tax_rate, 10_000);
    quote_result(lines, adjusted, shipping, tax)
}

fn quote_result(lines: Vec<Line>, adjusted: Adjusted, shipping: i64, tax: i128) -> Outcome {
    let total = adjusted.net + i128::from(shipping) + tax;
    Outcome::Quote(Quote {
        lines,
        subtotal: adjusted.subtotal as i64,
        tier_discount: adjusted.tier_discount as i64,
        coupon_discount: adjusted.coupon_discount as i64,
        shipping,
        tax: tax as i64,
        total: total as i64,
        applied: applied_rules(
            adjusted.tier_discount,
            adjusted.coupon_discount,
            shipping,
            tax,
        ),
    })
}

fn region_info(region: &str) -> (i128, i64, i128) {
    match region {
        "EU" => (2000, 800, 10_000),
        "US" => (700, 500, 7_500),
        "ASIA" => (1000, 1200, 15_000),
        _ => unreachable!("validated region"),
    }
}

fn applied_rules(tier: i128, coupon: i128, shipping: i64, tax: i128) -> Vec<String> {
    let mut applied = Vec::new();
    if tier > 0 {
        applied.push("tier".to_string());
    }
    if coupon > 0 {
        applied.push("coupon".to_string());
    }
    if shipping == 0 {
        applied.push("free-shipping".to_string());
    }
    if tax > 0 {
        applied.push("tax".to_string());
    }
    applied
}

fn round_half_up(numerator: i128, denominator: i128) -> i128 {
    let whole = numerator / denominator;
    let remainder = numerator % denominator;
    whole + i128::from(remainder * 2 >= denominator)
}
