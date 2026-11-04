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

const COUPON_KINDS: [(&str, bool, i128); 2] = [("PCT", true, 50), ("FIXED", false, 500)];
struct Region {
    base: i64,
    threshold: i128,
    tax_rate: i128,
}
struct Options {
    tier_rate: i128,
    coupon: Option<(bool, i128)>,
    region: Region,
}
struct Priced {
    lines: Vec<Line>,
    subtotal: i128,
    tier: i128,
    coupon: i128,
    net: i128,
    shipping: i64,
    tax: i128,
}
struct Builder {
    items: Vec<RawItem>,
    tier: String,
    coupon: String,
    region: String,
}

impl Builder {
    fn new(request: &Request) -> Self {
        Self {
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
    fn validate(&self) -> Result<Vec<i128>, QuoteError> {
        if self.items.is_empty() {
            return Err(issue("EMPTY_ORDER", None));
        }
        if self.items.len() > 50 {
            return Err(issue("TOO_MANY_ITEMS", None));
        }
        let mut prices = Vec::with_capacity(self.items.len());
        for (index, item) in self.items.iter().enumerate() {
            validate_item_fields(item, index)?;
            prices.push(self.validate_row(item, index)?);
        }
        Ok(prices)
    }
    fn validate_row(&self, item: &RawItem, index: usize) -> Result<i128, QuoteError> {
        if !valid_price_text(&item.price) {
            return Err(issue("BAD_PRICE", Some(index)));
        }
        let (whole, fraction) = item.price.split_once('.').unwrap_or((&item.price, ""));
        Self::cents_from_parts(whole, fraction).ok_or_else(|| issue("BAD_PRICE", Some(index)))
    }
    fn cents_from_parts(whole: &str, fraction: &str) -> Option<i128> {
        let tail = match fraction.len() {
            0 => 0,
            1 => fraction.parse::<i128>().ok()? * 10,
            _ => fraction.parse::<i128>().ok()?,
        };
        Some(whole.parse::<i128>().ok()? * 100 + tail)
    }
    fn merge(&self, amounts: &[i128]) -> Result<BTreeMap<String, (i64, i128)>, QuoteError> {
        let mut grouped = BTreeMap::new();
        for (index, (item, amount)) in self.items.iter().zip(amounts).enumerate() {
            merge_item(&mut grouped, item, *amount, index)?;
        }
        Ok(grouped)
    }
    fn check_options(&self) -> Result<Options, QuoteError> {
        let tier_rate = match self.tier.as_str() {
            "basic" => 0,
            "silver" => 500,
            "gold" => 1000,
            _ => return Err(issue("BAD_TIER", None)),
        };
        let coupon = if self.coupon.is_empty() {
            None
        } else {
            Some(coupon_value(&self.coupon).ok_or_else(|| issue("BAD_COUPON", None))?)
        };
        let region = region_info(&self.region).ok_or_else(|| issue("BAD_REGION", None))?;
        Ok(Options {
            tier_rate,
            coupon,
            region,
        })
    }
    fn price(&self, grouped: BTreeMap<String, (i64, i128)>, options: Options) -> Priced {
        let lines = make_lines(grouped);
        let subtotal = lines.iter().map(|line| i128::from(line.line_cents)).sum();
        let tier = (subtotal * options.tier_rate + 5000) / 10000;
        let after_tier = subtotal - tier;
        let coupon = discount(after_tier, options.coupon);
        let net = after_tier - coupon;
        let (shipping, tax) = delivery(net, &options.region, &self.coupon);
        Priced {
            lines,
            subtotal,
            tier,
            coupon,
            net,
            shipping,
            tax,
        }
    }
    fn finish(&self, priced: Priced) -> Quote {
        let applied = applied_labels(priced.tier, priced.coupon, priced.shipping == 0, priced.tax);
        Quote {
            lines: priced.lines,
            subtotal: priced.subtotal as i64,
            tier_discount: priced.tier as i64,
            coupon_discount: priced.coupon as i64,
            shipping: priced.shipping,
            tax: priced.tax as i64,
            total: (priced.net + i128::from(priced.shipping) + priced.tax) as i64,
            applied,
        }
    }
}
fn region_info(code: &str) -> Option<Region> {
    match code {
        "EU" => Some(Region {
            base: 800,
            threshold: 10000,
            tax_rate: 2000,
        }),
        "US" => Some(Region {
            base: 500,
            threshold: 7500,
            tax_rate: 700,
        }),
        "ASIA" => Some(Region {
            base: 1200,
            threshold: 15000,
            tax_rate: 1000,
        }),
        _ => None,
    }
}
fn applied_labels(tier: i128, coupon: i128, free: bool, tax: i128) -> Vec<String> {
    let mut labels = Vec::new();
    if tier > 0 {
        labels.push("tier".into());
    }
    if coupon > 0 {
        labels.push("coupon".into());
    }
    if free {
        labels.push("free-shipping".into());
    }
    if tax > 0 {
        labels.push("tax".into());
    }
    labels
}
fn validate_item_fields(item: &RawItem, index: usize) -> Result<(), QuoteError> {
    if !valid_sku(&item.sku) {
        return Err(issue("BAD_SKU", Some(index)));
    }
    if !(1..=1000).contains(&item.qty) {
        return Err(issue("BAD_QTY", Some(index)));
    }
    Ok(())
}
fn valid_price_text(text: &str) -> bool {
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    !whole.is_empty()
        && whole.len() <= 6
        && fraction.len() <= 2
        && (!text.contains('.') || !fraction.is_empty())
        && text.matches('.').count() <= 1
        && text.bytes().all(|b| b.is_ascii_digit() || b == b'.')
        && text.bytes().any(|b| b.is_ascii_digit() && b != b'0')
}
fn issue(code: &str, index: Option<usize>) -> QuoteError {
    QuoteError {
        code: code.into(),
        index,
    }
}
fn valid_sku(sku: &str) -> bool {
    (3..=12).contains(&sku.len())
        && sku
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'-')
}
fn merge_item(
    map: &mut BTreeMap<String, (i64, i128)>,
    item: &RawItem,
    price: i128,
    index: usize,
) -> Result<(), QuoteError> {
    if let Some((qty, prior)) = map.get_mut(&item.sku) {
        if *prior != price {
            return Err(issue("PRICE_CONFLICT", Some(index)));
        }
        *qty += item.qty;
        if *qty > 1000 {
            return Err(issue("BAD_QTY", Some(index)));
        }
    } else {
        map.insert(item.sku.clone(), (item.qty, price));
    }
    Ok(())
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
fn discount(amount: i128, coupon: Option<(bool, i128)>) -> i128 {
    match coupon {
        Some((true, n)) => (amount * n + 50) / 100,
        Some((false, n)) => (n * 100).min(amount),
        None => 0,
    }
}
fn delivery(net: i128, region: &Region, coupon: &str) -> (i64, i128) {
    let shipping = if coupon == "FREESHIP" || net >= region.threshold {
        0
    } else {
        region.base
    };
    let tax = (net * region.tax_rate + 5000) / 10000;
    (shipping, tax)
}
fn make_lines(grouped: BTreeMap<String, (i64, i128)>) -> Vec<Line> {
    grouped
        .into_iter()
        .map(|(sku, (qty, cents))| Line {
            sku,
            qty,
            unit_cents: cents as i64,
            line_cents: (cents * i128::from(qty)) as i64,
        })
        .collect()
}
/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let builder = Builder::new(request);
    let amounts = match builder.validate() {
        Ok(rows) => rows,
        Err(error) => return Outcome::Error(error),
    };
    let grouped = match builder.merge(&amounts) {
        Ok(rows) => rows,
        Err(error) => return Outcome::Error(error),
    };
    let options = match builder.check_options() {
        Ok(options) => options,
        Err(error) => return Outcome::Error(error),
    };
    Outcome::Quote(builder.finish(builder.price(grouped, options)))
}
