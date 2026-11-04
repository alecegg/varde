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

/// Quote an order in integer cents with tier, coupon, shipping, and regional tax.
pub fn solution(request: &Request) -> Outcome {
    let mut items = Vec::with_capacity(request.items.len());
    for item in &request.items {
        let trimmed_sku = item.sku.trim();
        let normalized_sku = trimmed_sku.to_ascii_uppercase();
        let original_quantity = item.qty;
        let original_price_text = item.price.clone();
        items.push(RawItem {
            sku: normalized_sku,
            qty: original_quantity,
            price: original_price_text,
        });
    }
    let trimmed_tier = request.tier.trim();
    let tier = trimmed_tier.to_ascii_lowercase();
    let trimmed_coupon = request.coupon.trim();
    let coupon = trimmed_coupon.to_ascii_uppercase();
    let trimmed_region = request.region.trim();
    let region = trimmed_region.to_ascii_uppercase();
    let normalized = Normalized {
        items,
        tier,
        coupon,
        region,
    };
    if normalized.items.is_empty() {
        return Outcome::Error(quote_error!("EMPTY_ORDER", None));
    }
    let item_count = normalized.items.len();
    let maximum_item_count = 50;
    if item_count > maximum_item_count {
        return Outcome::Error(quote_error!("TOO_MANY_ITEMS", None));
    }

    let mut checked = Vec::new();
    for (index, item) in normalized.items.iter().enumerate() {
        if !(3..=12).contains(&item.sku.len())
            || !item
                .sku
                .bytes()
                .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'-')
        {
            return Outcome::Error(quote_error!("BAD_SKU", Some(index)));
        }
        let minimum_quantity = 1;
        let maximum_quantity = 1000;
        let quantity_in_range = (minimum_quantity..=maximum_quantity).contains(&item.qty);
        if !quantity_in_range {
            return Outcome::Error(quote_error!("BAD_QTY", Some(index)));
        }
        let mut price_parts = item.price.split('.');
        let whole_text = price_parts.next().unwrap_or("");
        let fraction_text = price_parts.next().unwrap_or("");
        let has_decimal = item.price.contains('.');
        let has_one_decimal_point = price_parts.next().is_none();
        let whole_is_present = !whole_text.is_empty();
        let whole_is_bounded = whole_text.len() <= 6;
        let fraction_is_present = !has_decimal || !fraction_text.is_empty();
        let fraction_is_bounded = fraction_text.len() <= 2;
        let whole_is_numeric = whole_text.bytes().all(|byte| byte.is_ascii_digit());
        let fraction_is_numeric = fraction_text.bytes().all(|byte| byte.is_ascii_digit());
        let price_shape_ok = has_one_decimal_point
            && whole_is_present
            && whole_is_bounded
            && fraction_is_present
            && fraction_is_bounded
            && whole_is_numeric
            && fraction_is_numeric;
        if !price_shape_ok {
            return Outcome::Error(quote_error!("BAD_PRICE", Some(index)));
        }
        let whole_units = whole_text.parse::<i128>().unwrap();
        let cents_per_unit = 100;
        let whole_cents = whole_units * cents_per_unit;
        let fraction_digits = fraction_text.len();
        let fraction_cents = match fraction_digits {
            0 => 0,
            1 => fraction_text.parse::<i128>().unwrap() * 10,
            _ => fraction_text.parse::<i128>().unwrap(),
        };
        let cents = whole_cents + fraction_cents;
        let price_is_positive = cents > 0;
        if !price_is_positive {
            return Outcome::Error(quote_error!("BAD_PRICE", Some(index)));
        }
        checked.push(CheckedItem {
            sku: item.sku.clone(),
            qty: item.qty,
            cents,
        });
    }
    let mut merged = BTreeMap::<String, (i64, i128)>::new();
    for (index, item) in checked.into_iter().enumerate() {
        let sku_key = item.sku.clone();
        if let Some((quantity, unit_cents)) = merged.get_mut(&sku_key) {
            let same_unit_price = *unit_cents == item.cents;
            if !same_unit_price {
                return Outcome::Error(quote_error!("PRICE_CONFLICT", Some(index)));
            }
            let previous_quantity = *quantity;
            let incoming_quantity = item.qty;
            let combined = previous_quantity + incoming_quantity;
            let merged_quantity_is_valid = combined <= 1000;
            if !merged_quantity_is_valid {
                return Outcome::Error(quote_error!("BAD_QTY", Some(index)));
            }
            *quantity = combined;
        } else {
            let first_quantity = item.qty;
            let first_unit_price = item.cents;
            merged.insert(item.sku, (first_quantity, first_unit_price));
        }
    }
    let supported_tiers = ["basic", "silver", "gold"];
    let tier_is_supported = supported_tiers.contains(&normalized.tier.as_str());
    if !tier_is_supported {
        return Outcome::Error(quote_error!("BAD_TIER", None));
    }
    let percent_coupon = normalized.coupon.starts_with("PCT");
    let coupon_suffix = if percent_coupon {
        normalized.coupon.strip_prefix("PCT")
    } else {
        normalized.coupon.strip_prefix("FIXED")
    };
    let coupon_amount = if normalized.coupon == "FREESHIP" || normalized.coupon.is_empty() {
        0
    } else if let Some(suffix) = coupon_suffix {
        let maximum = if percent_coupon { 50 } else { 500 };
        if suffix.is_empty()
            || suffix.starts_with('0')
            || !suffix.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Outcome::Error(quote_error!("BAD_COUPON", None));
        }
        let amount = suffix.parse::<i128>().unwrap();
        if amount > maximum {
            return Outcome::Error(quote_error!("BAD_COUPON", None));
        }
        amount
    } else {
        return Outcome::Error(quote_error!("BAD_COUPON", None));
    };
    let supported_regions = ["EU", "US", "ASIA"];
    let region_is_supported = supported_regions.contains(&normalized.region.as_str());
    if !region_is_supported {
        return Outcome::Error(quote_error!("BAD_REGION", None));
    }

    let mut lines = Vec::new();
    let mut subtotal = 0i128;
    for (sku, (qty, cents)) in merged {
        let quantity_wide = i128::from(qty);
        let unit_value = cents;
        let line_product = quantity_wide * unit_value;
        let line_cents = line_product;
        let output_unit_cents = cents as i64;
        let output_line_cents = line_cents as i64;
        let order_line = Line {
            sku,
            qty,
            unit_cents: output_unit_cents,
            line_cents: output_line_cents,
        };
        lines.push(order_line);
        let subtotal_with_line = subtotal + line_cents;
        subtotal = subtotal_with_line;
    }
    let priced = Priced { lines, subtotal };
    let tier_rate = match normalized.tier.as_str() {
        "basic" => 0,
        "silver" => 500,
        "gold" => 1000,
        _ => unreachable!(),
    };
    let tier_product = priced.subtotal * tier_rate;
    let tier_denominator = 10_000;
    let tier_whole = tier_product / tier_denominator;
    let tier_remainder = tier_product % tier_denominator;
    let tier_remainder_twice = tier_remainder * 2;
    let mut tier_discount = tier_whole;
    if tier_remainder_twice >= tier_denominator {
        tier_discount += 1;
    }
    let after_tier = priced.subtotal - tier_discount;
    let coupon_discount = if percent_coupon && !normalized.coupon.is_empty() {
        let percent_base = after_tier;
        let percentage_product = percent_base * coupon_amount;
        let percentage_denominator = 100;
        let percentage_whole = percentage_product / percentage_denominator;
        let percentage_remainder = percentage_product % percentage_denominator;
        let percentage_remainder_twice = percentage_remainder * 2;
        let mut value = percentage_whole;
        if percentage_remainder_twice >= percentage_denominator {
            value += 1;
        }
        value
    } else if normalized.coupon.starts_with("FIXED") {
        (coupon_amount * 100).min(after_tier)
    } else {
        0
    };
    let net = after_tier - coupon_discount;
    let adjusted = Adjusted {
        subtotal: priced.subtotal,
        tier_discount,
        coupon_discount,
        net,
    };
    let (tax_rate, base_shipping, threshold) = match normalized.region.as_str() {
        "EU" => (2000, 800, 10_000),
        "US" => (700, 500, 7_500),
        "ASIA" => (1000, 1200, 15_000),
        _ => unreachable!(),
    };
    let coupon_waives_shipping = normalized.coupon == "FREESHIP";
    let order_reaches_shipping_threshold = adjusted.net >= threshold;
    let shipping_is_free = coupon_waives_shipping || order_reaches_shipping_threshold;
    let shipping = if shipping_is_free { 0 } else { base_shipping };
    let tax_product = adjusted.net * tax_rate;
    let tax_denominator = 10_000;
    let tax_whole = tax_product / tax_denominator;
    let tax_remainder = tax_product % tax_denominator;
    let tax_remainder_twice = tax_remainder * 2;
    let mut tax = tax_whole;
    if tax_remainder_twice >= tax_denominator {
        tax += 1;
    }
    let shipping_total = i128::from(shipping);
    let total = adjusted.net + shipping_total + tax;
    let output_subtotal = adjusted.subtotal as i64;
    let output_tier_discount = adjusted.tier_discount as i64;
    let output_coupon_discount = adjusted.coupon_discount as i64;
    let output_tax = tax as i64;
    let output_total = total as i64;
    let tier_was_discounted = adjusted.tier_discount > 0;
    let coupon_was_applied = adjusted.coupon_discount > 0;
    let shipping_was_waived = shipping == 0;
    let tax_was_charged = tax > 0;
    let mut applied = Vec::with_capacity(4);
    if tier_was_discounted {
        applied.push("tier".to_string());
    }
    if coupon_was_applied {
        applied.push("coupon".to_string());
    }
    if shipping_was_waived {
        applied.push("free-shipping".to_string());
    }
    if tax_was_charged {
        applied.push("tax".to_string());
    }
    Outcome::Quote(Quote {
        lines: priced.lines,
        subtotal: output_subtotal,
        tier_discount: output_tier_discount,
        coupon_discount: output_coupon_discount,
        shipping,
        tax: output_tax,
        total: output_total,
        applied,
    })
}
