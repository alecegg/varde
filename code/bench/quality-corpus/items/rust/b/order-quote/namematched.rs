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
    let order = normalize_request(request);
    let items = validate_order_items(&order.items).and_then(|rows| merge_duplicate_items(rows));
    let options = validate_order_options(&order);
    finish_validation(items, options, order)
}
fn finish_validation(items: ItemResult, options: OptionResult, order: Normalized) -> Outcome {
    items
        .and_then(|rows| options.map(|_| rows))
        .map_or_else(Outcome::Error, |rows| {
            build_quote(price_items(rows), &order)
        })
}
fn normalize_request(request: &Request) -> Normalized {
    Normalized {
        items: normalize_order_items(&request.items),
        tier: request.tier.trim().to_ascii_lowercase(),
        coupon: uppercase_and_trim(&request.coupon),
        region: uppercase_and_trim(&request.region),
    }
}
fn uppercase_and_trim(value: &str) -> String {
    value.trim().to_ascii_uppercase()
}
fn normalize_order_items(items: &[RawItem]) -> Vec<RawItem> {
    items
        .iter()
        .map(|item| normalize_order_item(item))
        .collect()
}
fn normalize_order_item(item: &RawItem) -> RawItem {
    RawItem {
        sku: item.sku.trim().to_ascii_uppercase(),
        qty: item.qty,
        price: item.price.clone(),
    }
}
fn quote_error(code: &str, index: Option<usize>) -> QuoteError {
    QuoteError {
        code: code.into(),
        index,
    }
}
fn validate_order_items(items: &[RawItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    validate_item_count(items.len())?;
    validate_all_items(items)
}
fn validate_item_count(count: usize) -> MergeResult {
    match count {
        0 => Err(quote_error("EMPTY_ORDER", None)),
        1..=50 => Ok(()),
        _ => Err(quote_error("TOO_MANY_ITEMS", None)),
    }
}
fn validate_all_items(items: &[RawItem]) -> Result<Vec<CheckedItem>, QuoteError> {
    items
        .iter()
        .enumerate()
        .map(|(i, item)| validate_order_item(item, i))
        .collect()
}
fn validate_order_item(item: &RawItem, index: usize) -> Result<CheckedItem, QuoteError> {
    item_validation_error(item).map_or_else(
        || Ok(build_checked_item(item)),
        |code| Err(quote_error(code, Some(index))),
    )
}
fn item_validation_error(item: &RawItem) -> Option<&'static str> {
    invalid_sku_reason(item)
        .or_else(|| invalid_quantity_reason(item))
        .or_else(|| (!is_valid_price_text(&item.price)).then_some("BAD_PRICE"))
}
fn invalid_sku_reason(item: &RawItem) -> Option<&'static str> {
    (!is_valid_sku(&item.sku)).then_some("BAD_SKU")
}
fn invalid_quantity_reason(item: &RawItem) -> Option<&'static str> {
    (!is_valid_quantity(item.qty)).then_some("BAD_QTY")
}
fn build_checked_item(item: &RawItem) -> CheckedItem {
    CheckedItem {
        sku: item.sku.clone(),
        qty: item.qty,
        cents: price_as_cents(&item.price),
    }
}
fn is_valid_sku(sku: &str) -> bool {
    (3..=12).contains(&sku.len()) && sku.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}
fn is_valid_quantity(quantity: i64) -> bool {
    (1..=1000).contains(&quantity)
}
fn is_valid_price_text(text: &str) -> bool {
    let (whole, fraction) = decimal_parts(text);
    are_valid_price_parts(text, whole, fraction) && cents_from_price_parts(whole, fraction) > 0
}
fn decimal_parts(text: &str) -> PriceParts<'_> {
    text.split_once('.').unwrap_or((text, ""))
}
fn are_valid_price_parts(text: &str, whole: &str, fraction: &str) -> bool {
    !whole.is_empty()
        && whole.len() <= 6
        && is_ascii_digit_text(whole)
        && fraction.len() <= 2
        && (!text.contains('.') || is_ascii_digit_text(fraction))
}
fn is_ascii_digit_text(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit())
}
fn price_as_cents(text: &str) -> i128 {
    let (whole, fraction) = decimal_parts(text);
    cents_from_price_parts(whole, fraction)
}
fn cents_from_price_parts(whole: &str, fraction: &str) -> i128 {
    whole_part_cents(whole) + fraction_part_cents(fraction)
}
fn whole_part_cents(whole: &str) -> i128 {
    whole.parse::<i128>().unwrap() * 100
}
fn fraction_part_cents(fraction: &str) -> i128 {
    fraction.parse::<i128>().unwrap_or(0) * if fraction.len() == 1 { 10 } else { 1 }
}
fn merge_duplicate_items(items: Vec<CheckedItem>) -> Result<Vec<CheckedItem>, QuoteError> {
    let mut merged = collect_validated_items(items)?;
    merged.sort_by(|left, right| left.sku.cmp(&right.sku));
    Ok(merged)
}
fn collect_validated_items(items: CheckedItems) -> ItemResult {
    let mut merged = Vec::new();
    items
        .into_iter()
        .enumerate()
        .try_for_each(|(i, item)| merge_item_at(&mut merged, item, i))?;
    Ok(merged)
}
fn merge_item_at(items: &mut CheckedItems, item: CheckedItem, index: usize) -> MergeResult {
    match items.iter_mut().find(|old| old.sku == item.sku) {
        Some(old) => merge_duplicate(old, item, index),
        None => {
            items.push(item);
            Ok(())
        }
    }
}
fn merge_duplicate(old: &mut CheckedItem, item: CheckedItem, index: usize) -> MergeResult {
    if old.cents != item.cents {
        return Err(quote_error("PRICE_CONFLICT", Some(index)));
    }
    old.qty = sum_item_quantities(old.qty, item.qty, index)?;
    Ok(())
}
fn sum_item_quantities(old: i64, added: i64, index: usize) -> Result<i64, QuoteError> {
    let quantity = old + added;
    if quantity > 1000 {
        Err(quote_error("BAD_QTY", Some(index)))
    } else {
        Ok(quantity)
    }
}
fn validate_order_options(order: &Normalized) -> Result<(), QuoteError> {
    match order_option_error(order) {
        Some(code) => Err(quote_error(code, None)),
        None => Ok(()),
    }
}
fn order_option_error(order: &Normalized) -> Option<&'static str> {
    tier_validation_error(order)
        .or_else(|| coupon_validation_error(order))
        .or_else(|| region_validation_error(order))
}
fn tier_validation_error(order: &Normalized) -> Option<&'static str> {
    (!is_valid_tier(&order.tier)).then_some("BAD_TIER")
}
fn coupon_validation_error(order: &Normalized) -> Option<&'static str> {
    (!is_valid_coupon(&order.coupon)).then_some("BAD_COUPON")
}
fn region_validation_error(order: &Normalized) -> Option<&'static str> {
    (!is_valid_region(&order.region)).then_some("BAD_REGION")
}
fn is_valid_tier(tier: &str) -> bool {
    ["basic", "silver", "gold"].contains(&tier)
}
fn is_valid_coupon(coupon: &str) -> bool {
    coupon.is_empty() || parse_coupon_value(coupon).is_some()
}
fn is_valid_region(region: &str) -> bool {
    ["EU", "US", "ASIA"].contains(&region)
}
fn parse_coupon_value(coupon: &str) -> Option<(bool, i128)> {
    match coupon {
        "FREESHIP" => Some((true, 0)),
        _ => split_coupon_parts(coupon).and_then(|(percent, suffix)| {
            coupon_amount_from_suffix(suffix, percent).map(|amount| (percent, amount))
        }),
    }
}
fn coupon_amount_from_suffix(suffix: &str, percent: bool) -> CouponAmount {
    if suffix.is_empty()
        || suffix.starts_with('0')
        || !suffix.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let amount = suffix.parse().ok()?;
    (amount <= maximum_coupon_amount(percent)).then_some(amount)
}
fn maximum_coupon_amount(percent: bool) -> i128 {
    if percent {
        50
    } else {
        500
    }
}
fn split_coupon_parts(coupon: &str) -> Option<CouponParts<'_>> {
    match coupon.strip_prefix("PCT") {
        Some(suffix) => Some((true, suffix)),
        None => coupon.strip_prefix("FIXED").map(|suffix| (false, suffix)),
    }
}
fn price_items(items: Vec<CheckedItem>) -> Priced {
    let lines: Vec<Line> = items.into_iter().map(|item| price_line(item)).collect();
    let amount = sum_line_totals(&lines);
    Priced {
        lines,
        subtotal: amount,
    }
}
fn price_line(item: CheckedItem) -> Line {
    Line {
        sku: item.sku,
        qty: item.qty,
        unit_cents: item.cents as i64,
        line_cents: item.cents as i64 * item.qty,
    }
}
fn sum_line_totals(lines: &[Line]) -> i128 {
    lines.iter().map(|line| i128::from(line.line_cents)).sum()
}
fn calculate_discounts(subtotal: i128, tier: &str, coupon: &str) -> Adjusted {
    let tier_amount = calculate_tier_discount(subtotal, tier);
    let coupon_amount = calculate_coupon_discount(subtotal - tier_amount, coupon);
    make_adjusted_amounts(subtotal, tier_amount, coupon_amount)
}
fn make_adjusted_amounts(subtotal: i128, tier_discount: i128, coupon_discount: i128) -> Adjusted {
    Adjusted {
        subtotal,
        tier_discount,
        coupon_discount,
        net: subtotal - tier_discount - coupon_discount,
    }
}
fn calculate_tier_discount(subtotal: i128, tier: &str) -> i128 {
    let basis = match tier {
        "silver" => 500,
        "gold" => 1000,
        _ => 0,
    };
    round_division_half_up(subtotal * basis, 10_000)
}
fn calculate_coupon_discount(net: i128, coupon: &str) -> i128 {
    parse_coupon_value(coupon).map_or(0, |(percent, amount)| {
        apply_coupon_discount(net, percent, amount)
    })
}
fn apply_coupon_discount(net: i128, percent: bool, amount: i128) -> i128 {
    if percent {
        round_division_half_up(net * amount, 100)
    } else {
        (amount * 100).min(net)
    }
}
fn round_division_half_up(numerator: i128, denominator: i128) -> i128 {
    (2 * numerator + denominator) / (2 * denominator)
}
fn build_quote(priced: Priced, order: &Normalized) -> Outcome {
    let adjusted = calculate_discounts(priced.subtotal, &order.tier, &order.coupon);
    regional_quote(priced.lines, adjusted, &order.region, &order.coupon)
}
fn regional_quote(lines: Vec<Line>, adjusted: Adjusted, region: &str, coupon: &str) -> Outcome {
    let (shipping, tax) = calculate_regional_costs(adjusted.net, region, coupon);
    Outcome::Quote(Quote {
        lines,
        ..set_quote_amounts(adjusted, shipping, tax)
    })
}
fn calculate_regional_costs(net: i128, region: &str, coupon: &str) -> (i64, i128) {
    let (rate, base, threshold) = regional_tax_and_shipping(region);
    (
        calculate_shipping(net, base, threshold, coupon),
        calculate_tax(net, rate),
    )
}
fn calculate_tax(net: i128, rate: i128) -> i128 {
    round_division_half_up(net * rate, 10_000)
}
fn regional_tax_and_shipping(region: &str) -> (i128, i64, i128) {
    match region {
        "EU" => (2000, 800, 10000),
        "US" => (700, 500, 7500),
        _ => (1000, 1200, 15000),
    }
}
fn calculate_shipping(net: i128, base: i64, threshold: i128, coupon: &str) -> i64 {
    if coupon == "FREESHIP" || net >= threshold {
        0
    } else {
        base
    }
}
fn set_quote_amounts(adjusted: Adjusted, shipping: i64, tax: i128) -> Quote {
    Quote {
        subtotal: adjusted.subtotal as i64,
        tier_discount: adjusted.tier_discount as i64,
        coupon_discount: adjusted.coupon_discount as i64,
        ..calculate_quote_totals((&adjusted, shipping, tax))
    }
}
fn calculate_quote_totals(input: QuoteInput<'_>) -> Quote {
    let (adjusted, shipping, tax) = input;
    Quote {
        shipping,
        tax: tax as i64,
        total: calculate_total(adjusted.net, shipping, tax) as i64,
        applied: list_applied_rules(adjusted, shipping, tax),
        ..Quote::default()
    }
}
fn calculate_total(net: i128, shipping: i64, tax: i128) -> i128 {
    net + i128::from(shipping) + tax
}
fn list_applied_rules(adjusted: &Adjusted, shipping: i64, tax: i128) -> Vec<String> {
    list_discount_labels(adjusted.tier_discount, adjusted.coupon_discount)
        .into_iter()
        .chain(list_charge_labels(shipping, tax))
        .collect()
}
fn list_discount_labels(tier: i128, coupon: i128) -> Vec<String> {
    [("tier", tier > 0), ("coupon", coupon > 0)]
        .into_iter()
        .filter_map(|(label, include)| include.then(|| label.to_string()))
        .collect()
}
fn list_charge_labels(shipping: i64, tax: i128) -> Vec<String> {
    [("free-shipping", shipping == 0), ("tax", tax > 0)]
        .into_iter()
        .filter_map(|(label, include)| include.then(|| label.to_string()))
        .collect()
}
