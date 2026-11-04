"""Quote an order in integer cents with tier, coupon, shipping, and regional tax."""

import re

TIER_BASIS_POINTS = {"basic": 0, "silver": 500, "gold": 1000}
REGIONS = {
    "EU": (2000, 800, 10000),
    "US": (700, 500, 7500),
    "ASIA": (1000, 1200, 15000),
}
SKU_PATTERN = re.compile(r"[A-Z0-9-]{3,12}")
PRICE_PATTERN = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,2})?")
COUPON_PATTERN = re.compile(
    r"(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)"
)


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    return (
        items_ok(request) or merge_all(request) or options_ok(request) or price(request)
    )


def items_ok(request):
    order_items = request["items"]
    if not order_items or len(order_items) > 50:
        return make_error("EMPTY_ORDER" if not order_items else "TOO_MANY_ITEMS", None)
    return find_item_error(order_items)


def find_item_error(order_items):
    for item_index, order_item in enumerate(order_items):
        if error_code := item_error_code(order_item):
            return make_error(error_code, item_index)
    return None


def item_error_code(order_item):
    return (
        sku_error_code(order_item["sku"])
        or quantity_error_code(order_item["qty"])
        or ("BAD_PRICE" if price_to_cents(order_item["price"]) is None else None)
    )


def sku_error_code(sku):
    return "BAD_SKU" if not SKU_PATTERN.fullmatch(trim_upper(sku)) else None


def quantity_error_code(quantity):
    return "BAD_QTY" if type(quantity) is not int or not 1 <= quantity <= 1000 else None


def price_to_cents(price_text):
    if not isinstance(price_text, str) or not PRICE_PATTERN.fullmatch(price_text):
        return None
    return positive_price_cents(price_text.partition("."))


def positive_price_cents(price_parts):
    whole_dollars, decimal_point, fractional_dollars = price_parts
    cents = int(whole_dollars) * 100 + int(
        (fractional_dollars if decimal_point else "").ljust(2, "0")
    )
    return cents if cents else None


def trim_upper(text):
    return text.strip().upper()


def merge_all(request):
    return merge_item_rows(request["items"])


def merge_item_rows(order_items):
    merged_items = {}
    for item_index, order_item in enumerate(order_items):
        if error := merge_item(merged_items, order_item, item_index):
            return error
    return None


def merge_item(merged, row, index):
    parts = trim_upper(row["sku"]), row["qty"], price_to_cents(row["price"])
    return merge_item_values(merged, index, parts)


def merge_item_values(merged, index, parts):
    sku, qty, cents = parts
    old_price, old_qty = merged.get(sku, (cents, 0))
    return check_merged_item(merged, sku, qty, cents, index, old_price, old_qty)


def check_merged_item(merged, sku, qty, cents, index, old_price, old_qty):
    if old_price != cents:
        return make_error("PRICE_CONFLICT", index)
    return store_merged_quantity(merged, sku, qty, cents, index, old_qty)


def store_merged_quantity(merged, sku, qty, cents, index, old_qty):
    total = old_qty + qty
    if total > 1000:
        return make_error("BAD_QTY", index)
    merged[sku] = (cents, total)
    return None


def options_ok(request):
    if error_code := options_error(request):
        return make_error(error_code, None)
    return None


def options_error(request):
    tier = request["tier"].strip().lower()
    coupon, region = trim_upper(request["coupon"]), trim_upper(request["region"])
    return bad_tier(tier) or bad_coupon(coupon) or bad_region(region)


def bad_tier(tier):
    return None if tier in TIER_BASIS_POINTS else "BAD_TIER"


def bad_coupon(coupon):
    return None if not coupon or COUPON_PATTERN.fullmatch(coupon) else "BAD_COUPON"


def bad_region(region):
    return None if region in REGIONS else "BAD_REGION"


def sorted_quote_lines(order_items):
    return [
        line_record(sku, values)
        for sku, values in sorted(aggregate_items(order_items).items())
    ]


def aggregate_items(order_items):
    merged_items = {}
    for order_item in order_items:
        add_item_to_aggregate(merged_items, order_item)
    return merged_items


def add_item_to_aggregate(merged_items, order_item):
    sku, unit_cents = aggregate_item_values(order_item)
    merged_items[sku] = (
        unit_cents,
        merged_items.get(sku, (unit_cents, 0))[1] + order_item["qty"],
    )


def aggregate_item_values(order_item):
    return trim_upper(order_item["sku"]), price_to_cents(order_item["price"])


def line_record(sku, values):
    cents, qty = values
    return {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}


def quote_amount_parts(subtotal_cents, quote_options):
    tier, coupon, region = quote_options
    tier_discount = half_up(subtotal_cents * TIER_BASIS_POINTS[tier], 10000)
    coupon_discount = coupon_discount_cents(subtotal_cents - tier_discount, coupon)
    return subtotal_cents, tier_discount, coupon_discount, region, coupon


def coupon_discount_cents(net_cents, coupon):
    return (
        percentage_coupon_discount(net_cents, coupon)
        if coupon.startswith("PCT")
        else fixed_coupon_discount(net_cents, coupon)
    )


def fixed_coupon_discount(net_cents, coupon):
    return min(int(coupon[5:]) * 100, net_cents) if coupon.startswith("FIXED") else 0


def percentage_coupon_discount(net_cents, coupon):
    return half_up(net_cents * int(coupon[3:]), 100)


def half_up(value, divisor):
    return (2 * value + divisor) // (2 * divisor)


def price(request):
    lines = sorted_quote_lines(request["items"])
    subtotal_cents = sum(line["line_cents"] for line in lines)
    amount_parts = quote_amount_parts(subtotal_cents, pricing_options(request))
    return assemble_quote(lines, amount_parts)


def pricing_options(request):
    return (
        request["tier"].strip().lower(),
        trim_upper(request["coupon"]),
        trim_upper(request["region"]),
    )


def assemble_quote(lines, amount_parts):
    applied = applied_adjustments(*adjustments(amount_parts))
    return {**quote_money_fields(*amount_parts), "lines": lines, "applied": applied}


def quote_money_fields(subtotal, discount, cut, region, coupon):
    net = subtotal - discount - cut
    left = dict(subtotal=subtotal, tier_discount=discount, coupon_discount=cut)
    return {**left, **quote_money_remainder(net, region, coupon)}


def quote_money_remainder(net, region, coupon):
    ship = ship_fee(net, coupon, region)
    tax = half_up(net * REGIONS[region][0], 10000)
    return {"shipping": ship, "tax": tax, "total": net + ship + tax}


def adjustments(parts):
    subtotal, discount, cut, region, coupon = parts
    net = subtotal - discount - cut
    ship, tax = ship_fee(net, coupon, region), half_up(net * REGIONS[region][0], 10000)
    return discount, cut, ship, tax


def applied_adjustments(discount, cut, ship, tax):
    return [label for label in applied_labels(discount, cut, ship, tax) if label]


def applied_labels(discount, cut, ship, tax):
    discounts = "tier" if discount else "", "coupon" if cut else ""
    shipping_and_tax = "free-shipping" if ship == 0 else "", "tax" if tax else ""
    return discounts + shipping_and_tax


def ship_fee(net_cents, coupon, region):
    return (
        0
        if coupon == "FREESHIP" or net_cents >= REGIONS[region][2]
        else REGIONS[region][1]
    )


def make_error(error_code, item_index):
    return {"error": error_code, "index": item_index}
