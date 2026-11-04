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

struct Order {
    items: Vec<NormalizedItem>,
    tier: String,
    coupon: String,
    region: String,
}

struct NormalizedItem {
    sku: String,
    qty: i64,
    price_text: String,
}

struct CheckedItem {
    sku: String,
    qty: i64,
    unit_cents: i128,
}

struct PriceBook {
    lines: Vec<Line>,
    subtotal: i128,
}

struct Adjustment {
    label: &'static str,
    cents: i128,
    active: bool,
}

/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let order = normalize_request(request);
    let merged = match validate_order(&order) {
        Ok(items) => items,
        Err(error) => return Outcome::Error(error),
    };
    assemble_quote(price_lines(merged), &order)
}

fn normalize_request(request: &Request) -> Order {
    Order {
        items: request
            .items
            .iter()
            .map(|item| NormalizedItem {
                sku: item.sku.trim().to_ascii_uppercase(),
                qty: item.qty,
                price_text: item.price.clone(),
            })
            .collect(),
        tier: request.tier.trim().to_ascii_lowercase(),
        coupon: request.coupon.trim().to_ascii_uppercase(),
        region: request.region.trim().to_ascii_uppercase(),
    }
}

fn validate_order(order: &Order) -> Result<Vec<CheckedItem>, QuoteError> {
    check_item_count(order.items.len())?;
    let merged = check_merged_items(check_item_fields(&order.items)?)?;
    let error = check_tier(&order.tier)
        .or_else(|| check_coupon(&order.coupon))
        .or_else(|| {
            (!matches!(order.region.as_str(), "EU" | "US" | "ASIA"))
                .then(|| quote_error("BAD_REGION", None))
        });
    if let Some(error) = error {
        Err(error)
    } else {
        Ok(merged)
    }
}

fn check_item_count(count: usize) -> Result<(), QuoteError> {
    let code = match count {
        0 => "EMPTY_ORDER",
        1..=50 => return Ok(()),
        _ => "TOO_MANY_ITEMS",
    };
    Err(quote_error(code, None))
}

fn quote_error(code: &str, index: Option<usize>) -> QuoteError {
    QuoteError {
        code: code.into(),
        index,
    }
}

fn check_item_fields(items: &[NormalizedItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    let mut checked = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let unit_cents = check_item(item, index)?;
        checked.push(CheckedItem {
            sku: item.sku.clone(),
            qty: item.qty,
            unit_cents,
        });
    }
    Ok(checked)
}

fn check_item(item: &NormalizedItem, index: usize) -> Result<i128, QuoteError> {
    if !(3..=12).contains(&item.sku.len())
        || !item
            .sku
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'-')
    {
        return Err(quote_error("BAD_SKU", Some(index)));
    }
    if !(1..=1000).contains(&item.qty) {
        return Err(quote_error("BAD_QTY", Some(index)));
    }
    price_in_cents(&item.price_text).ok_or_else(|| quote_error("BAD_PRICE", Some(index)))
}

fn price_in_cents(text: &str) -> Option<i128> {
    if !price_text_is_valid(text) {
        return None;
    }
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    let fractional = match fraction.len() {
        0 => 0,
        1 => fraction.parse::<i128>().ok()? * 10,
        _ => fraction.parse::<i128>().ok()?,
    };
    let cents = whole.parse::<i128>().ok()? * 100 + fractional;
    (cents > 0).then_some(cents)
}

fn price_text_is_valid(text: &str) -> bool {
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    !whole.is_empty()
        && whole.len() <= 6
        && whole.bytes().all(|byte| byte.is_ascii_digit())
        && fraction.len() <= 2
        && (!text.contains('.')
            || !fraction.is_empty() && fraction.bytes().all(|byte| byte.is_ascii_digit()))
}

fn check_merged_items(items: Vec<CheckedItem>) -> Result<Vec<CheckedItem>, QuoteError> {
    let mut merged = BTreeMap::<String, (i64, i128)>::new();
    for (index, item) in items.into_iter().enumerate() {
        merge_item(&mut merged, item, index)?;
    }
    Ok(merged
        .into_iter()
        .map(|(sku, (qty, unit_cents))| CheckedItem {
            sku,
            qty,
            unit_cents,
        })
        .collect())
}

fn merge_item(
    merged: &mut BTreeMap<String, (i64, i128)>,
    item: CheckedItem,
    index: usize,
) -> Result<(), QuoteError> {
    if let Some((qty, cents)) = merged.get_mut(&item.sku) {
        if *cents != item.unit_cents {
            return Err(quote_error("PRICE_CONFLICT", Some(index)));
        }
        *qty += item.qty;
        if *qty > 1000 {
            return Err(quote_error("BAD_QTY", Some(index)));
        }
    } else {
        merged.insert(item.sku, (item.qty, item.unit_cents));
    }
    Ok(())
}

fn check_tier(tier: &str) -> Option<QuoteError> {
    (!matches!(tier, "basic" | "silver" | "gold")).then(|| QuoteError {
        code: "BAD_TIER".into(),
        index: None,
    })
}

fn check_coupon(coupon: &str) -> Option<QuoteError> {
    (!coupon.is_empty() && coupon_value(coupon).is_none()).then(|| QuoteError {
        code: "BAD_COUPON".into(),
        index: None,
    })
}

fn coupon_value(coupon: &str) -> Option<(bool, i128)> {
    if coupon == "FREESHIP" {
        return Some((false, 0));
    }
    let percent = coupon.starts_with("PCT");
    let suffix = coupon.strip_prefix(if percent { "PCT" } else { "FIXED" })?;
    if suffix.is_empty()
        || suffix.starts_with('0')
        || !suffix.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let amount = suffix.parse::<i128>().ok()?;
    (amount <= if percent { 50 } else { 500 }).then_some((percent, amount))
}

fn price_lines(items: Vec<CheckedItem>) -> PriceBook {
    let mut lines = Vec::with_capacity(items.len());
    for item in items {
        lines.push(Line {
            sku: item.sku,
            qty: item.qty,
            unit_cents: item.unit_cents as i64,
            line_cents: (item.unit_cents * i128::from(item.qty)) as i64,
        });
    }
    let subtotal = lines.iter().map(|line| i128::from(line.line_cents)).sum();
    PriceBook { lines, subtotal }
}

fn tier_rule(subtotal: i128, tier: &str) -> Adjustment {
    let basis_points = match tier {
        "silver" => 500,
        "gold" => 1000,
        _ => 0,
    };
    let cents = (2 * subtotal * basis_points + 10_000) / 20_000;
    Adjustment {
        label: "tier",
        cents,
        active: cents > 0,
    }
}

fn coupon_rule(net: i128, coupon: &str) -> Adjustment {
    let cents = match coupon_value(coupon) {
        Some((true, percent)) => (2 * net * percent + 100) / 200,
        Some((false, amount)) => (amount * 100).min(net),
        None => 0,
    };
    Adjustment {
        label: "coupon",
        cents,
        active: cents > 0,
    }
}

fn shipping_rule(net: i128, order: &Order) -> Adjustment {
    let (base, threshold) = match order.region.as_str() {
        "EU" => (800, 10_000),
        "US" => (500, 7_500),
        _ => (1200, 15_000),
    };
    let cents = if order.coupon == "FREESHIP" || net >= threshold {
        0
    } else {
        base
    };
    Adjustment {
        label: "free-shipping",
        cents: i128::from(cents),
        active: cents == 0,
    }
}

fn tax_rule(net: i128, region: &str) -> Adjustment {
    let basis_points = match region {
        "EU" => 2000,
        "US" => 700,
        _ => 1000,
    };
    let cents = (2 * net * basis_points + 10_000) / 20_000;
    Adjustment {
        label: "tax",
        cents,
        active: cents > 0,
    }
}

fn assemble_quote(prices: PriceBook, order: &Order) -> Outcome {
    let tier = tier_rule(prices.subtotal, &order.tier);
    let after_tier = prices.subtotal - tier.cents;
    let coupon = coupon_rule(after_tier, &order.coupon);
    let net = after_tier - coupon.cents;
    let shipping = shipping_rule(net, order);
    let tax = tax_rule(net, &order.region);
    let mut applied = Vec::with_capacity(4);
    collect_applied(&mut applied, [&tier, &coupon, &shipping, &tax]);
    Outcome::Quote(adapt_quote(
        prices, tier, coupon, shipping, tax, net, applied,
    ))
}

fn collect_applied(applied: &mut Vec<String>, adjustments: [&Adjustment; 4]) {
    for adjustment in adjustments {
        if adjustment.active {
            applied.push(adjustment.label.to_string());
        }
    }
}

fn adapt_quote(
    prices: PriceBook,
    tier: Adjustment,
    coupon: Adjustment,
    shipping: Adjustment,
    tax: Adjustment,
    net: i128,
    applied: Vec<String>,
) -> Quote {
    Quote {
        lines: prices.lines,
        subtotal: prices.subtotal as i64,
        tier_discount: tier.cents as i64,
        coupon_discount: coupon.cents as i64,
        shipping: shipping.cents as i64,
        tax: tax.cents as i64,
        total: (net + shipping.cents + tax.cents) as i64,
        applied,
    }
}
