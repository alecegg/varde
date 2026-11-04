"""Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""

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
ITEM_RULES = (
    (lambda row: not SKU.fullmatch(row[0]), "BAD_SKU"),
    (lambda row: type(row[1]) is not int or not 1 <= row[1] <= 1000, "BAD_QTY"),
)
COUPON_RULES = (("PCT", "percent"), ("FIXED", "fixed"), ("FREESHIP", "none"))


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    return quote(*normalize(request))


def normalize(request):
    rows = tuple(
        (row["sku"].strip().upper(), row["qty"], row["price"])
        for row in request["items"]
    )
    options = (
        request["tier"].strip().lower(),
        request["coupon"].strip().upper(),
        request["region"].strip().upper(),
    )
    return rows, options


def validate(rows):
    if not rows or len(rows) > 50:
        return {"error": "EMPTY_ORDER" if not rows else "TOO_MANY_ITEMS", "index": None}
    checked = []
    for index, row in enumerate(rows):
        error = next((code for invalid, code in ITEM_RULES if invalid(row)), None)
        if error:
            return {"error": error, "index": index}
        cents = price_cents(row[2])
        if cents is None:
            return {"error": "BAD_PRICE", "index": index}
        checked.append((row[0], row[1], cents))
    return tuple(checked)


def price_cents(value):
    if not isinstance(value, str) or not PRICE.fullmatch(value):
        return None
    whole, dot, fraction = value.partition(".")
    result = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
    return result if result > 0 else None


def validate_options(options):
    tier, coupon, region = options
    predicates = (
        (tier not in TIER_BP, "BAD_TIER"),
        (bool(coupon) and not COUPON.fullmatch(coupon), "BAD_COUPON"),
        (region not in REGIONS, "BAD_REGION"),
    )
    return next(
        ({"error": code, "index": None} for invalid, code in predicates if invalid),
        None,
    )


def merge(rows):
    merged = {}
    for index, (sku, qty, cents) in enumerate(rows):
        old = merged.get(sku)
        if old and old[1] != cents:
            return {"error": "PRICE_CONFLICT", "index": index}
        count = qty + (old[0] if old else 0)
        if count > 1000:
            return {"error": "BAD_QTY", "index": index}
        merged[sku] = count, cents
    return merged


def coupon_value(net, coupon):
    kind = (
        next(rule for prefix, rule in COUPON_RULES if coupon.startswith(prefix))
        if coupon
        else "none"
    )
    return {
        "percent": lambda: (2 * net * int(coupon[3:]) + 100) // 200,
        "fixed": lambda: min(int(coupon[5:]) * 100, net),
        "none": lambda: 0,
    }[kind]()


def calculate(merged, options):
    tier, coupon, region = options
    lines = make_lines(merged)
    subtotal = sum(row["line_cents"] for row in lines)
    tier_discount = (2 * subtotal * TIER_BP[tier] + 10000) // 20000
    after_tier = subtotal - tier_discount
    coupon_discount = coupon_value(after_tier, coupon)
    net = after_tier - coupon_discount
    shipping, tax = delivery_costs(net, coupon, region)
    return lines, subtotal, tier_discount, coupon_discount, net, shipping, tax


def make_lines(merged):
    return [
        {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}
        for sku, (qty, cents) in sorted(merged.items())
    ]


def delivery_costs(net, coupon, region):
    tax_rate, ship_rate, free_at = REGIONS[region]
    shipping = 0 if coupon == "FREESHIP" or net >= free_at else ship_rate
    tax = (2 * net * tax_rate + 10000) // 20000
    return shipping, tax


def quote(rows, options):
    checked = validate(rows)
    if isinstance(checked, dict):
        return checked
    merged = merge(checked)
    if isinstance(merged, dict) and "error" in merged:
        return merged
    if error := validate_options(options):
        return error
    return result(calculate(merged, options))


def result(values):
    lines, subtotal, tier_discount, coupon_discount, net, shipping, tax = values
    active = (
        (tier_discount > 0, "tier"),
        (coupon_discount > 0, "coupon"),
        (shipping == 0, "free-shipping"),
        (tax > 0, "tax"),
    )
    return {
        "lines": lines,
        "subtotal": subtotal,
        "tier_discount": tier_discount,
        "coupon_discount": coupon_discount,
        "shipping": shipping,
        "tax": tax,
        "total": net + shipping + tax,
        "applied": [name for enabled, name in active if enabled],
    }
