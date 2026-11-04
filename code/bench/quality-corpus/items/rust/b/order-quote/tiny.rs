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

#[derive(Debug, Clone, PartialEq, Eq, Default)]
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
type ItemResult = Result<Vec<CheckedItem>, QuoteError>;
type OptionResult = Result<(), QuoteError>;
type MergeResult = Result<(), QuoteError>;
type CheckedItems = Vec<CheckedItem>;
type PriceParts<'a> = (&'a str, &'a str);
type CouponParts<'a> = (bool, &'a str);
type CouponAmount = Option<i128>;
type QuoteInput<'a> = (&'a Adjusted, i64, i128);

/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let order = normalise(request);
    let items = validate(&order.items).and_then(|rows| merge_items(rows));
    let options = validate_options(&order);
    finish(items, options, order)
}
fn finish(items: ItemResult, options: OptionResult, order: Normalized) -> Outcome {
    items
        .and_then(|rows| options.map(|_| rows))
        .map_or_else(Outcome::Error, |rows| {
            finish_quote(price_lines(rows), &order)
        })
}
fn normalise(request: &Request) -> Normalized {
    Normalized {
        items: normalize_items(&request.items),
        tier: request.tier.trim().to_ascii_lowercase(),
        coupon: uppercase_trimmed(&request.coupon),
        region: uppercase_trimmed(&request.region),
    }
}
fn uppercase_trimmed(value: &str) -> String {
    value.trim().to_ascii_uppercase()
}
fn normalize_items(items: &[RawItem]) -> Vec<RawItem> {
    items.iter().map(|item| normalize_item(item)).collect()
}
fn normalize_item(item: &RawItem) -> RawItem {
    RawItem {
        sku: item.sku.trim().to_ascii_uppercase(),
        qty: item.qty,
        price: item.price.clone(),
    }
}
fn issue(code: &str, index: Option<usize>) -> QuoteError {
    QuoteError {
        code: code.into(),
        index,
    }
}
fn validate(items: &[RawItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    item_limit(items.len())?;
    validate_rows(items)
}
fn item_limit(count: usize) -> MergeResult {
    match count {
        0 => Err(issue("EMPTY_ORDER", None)),
        1..=50 => Ok(()),
        _ => Err(issue("TOO_MANY_ITEMS", None)),
    }
}
fn validate_rows(items: &[RawItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    items
        .iter()
        .enumerate()
        .map(|(i, item)| validate_item(item, i))
        .collect()
}
fn validate_item(item: &RawItem, index: usize) -> Result<CheckedItem, QuoteError> {
    item_error(item).map_or_else(
        || Ok(checked_item(item)),
        |code| Err(issue(code, Some(index))),
    )
}
fn item_error(item: &RawItem) -> Option<&'static str> {
    sku_error(item)
        .or_else(|| quantity_error(item))
        .or_else(|| (!valid_price(&item.price)).then_some("BAD_PRICE"))
}
fn sku_error(item: &RawItem) -> Option<&'static str> {
    (!valid_sku(&item.sku)).then_some("BAD_SKU")
}
fn quantity_error(item: &RawItem) -> Option<&'static str> {
    (!valid_quantity(item.qty)).then_some("BAD_QTY")
}
fn checked_item(item: &RawItem) -> CheckedItem {
    CheckedItem {
        sku: item.sku.clone(),
        qty: item.qty,
        cents: price_cents(&item.price),
    }
}
fn valid_sku(sku: &str) -> bool {
    (3..=12).contains(&sku.len()) && sku.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}
fn valid_quantity(quantity: i64) -> bool {
    (1..=1000).contains(&quantity)
}
fn valid_price(text: &str) -> bool {
    let (whole, fraction) = parts_of(text);
    valid_price_parts(text, whole, fraction) && price_cents_parts(whole, fraction) > 0
}
fn parts_of(text: &str) -> PriceParts<'_> {
    text.split_once('.').unwrap_or((text, ""))
}
fn valid_price_parts(text: &str, whole: &str, fraction: &str) -> bool {
    !whole.is_empty()
        && whole.len() <= 6
        && digits(whole)
        && fraction.len() <= 2
        && (!text.contains('.') || digits(fraction))
}
fn digits(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit())
}
fn price_cents(text: &str) -> i128 {
    let (whole, fraction) = parts_of(text);
    price_cents_parts(whole, fraction)
}
fn price_cents_parts(whole: &str, fraction: &str) -> i128 {
    whole_cents(whole) + fraction_cents(fraction)
}
fn whole_cents(whole: &str) -> i128 {
    whole.parse::<i128>().unwrap() * 100
}
fn fraction_cents(fraction: &str) -> i128 {
    fraction.parse::<i128>().unwrap_or(0) * if fraction.len() == 1 { 10 } else { 1 }
}
fn merge_items(items: Vec<CheckedItem>) -> Result<Vec<CheckedItem>, QuoteError> {
    let mut merged = collect_items(items)?;
    merged.sort_by(|left, right| left.sku.cmp(&right.sku));
    Ok(merged)
}
fn collect_items(items: CheckedItems) -> ItemResult {
    let mut merged = Vec::new();
    items
        .into_iter()
        .enumerate()
        .try_for_each(|(i, item)| merge_at(&mut merged, item, i))?;
    Ok(merged)
}
fn merge_at(items: &mut CheckedItems, item: CheckedItem, index: usize) -> MergeResult {
    match items.iter_mut().find(|old| old.sku == item.sku) {
        Some(old) => merge_existing(old, item, index),
        None => {
            items.push(item);
            Ok(())
        }
    }
}
fn merge_existing(old: &mut CheckedItem, item: CheckedItem, index: usize) -> MergeResult {
    if old.cents != item.cents {
        return Err(issue("PRICE_CONFLICT", Some(index)));
    }
    old.qty = merged_quantity(old.qty, item.qty, index)?;
    Ok(())
}
fn merged_quantity(old: i64, added: i64, index: usize) -> Result<i64, QuoteError> {
    let quantity = old + added;
    if quantity > 1000 {
        Err(issue("BAD_QTY", Some(index)))
    } else {
        Ok(quantity)
    }
}
fn validate_options(order: &Normalized) -> Result<(), QuoteError> {
    match option_error(order) {
        Some(code) => Err(issue(code, None)),
        None => Ok(()),
    }
}
fn option_error(order: &Normalized) -> Option<&'static str> {
    tier_issue(order)
        .or_else(|| coupon_issue(order))
        .or_else(|| region_issue(order))
}
fn tier_issue(order: &Normalized) -> Option<&'static str> {
    (!tier_valid(&order.tier)).then_some("BAD_TIER")
}
fn coupon_issue(order: &Normalized) -> Option<&'static str> {
    (!coupon_valid(&order.coupon)).then_some("BAD_COUPON")
}
fn region_issue(order: &Normalized) -> Option<&'static str> {
    (!region_valid(&order.region)).then_some("BAD_REGION")
}
fn tier_valid(tier: &str) -> bool {
    ["basic", "silver", "gold"].contains(&tier)
}
fn coupon_valid(coupon: &str) -> bool {
    coupon.is_empty() || coupon_value(coupon).is_some()
}
fn region_valid(region: &str) -> bool {
    ["EU", "US", "ASIA"].contains(&region)
}
fn coupon_value(coupon: &str) -> Option<(bool, i128)> {
    match coupon {
        "FREESHIP" => Some((true, 0)),
        _ => coupon_parts(coupon).and_then(|(percent, suffix)| {
            coupon_amount(suffix, percent).map(|amount| (percent, amount))
        }),
    }
}
fn coupon_amount(suffix: &str, percent: bool) -> CouponAmount {
    if suffix.is_empty()
        || suffix.starts_with('0')
        || !suffix.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let amount = suffix.parse().ok()?;
    (amount <= coupon_limit(percent)).then_some(amount)
}
fn coupon_limit(percent: bool) -> i128 {
    if percent {
        50
    } else {
        500
    }
}
fn coupon_parts(coupon: &str) -> Option<CouponParts<'_>> {
    match coupon.strip_prefix("PCT") {
        Some(suffix) => Some((true, suffix)),
        None => coupon.strip_prefix("FIXED").map(|suffix| (false, suffix)),
    }
}
fn price_lines(items: Vec<CheckedItem>) -> Priced {
    let lines: Vec<Line> = items.into_iter().map(|item| line_for(item)).collect();
    let amount = subtotal(&lines);
    Priced {
        lines,
        subtotal: amount,
    }
}
fn line_for(item: CheckedItem) -> Line {
    Line {
        sku: item.sku,
        qty: item.qty,
        unit_cents: item.cents as i64,
        line_cents: item.cents as i64 * item.qty,
    }
}
fn subtotal(lines: &[Line]) -> i128 {
    lines.iter().map(|line| i128::from(line.line_cents)).sum()
}
fn discounts(subtotal: i128, tier: &str, coupon: &str) -> Adjusted {
    let tier_amount = tier_discount(subtotal, tier);
    let coupon_amount = coupon_discount(subtotal - tier_amount, coupon);
    discount_record(subtotal, tier_amount, coupon_amount)
}
fn discount_record(subtotal: i128, tier_discount: i128, coupon_discount: i128) -> Adjusted {
    Adjusted {
        subtotal,
        tier_discount,
        coupon_discount,
        net: subtotal - tier_discount - coupon_discount,
    }
}
fn tier_discount(subtotal: i128, tier: &str) -> i128 {
    let basis = match tier {
        "silver" => 500,
        "gold" => 1000,
        _ => 0,
    };
    round_half_up(subtotal * basis, 10_000)
}
fn coupon_discount(net: i128, coupon: &str) -> i128 {
    coupon_value(coupon).map_or(0, |(percent, amount)| apply_coupon(net, percent, amount))
}
fn apply_coupon(net: i128, percent: bool, amount: i128) -> i128 {
    if percent {
        round_half_up(net * amount, 100)
    } else {
        (amount * 100).min(net)
    }
}
fn round_half_up(numerator: i128, denominator: i128) -> i128 {
    (2 * numerator + denominator) / (2 * denominator)
}
fn finish_quote(priced: Priced, order: &Normalized) -> Outcome {
    let adjusted = discounts(priced.subtotal, &order.tier, &order.coupon);
    quote_region(priced.lines, adjusted, &order.region, &order.coupon)
}
fn quote_region(lines: Vec<Line>, adjusted: Adjusted, region: &str, coupon: &str) -> Outcome {
    let (shipping, tax) = regional_costs(adjusted.net, region, coupon);
    Outcome::Quote(Quote {
        lines,
        ..quote_amounts(adjusted, shipping, tax)
    })
}
fn regional_costs(net: i128, region: &str, coupon: &str) -> (i64, i128) {
    let (rate, base, threshold) = region_info(region);
    (
        shipping_for(net, base, threshold, coupon),
        tax_for(net, rate),
    )
}
fn tax_for(net: i128, rate: i128) -> i128 {
    round_half_up(net * rate, 10_000)
}
fn region_info(region: &str) -> (i128, i64, i128) {
    match region {
        "EU" => (2000, 800, 10000),
        "US" => (700, 500, 7500),
        _ => (1000, 1200, 15000),
    }
}
fn shipping_for(net: i128, base: i64, threshold: i128, coupon: &str) -> i64 {
    if coupon == "FREESHIP" || net >= threshold {
        0
    } else {
        base
    }
}
fn quote_amounts(adjusted: Adjusted, shipping: i64, tax: i128) -> Quote {
    Quote {
        subtotal: adjusted.subtotal as i64,
        tier_discount: adjusted.tier_discount as i64,
        coupon_discount: adjusted.coupon_discount as i64,
        ..quote_totals((&adjusted, shipping, tax))
    }
}
fn quote_totals(input: QuoteInput<'_>) -> Quote {
    let (adjusted, shipping, tax) = input;
    Quote {
        shipping,
        tax: tax as i64,
        total: total_for(adjusted.net, shipping, tax) as i64,
        applied: applied_rules(adjusted, shipping, tax),
        ..Quote::default()
    }
}
fn total_for(net: i128, shipping: i64, tax: i128) -> i128 {
    net + i128::from(shipping) + tax
}
fn applied_rules(adjusted: &Adjusted, shipping: i64, tax: i128) -> Vec<String> {
    discount_labels(adjusted.tier_discount, adjusted.coupon_discount)
        .into_iter()
        .chain(charge_labels(shipping, tax))
        .collect()
}
fn discount_labels(tier: i128, coupon: i128) -> Vec<String> {
    [("tier", tier > 0), ("coupon", coupon > 0)]
        .into_iter()
        .filter_map(|(label, include)| include.then(|| label.to_string()))
        .collect()
}
fn charge_labels(shipping: i64, tax: i128) -> Vec<String> {
    [("free-shipping", shipping == 0), ("tax", tax > 0)]
        .into_iter()
        .filter_map(|(label, include)| include.then(|| label.to_string()))
        .collect()
}
