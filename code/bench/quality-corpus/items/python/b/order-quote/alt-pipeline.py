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


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    context = normalise(request)
    for transform in (validate, merge, price, assemble):
        context = transform(context)
        if "error" in context:
            return context
    return context["quote"]


def normalise(request):
    rows = tuple(
        (row["sku"].strip().upper(), row["qty"], row["price"])
        for row in request["items"]
    )
    options = (
        request["tier"].strip().lower(),
        request["coupon"].strip().upper(),
        request["region"].strip().upper(),
    )
    return {"rows": rows, "options": options}


def validate(context):
    rows = context["rows"]
    if not rows or len(rows) > 50:
        return {"error": "EMPTY_ORDER" if not rows else "TOO_MANY_ITEMS", "index": None}
    checked = []
    for index, row in enumerate(rows):
        item, error = validate_item(row, index)
        if error:
            return error
        checked.append(item)
    return {**context, "items": tuple(checked)}


def validate_item(row, index):
    sku, qty, price = row
    if not SKU.fullmatch(sku):
        return None, {"error": "BAD_SKU", "index": index}
    if type(qty) is not int or not 1 <= qty <= 1000:
        return None, {"error": "BAD_QTY", "index": index}
    cents = price_cents(price)
    if cents is None:
        return None, {"error": "BAD_PRICE", "index": index}
    return (sku, qty, cents), None


def price_cents(price):
    if not isinstance(price, str) or not PRICE.fullmatch(price):
        return None
    whole, dot, fraction = price.partition(".")
    cents = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
    return cents if cents else None


def merge(context):
    merged, error = merge_items(context["items"])
    if error:
        return error
    options = context["options"]
    if error := validate_options(options):
        return error
    return {**context, "merged": merged}


def merge_items(items):
    merged = {}
    for index, (sku, qty, cents) in enumerate(items):
        previous = merged.get(sku)
        if previous and previous[1] != cents:
            return None, {"error": "PRICE_CONFLICT", "index": index}
        total_qty = qty + (previous[0] if previous else 0)
        if total_qty > 1000:
            return None, {"error": "BAD_QTY", "index": index}
        merged[sku] = total_qty, cents
    return merged, None


def validate_options(options):
    tier, coupon, region = options
    if tier not in TIER_BP:
        return {"error": "BAD_TIER", "index": None}
    if coupon and not COUPON.fullmatch(coupon):
        return {"error": "BAD_COUPON", "index": None}
    if region not in REGIONS:
        return {"error": "BAD_REGION", "index": None}
    return None


def price(context):
    tier, coupon, region = context["options"]
    lines = make_lines(context["merged"])
    subtotal = sum(line["line_cents"] for line in lines)
    amounts = price_amounts(subtotal, tier, coupon)
    tax_bp, base_shipping, threshold = REGIONS[region]
    shipping = 0 if coupon == "FREESHIP" or amounts[3] >= threshold else base_shipping
    tax = (2 * amounts[3] * tax_bp + 10000) // 20000
    priced = {"lines": lines, "amounts": amounts, "shipping": shipping, "tax": tax}
    return {**context, "priced": priced}


def make_lines(merged):
    return tuple(
        {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}
        for sku, (qty, cents) in sorted(merged.items())
    )


def price_amounts(subtotal, tier, coupon):
    tier_cut = (2 * subtotal * TIER_BP[tier] + 10000) // 20000
    net = subtotal - tier_cut
    coupon_cut = discount(net, coupon)
    return subtotal, tier_cut, coupon_cut, net - coupon_cut


def discount(net, coupon):
    if coupon.startswith("PCT"):
        return (2 * net * int(coupon[3:]) + 100) // 200
    if coupon.startswith("FIXED"):
        return min(int(coupon[5:]) * 100, net)
    return 0


def assemble(context):
    priced = context["priced"]
    lines, amounts = priced["lines"], priced["amounts"]
    shipping, tax = priced["shipping"], priced["tax"]
    subtotal, tier_cut, coupon_cut, net = amounts
    quote = {
        "lines": list(lines),
        "subtotal": subtotal,
        "tier_discount": tier_cut,
        "coupon_discount": coupon_cut,
        "shipping": shipping,
        "tax": tax,
        "total": net + shipping + tax,
        "applied": applied_names(tier_cut, coupon_cut, shipping, tax),
    }
    return {"quote": quote}


def applied_names(tier_cut, coupon_cut, shipping, tax):
    active = (
        (tier_cut > 0, "tier"),
        (coupon_cut > 0, "coupon"),
        (shipping == 0, "free-shipping"),
        (tax > 0, "tax"),
    )
    return [name for enabled, name in active if enabled]
