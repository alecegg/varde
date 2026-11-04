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

struct Items {
    rows: Vec<RawItem>,
}
struct Validated {
    rows: Vec<(RawItem, i128)>,
}
struct Merged {
    rows: Vec<(String, i64, i128)>,
}
struct Region {
    tax_rate: i64,
    base: i64,
    threshold: i64,
}
struct Options {
    tier: String,
    coupon: String,
    region: Region,
}
struct Pricing {
    lines: Vec<Line>,
    subtotal: i128,
    tier_discount: i128,
    coupon_discount: i128,
    net: i128,
    shipping: i64,
    tax: i128,
}
const COUPON_KINDS: [(&str, bool, i128); 2] = [("PCT", true, 50), ("FIXED", false, 500)];

macro_rules! error {
    ($code:expr, $index:expr) => {
        QuoteError {
            code: $code.into(),
            index: $index,
        }
    };
}
fn normalise(request: &Request) -> Items {
    Items {
        rows: request
            .items
            .iter()
            .map(|item| RawItem {
                sku: item.sku.trim().to_ascii_uppercase(),
                qty: item.qty,
                price: item.price.clone(),
            })
            .collect(),
    }
}
fn valid_price_parts(text: &str, whole: &str, frac: &str, extra: Option<&str>) -> bool {
    extra.is_none()
        && !whole.is_empty()
        && whole.len() <= 6
        && frac.len() <= 2
        && !(text.contains('.') && frac.is_empty())
        && whole.bytes().all(|b| b.is_ascii_digit())
        && frac.bytes().all(|b| b.is_ascii_digit())
        && text
            .bytes()
            .any(|byte| byte.is_ascii_digit() && byte != b'0')
}
fn cents_parts(whole: &str, frac: &str) -> Option<i128> {
    let base = whole.parse::<i128>().ok()? * 100;
    let extra = match frac.len() {
        0 => 0,
        1 => frac.parse::<i128>().ok()? * 10,
        _ => frac.parse::<i128>().ok()?,
    };
    let value = base + extra;
    (value > 0).then_some(value)
}
fn validate(items: Items) -> Result<Validated, QuoteError> {
    check_count(&items.rows)?;
    let mut rows = Vec::with_capacity(items.rows.len());
    for (index, row) in items.rows.into_iter().enumerate() {
        if !valid_sku(&row.sku) {
            return Err(error!("BAD_SKU", Some(index)));
        }
        if !(1..=1000).contains(&row.qty) {
            return Err(error!("BAD_QTY", Some(index)));
        }
        rows.push(validate_row(row, index)?);
    }
    Ok(Validated { rows })
}
fn validate_row(row: RawItem, index: usize) -> Result<(RawItem, i128), QuoteError> {
    let mut parts = row.price.split('.');
    let whole = parts.next().unwrap_or("");
    let fraction = parts.next().unwrap_or("");
    if !valid_price_parts(&row.price, whole, fraction, parts.next()) {
        return Err(error!("BAD_PRICE", Some(index)));
    }
    let amount = cents_parts(whole, fraction).ok_or_else(|| error!("BAD_PRICE", Some(index)))?;
    Ok((row, amount))
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
fn valid_sku(sku: &str) -> bool {
    (3..=12).contains(&sku.len())
        && sku
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'-')
}
fn merge(items: Validated) -> Result<Merged, QuoteError> {
    let mut grouped = BTreeMap::<String, (i64, i128)>::new();
    for (index, (row, amount)) in items.rows.iter().enumerate() {
        merge_row(&mut grouped, row, *amount, index)?;
    }
    Ok(Merged {
        rows: grouped
            .into_iter()
            .map(|(sku, (qty, price))| (sku, qty, price))
            .collect(),
    })
}
fn merge_row(
    grouped: &mut BTreeMap<String, (i64, i128)>,
    row: &RawItem,
    price: i128,
    index: usize,
) -> Result<(), QuoteError> {
    if let Some((qty, prior)) = grouped.get_mut(&row.sku) {
        if *prior != price {
            return Err(error!("PRICE_CONFLICT", Some(index)));
        }
        *qty += row.qty;
        if *qty > 1000 {
            return Err(error!("BAD_QTY", Some(index)));
        }
    } else {
        grouped.insert(row.sku.clone(), (row.qty, price));
    }
    Ok(())
}
fn check_options(request: &Request) -> Result<Options, QuoteError> {
    let tier = request.tier.trim().to_ascii_lowercase();
    let coupon = request.coupon.trim().to_ascii_uppercase();
    validate_options(&tier, &coupon)?;
    let region_code = request.region.trim().to_ascii_uppercase();
    let region = parse_region(&region_code).ok_or_else(|| error!("BAD_REGION", None))?;
    Ok(Options {
        tier,
        coupon,
        region,
    })
}
fn validate_options(tier: &str, coupon: &str) -> Result<(), QuoteError> {
    if !["basic", "silver", "gold"].contains(&tier) {
        return Err(error!("BAD_TIER", None));
    }
    if !coupon.is_empty() && coupon_value(coupon).is_none() {
        return Err(error!("BAD_COUPON", None));
    }
    Ok(())
}
fn parse_region(code: &str) -> Option<Region> {
    match code {
        "EU" => Some(Region {
            tax_rate: 2000,
            base: 800,
            threshold: 10000,
        }),
        "US" => Some(Region {
            tax_rate: 700,
            base: 500,
            threshold: 7500,
        }),
        "ASIA" => Some(Region {
            tax_rate: 1000,
            base: 1200,
            threshold: 15000,
        }),
        _ => None,
    }
}
fn coupon_value(text: &str) -> Option<(bool, i128)> {
    if text == "FREESHIP" {
        return Some((false, 0));
    }
    for (prefix, percent, limit) in COUPON_KINDS {
        if let Some(digits) = text.strip_prefix(prefix) {
            if digits.is_empty()
                || digits.starts_with('0')
                || !digits.bytes().all(|b| b.is_ascii_digit())
            {
                return None;
            }
            let amount = digits.parse::<i128>().ok()?;
            return (amount <= limit).then_some((percent, amount));
        }
    }
    None
}
fn price(merged: Merged, options: Options) -> Pricing {
    let lines = make_lines(merged.rows);
    let subtotal: i128 = lines.iter().map(|line| i128::from(line.line_cents)).sum();
    let (tier_discount, coupon_discount, net) = discounts(subtotal, &options);
    delivery(
        Pricing {
            lines,
            subtotal,
            tier_discount,
            coupon_discount,
            net,
            shipping: 0,
            tax: 0,
        },
        &options,
    )
}
fn discounts(subtotal: i128, options: &Options) -> (i128, i128, i128) {
    let basis = match options.tier.as_str() {
        "silver" => 500,
        "gold" => 1000,
        _ => 0,
    };
    let tier_discount = (subtotal * basis + 5000) / 10000;
    let after_tier = subtotal - tier_discount;
    let coupon_discount = match coupon_value(&options.coupon) {
        Some((true, n)) => (after_tier * n + 50) / 100,
        Some((false, n)) => (n * 100).min(after_tier),
        None => 0,
    };
    let net = after_tier - coupon_discount;
    (tier_discount, coupon_discount, net)
}
fn make_lines(rows: Vec<(String, i64, i128)>) -> Vec<Line> {
    rows.into_iter()
        .map(|(sku, qty, price)| Line {
            sku,
            qty,
            unit_cents: price as i64,
            line_cents: (price * i128::from(qty)) as i64,
        })
        .collect()
}
fn delivery(mut priced: Pricing, options: &Options) -> Pricing {
    let region = &options.region;
    priced.shipping = if options.coupon == "FREESHIP" || priced.net >= i128::from(region.threshold)
    {
        0
    } else {
        region.base
    };
    priced.tax = (priced.net * i128::from(region.tax_rate) + 5000) / 10000;
    priced
}
fn assemble(p: Pricing) -> Quote {
    let total = p.net + i128::from(p.shipping) + p.tax;
    let applied = applied_names(&p);
    Quote {
        lines: p.lines,
        subtotal: p.subtotal as i64,
        tier_discount: p.tier_discount as i64,
        coupon_discount: p.coupon_discount as i64,
        shipping: p.shipping,
        tax: p.tax as i64,
        total: total as i64,
        applied,
    }
}
fn applied_names(p: &Pricing) -> Vec<String> {
    let mut names = Vec::new();
    if p.tier_discount > 0 {
        names.push("tier".into());
    }
    if p.coupon_discount > 0 {
        names.push("coupon".into());
    }
    if p.shipping == 0 {
        names.push("free-shipping".into());
    }
    if p.tax > 0 {
        names.push("tax".into());
    }
    names
}
/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    Ok(normalise(request))
        .and_then(validate)
        .and_then(merge)
        .and_then(|items| check_options(request).map(|opts| (items, opts)))
        .map(|(items, opts)| assemble(price(items, opts)))
        .map(Outcome::Quote)
        .unwrap_or_else(Outcome::Error)
}
