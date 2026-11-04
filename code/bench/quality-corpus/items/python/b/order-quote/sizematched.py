"""Quote an order in integer cents with tier, coupon, shipping, and regional tax."""

import re

TIER_BP = {"basic": 0, "silver": 500, "gold": 1000}
REGIONS = {
    "EU": (2000, 800, 10000),
    "US": (700, 500, 7500),
    "ASIA": (1000, 1200, 15000),
}
SKU = re.compile(r"[A-Z0-9-]{3,12}")
PRICE = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,2})?")
COUPON = re.compile(
    r"(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)"
)


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    raw_items = request["items"]
    tier = request["tier"].strip().lower()
    coupon = request["coupon"].strip().upper()
    region = request["region"].strip().upper()
    if not raw_items:
        return {"error": "EMPTY_ORDER", "index": None}
    if len(raw_items) > 50:
        return {"error": "TOO_MANY_ITEMS", "index": None}

    checked_items = []
    for index, item in enumerate(raw_items):
        sku = item["sku"].strip().upper()
        qty = item["qty"]
        price = item["price"]
        if not SKU.fullmatch(sku):
            return {"error": "BAD_SKU", "index": index}
        if type(qty) is not int or not 1 <= qty <= 1000:
            return {"error": "BAD_QTY", "index": index}
        if not isinstance(price, str) or not PRICE.fullmatch(price):
            return {"error": "BAD_PRICE", "index": index}
        whole, dot, fraction = price.partition(".")
        whole_dollars = int(whole)
        whole_cents = whole_dollars * 100
        fraction_text = fraction.ljust(2, "0") if dot else "00"
        fraction_cents = int(fraction_text)
        unit_cents = whole_cents + fraction_cents
        if unit_cents == 0:
            return {"error": "BAD_PRICE", "index": index}
        checked_items.append({"sku": sku, "qty": qty, "unit_cents": unit_cents})

    merged = {}
    for index, item in enumerate(checked_items):
        sku = item["sku"]
        qty = item["qty"]
        unit_cents = item["unit_cents"]
        if sku not in merged:
            merged[sku] = {"qty": qty, "unit_cents": unit_cents}
            continue
        old_qty = merged[sku]["qty"]
        old_price = merged[sku]["unit_cents"]
        if old_price != unit_cents:
            return {"error": "PRICE_CONFLICT", "index": index}
        combined_qty = old_qty + qty
        if combined_qty > 1000:
            return {"error": "BAD_QTY", "index": index}
        merged[sku] = {"qty": combined_qty, "unit_cents": unit_cents}

    if tier not in TIER_BP:
        return {"error": "BAD_TIER", "index": None}
    if coupon and not COUPON.fullmatch(coupon):
        return {"error": "BAD_COUPON", "index": None}
    if region not in REGIONS:
        return {"error": "BAD_REGION", "index": None}

    lines = []
    subtotal = 0
    for sku, product in sorted(merged.items()):
        qty = product["qty"]
        unit_cents = product["unit_cents"]
        line_cents = qty * unit_cents
        lines.append(
            {"sku": sku, "qty": qty, "unit_cents": unit_cents, "line_cents": line_cents}
        )
        subtotal += line_cents

    tier_rate = TIER_BP[tier]
    tier_product = subtotal * tier_rate
    tier_denominator = 10000
    tier_whole, tier_remainder = divmod(tier_product, tier_denominator)
    tier_fraction_twice = 2 * tier_remainder
    tier_rounds_up = tier_fraction_twice >= tier_denominator
    tier_discount = tier_whole + int(tier_rounds_up)
    after_tier = subtotal - tier_discount
    coupon_discount = 0
    if coupon.startswith("PCT"):
        percent_digits = coupon[3:]
        coupon_rate = int(percent_digits)
        coupon_product = after_tier * coupon_rate
        coupon_denominator = 100
        coupon_whole, coupon_remainder = divmod(coupon_product, coupon_denominator)
        coupon_fraction_twice = 2 * coupon_remainder
        coupon_rounds_up = coupon_fraction_twice >= coupon_denominator
        coupon_discount = coupon_whole + int(coupon_rounds_up)
    elif coupon.startswith("FIXED"):
        fixed_dollars = int(coupon[5:])
        fixed_cents = fixed_dollars * 100
        coupon_discount = min(fixed_cents, after_tier)
    net = after_tier - coupon_discount

    tax_rate, base_shipping, free_threshold = REGIONS[region]
    if coupon == "FREESHIP":
        shipping = 0
    elif net >= free_threshold:
        shipping = 0
    else:
        shipping = base_shipping
    tax_product = net * tax_rate
    tax_denominator = 10000
    tax_whole, tax_remainder = divmod(tax_product, tax_denominator)
    tax_fraction_twice = 2 * tax_remainder
    tax_rounds_up = tax_fraction_twice >= tax_denominator
    tax = tax_whole + int(tax_rounds_up)
    merchandise_total = net + shipping
    total = merchandise_total + tax

    applied = []
    tier_is_applied = tier_discount > 0
    coupon_is_applied = coupon_discount > 0
    shipping_is_waived = shipping == 0
    tax_is_applied = tax > 0
    if tier_is_applied:
        applied.append("tier")
    if coupon_is_applied:
        applied.append("coupon")
    if shipping_is_waived:
        applied.append("free-shipping")
    if tax_is_applied:
        applied.append("tax")
    quote = {
        "lines": lines,
        "subtotal": subtotal,
        "tier_discount": tier_discount,
        "coupon_discount": coupon_discount,
        "shipping": shipping,
        "tax": tax,
        "total": total,
        "applied": applied,
    }
    return quote
