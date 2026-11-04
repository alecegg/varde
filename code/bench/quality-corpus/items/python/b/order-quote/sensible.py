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
    items, tier, coupon, region = normalise(request)
    if error := validate(items):
        return error
    merged, error = merge_items(items, tier, coupon, region)
    if error:
        return error
    lines, amounts = price_lines(merged)
    return finish(lines, adjust(amounts, tier, coupon), coupon, region)


def normalise(request):
    items = [
        [row["sku"].strip().upper(), row["qty"], row["price"]]
        for row in request["items"]
    ]
    return (
        items,
        request["tier"].strip().lower(),
        request["coupon"].strip().upper(),
        request["region"].strip().upper(),
    )


def validate(items):
    if not items or len(items) > 50:
        return {
            "error": "EMPTY_ORDER" if not items else "TOO_MANY_ITEMS",
            "index": None,
        }
    for index, row in enumerate(items):
        if error := check_item(row, index):
            return error
        cents = price_cents(row[2])
        if cents is None:
            return {"error": "BAD_PRICE", "index": index}
        row.append(cents)


def check_item(row, index):
    if not SKU.fullmatch(row[0]):
        return {"error": "BAD_SKU", "index": index}
    if type(row[1]) is not int or not 1 <= row[1] <= 1000:
        return {"error": "BAD_QTY", "index": index}
    return None


def price_cents(price):
    if not isinstance(price, str) or not PRICE.fullmatch(price):
        return None
    whole, dot, fraction = price.partition(".")
    cents = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
    return cents if cents else None


def merge_items(items, tier, coupon, region):
    merged = {}
    for index, row in enumerate(items):
        if error := merge_one(merged, row, index):
            return {}, error
    if error := check_options(tier, coupon, region):
        return {}, error
    return merged, None


def check_options(tier, coupon, region):
    if tier not in TIER_BP:
        return {"error": "BAD_TIER", "index": None}
    if coupon and not COUPON.fullmatch(coupon):
        return {"error": "BAD_COUPON", "index": None}
    if region not in REGIONS:
        return {"error": "BAD_REGION", "index": None}
    return None


def merge_one(merged, row, index):
    sku, qty, _, cents = row
    if sku in merged:
        if merged[sku][1] != cents:
            return {"error": "PRICE_CONFLICT", "index": index}
        qty += merged[sku][0]
        if qty > 1000:
            return {"error": "BAD_QTY", "index": index}
    merged[sku] = [qty, cents]


def price_lines(merged):
    lines = []
    for sku, (qty, cents) in sorted(merged.items()):
        lines.append(
            {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}
        )
    subtotal = sum(line["line_cents"] for line in lines)
    return lines, (subtotal,)


def adjust(amounts, tier, coupon):
    subtotal = amounts[0]
    tier_cut = (2 * subtotal * TIER_BP[tier] + 10000) // 20000
    net = subtotal - tier_cut
    coupon_cut = coupon_discount(net, coupon)
    return subtotal, tier_cut, coupon_cut, net - coupon_cut


def coupon_discount(net, coupon):
    if coupon.startswith("PCT"):
        return (2 * net * int(coupon[3:]) + 100) // 200
    if coupon.startswith("FIXED"):
        return min(int(coupon[5:]) * 100, net)
    return 0


def finish(lines, amounts, coupon, region):
    subtotal, tier_cut, coupon_cut, net = amounts
    tax_bp, base_shipping, threshold = REGIONS[region]
    shipping = 0 if coupon == "FREESHIP" or net >= threshold else base_shipping
    tax = (2 * net * tax_bp + 10000) // 20000
    applied = applied_rules(tier_cut, coupon_cut, shipping, tax)
    return quote_result(lines, amounts, shipping, tax, applied)


def quote_result(lines, amounts, shipping, tax, applied):
    subtotal, tier_cut, coupon_cut, net = amounts
    return {
        "lines": lines,
        "subtotal": subtotal,
        "tier_discount": tier_cut,
        "coupon_discount": coupon_cut,
        "shipping": shipping,
        "tax": tax,
        "total": net + shipping + tax,
        "applied": applied,
    }


def applied_rules(tier_cut, coupon_cut, shipping, tax):
    active = (
        (tier_cut > 0, "tier"),
        (coupon_cut > 0, "coupon"),
        (shipping == 0, "free-shipping"),
        (tax > 0, "tax"),
    )
    return [name for enabled, name in active if enabled]
