"""Quote an order in integer cents with tier, coupon, shipping, and regional tax."""

import re


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    tier_rates = {"basic": 0, "silver": 500, "gold": 1000}
    regional_rules = {
        "EU": {"tax_rate": 2000, "shipping": 800, "threshold": 10000},
        "US": {"tax_rate": 700, "shipping": 500, "threshold": 7500},
        "ASIA": {"tax_rate": 1000, "shipping": 1200, "threshold": 15000},
    }
    sku_pattern = r"[A-Z0-9-]{3,12}"
    price_pattern = r"[0-9]{1,6}(?:\.[0-9]{1,2})?"
    coupon_pattern = r"(?:PCT|FIXED)[1-9][0-9]*|FREESHIP"

    raw_items = request["items"]
    tier = request["tier"].strip().lower()
    coupon = request["coupon"].strip().upper()
    region = request["region"].strip().upper()
    if not raw_items:
        return {"error": "EMPTY_ORDER", "index": None}
    if len(raw_items) > 50:
        return {"error": "TOO_MANY_ITEMS", "index": None}

    normalized_items = []
    for index, raw_item in enumerate(raw_items):
        sku = raw_item["sku"].strip().upper()
        quantity = raw_item["qty"]
        price_text = raw_item["price"]
        if not re.fullmatch(sku_pattern, sku):
            return {"error": "BAD_SKU", "index": index}
        if type(quantity) is not int or not 1 <= quantity <= 1000:
            return {"error": "BAD_QTY", "index": index}
        if not isinstance(price_text, str) or not re.fullmatch(
            price_pattern, price_text
        ):
            return {"error": "BAD_PRICE", "index": index}
        whole, dot, fraction = price_text.partition(".")
        if dot:
            cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
        else:
            cents = int(whole) * 100
        if cents <= 0:
            return {"error": "BAD_PRICE", "index": index}
        normalized_items.append((sku, quantity, cents))

    merged_items = {}
    for index, (sku, quantity, unit_cents) in enumerate(normalized_items):
        if sku not in merged_items:
            merged_items[sku] = [quantity, unit_cents]
        else:
            previous_quantity, previous_cents = merged_items[sku]
            if previous_cents != unit_cents:
                return {"error": "PRICE_CONFLICT", "index": index}
            combined_quantity = previous_quantity + quantity
            if combined_quantity > 1000:
                return {"error": "BAD_QTY", "index": index}
            merged_items[sku][0] = combined_quantity

    if tier not in tier_rates:
        return {"error": "BAD_TIER", "index": None}
    coupon_amount = 0
    if coupon:
        if coupon == "FREESHIP":
            pass
        elif re.fullmatch(coupon_pattern, coupon):
            coupon_amount = int(re.search(r"[0-9]+$", coupon).group())
            if coupon.startswith("PCT"):
                if coupon_amount > 50:
                    return {"error": "BAD_COUPON", "index": None}
            elif coupon_amount > 500:
                return {"error": "BAD_COUPON", "index": None}
        else:
            return {"error": "BAD_COUPON", "index": None}
    if region not in regional_rules:
        return {"error": "BAD_REGION", "index": None}

    lines = []
    subtotal = 0
    for sku in sorted(merged_items):
        quantity, unit_cents = merged_items[sku]
        line_cents = quantity * unit_cents
        lines.append(
            {
                "sku": sku,
                "qty": quantity,
                "unit_cents": unit_cents,
                "line_cents": line_cents,
            }
        )
        subtotal += line_cents

    tier_numerator = subtotal * tier_rates[tier]
    tier_discount, tier_remainder = divmod(tier_numerator, 10000)
    if tier_remainder * 2 >= 10000:
        tier_discount += 1
    after_tier = subtotal - tier_discount

    coupon_discount = 0
    if coupon.startswith("PCT"):
        percentage_numerator = after_tier * coupon_amount
        coupon_discount, percentage_remainder = divmod(percentage_numerator, 100)
        if percentage_remainder * 2 >= 100:
            coupon_discount += 1
    elif coupon.startswith("FIXED"):
        coupon_discount = min(coupon_amount * 100, after_tier)
    net = after_tier - coupon_discount

    rules = regional_rules[region]
    if coupon == "FREESHIP" or net >= rules["threshold"]:
        shipping = 0
    else:
        shipping = rules["shipping"]
    tax_numerator = net * rules["tax_rate"]
    tax, tax_remainder = divmod(tax_numerator, 10000)
    if tax_remainder * 2 >= 10000:
        tax += 1
    total = net + shipping + tax

    applied = []
    if tier_discount > 0:
        applied.append("tier")
    if coupon_discount > 0:
        applied.append("coupon")
    if shipping == 0:
        applied.append("free-shipping")
    if tax > 0:
        applied.append("tax")
    return {
        "lines": lines,
        "subtotal": subtotal,
        "tier_discount": tier_discount,
        "coupon_discount": coupon_discount,
        "shipping": shipping,
        "tax": tax,
        "total": total,
        "applied": applied,
    }
