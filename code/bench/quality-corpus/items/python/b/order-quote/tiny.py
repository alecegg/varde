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
    return item_errors(request) or merge(request) or opts(request) or quote(request)


def item_errors(request):
    rows = request["items"]
    if not rows or len(rows) > 50:
        return error_at("EMPTY_ORDER" if not rows else "TOO_MANY_ITEMS", None)
    return item_error(rows)


def item_error(rows):
    for index, row in enumerate(rows):
        if code := item_code(row):
            return error_at(code, index)
    return None


def item_code(row):
    return (
        sku_error(row["sku"])
        or qty_error(row["qty"])
        or ("BAD_PRICE" if price_cents(row["price"]) is None else None)
    )


def sku_error(value):
    return "BAD_SKU" if not SKU.fullmatch(trim_up(value)) else None


def qty_error(value):
    return "BAD_QTY" if type(value) is not int or not 1 <= value <= 1000 else None


def price_cents(value):
    if not isinstance(value, str) or not PRICE.fullmatch(value):
        return None
    return positive_cents(value.partition("."))


def positive_cents(parts):
    whole, dot, fraction = parts
    cents = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
    return cents if cents else None


def trim_up(value):
    return value.strip().upper()


def merge(request):
    return merge_rows(request["items"])


def merge_rows(rows):
    merged = {}
    for i, row in enumerate(rows):
        if issue := merge_one(merged, row, i):
            return issue
    return None


def merge_one(merged, row, index):
    parts = trim_up(row["sku"]), row["qty"], price_cents(row["price"])
    return merge_values(merged, index, parts)


def merge_values(merged, index, parts):
    sku, qty, cents = parts
    old_price, old_qty = merged.get(sku, (cents, 0))
    return merge_check(merged, sku, qty, cents, index, old_price, old_qty)


def merge_check(merged, sku, qty, cents, index, old_price, old_qty):
    if old_price != cents:
        return error_at("PRICE_CONFLICT", index)
    return merged_qty(merged, sku, qty, cents, index, old_qty)


def merged_qty(merged, sku, qty, cents, index, old_qty):
    total = old_qty + qty
    if total > 1000:
        return error_at("BAD_QTY", index)
    merged[sku] = (cents, total)
    return None


def opts(request):
    if code := option_code(request):
        return error_at(code, None)
    return None


def option_code(request):
    tier = request["tier"].strip().lower()
    coupon, region = trim_up(request["coupon"]), trim_up(request["region"])
    return tier_error(tier) or coupon_error(coupon) or region_error(region)


def tier_error(tier):
    return None if tier in TIER_BP else "BAD_TIER"


def coupon_error(coupon):
    return None if not coupon or COUPON.fullmatch(coupon) else "BAD_COUPON"


def region_error(region):
    return None if region in REGIONS else "BAD_REGION"


def sorted_lines(rows):
    return [line_dict(sku, values) for sku, values in sorted(accumulate(rows).items())]


def accumulate(rows):
    merged = {}
    for row in rows:
        add_aggregate(merged, row)
    return merged


def add_aggregate(merged, row):
    sku, cents = aggregate_values(row)
    merged[sku] = (cents, merged.get(sku, (cents, 0))[1] + row["qty"])


def aggregate_values(row):
    return trim_up(row["sku"]), price_cents(row["price"])


def line_dict(sku, values):
    cents, qty = values
    return {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}


def amount_parts(subtotal, options):
    tier, coupon, region = options
    discount = round_up(subtotal * TIER_BP[tier], 10000)
    cut = coupon_value(subtotal - discount, coupon)
    return subtotal, discount, cut, region, coupon


def coupon_value(net, coupon):
    return (
        coupon_pct(net, coupon)
        if coupon.startswith("PCT")
        else coupon_rest(net, coupon)
    )


def coupon_rest(net, coupon):
    return min(int(coupon[5:]) * 100, net) if coupon.startswith("FIXED") else 0


def coupon_pct(net, coupon):
    return round_up(net * int(coupon[3:]), 100)


def round_up(value, divisor):
    return (2 * value + divisor) // (2 * divisor)


def quote(request):
    lines = sorted_lines(request["items"])
    subtotal = sum(line["line_cents"] for line in lines)
    values = amount_parts(subtotal, quote_options(request))
    return quote_fields(lines, values)


def quote_options(request):
    return (
        request["tier"].strip().lower(),
        trim_up(request["coupon"]),
        trim_up(request["region"]),
    )


def quote_fields(lines, values):
    applied = applied_parts(*applied_values(values))
    return {**money_dict(*values), "lines": lines, "applied": applied}


def money_dict(subtotal, discount, coupon_cut, region, coupon):
    net = subtotal - discount - coupon_cut
    left = dict(subtotal=subtotal, tier_discount=discount, coupon_discount=coupon_cut)
    return {**left, **money_right(net, region, coupon)}


def money_right(net, region, coupon):
    ship = shipping(net, coupon, region)
    tax = round_up(net * REGIONS[region][0], 10000)
    return {"shipping": ship, "tax": tax, "total": net + ship + tax}


def applied_values(values):
    subtotal, discount, cut, region, coupon = values
    net = subtotal - discount - cut
    ship, tax = shipping(net, coupon, region), round_up(net * REGIONS[region][0], 10000)
    return discount, cut, ship, tax


def applied_parts(discount, cut, ship, tax):
    return [name for name in applied_flags(discount, cut, ship, tax) if name]


def applied_flags(discount, cut, ship, tax):
    discounts = "tier" if discount else "", "coupon" if cut else ""
    shipping = "free-shipping" if ship == 0 else "", "tax" if tax else ""
    return discounts + shipping


def shipping(net, coupon, region):
    return (
        0 if coupon == "FREESHIP" or net >= REGIONS[region][2] else REGIONS[region][1]
    )


def error_at(code, index):
    return {"error": code, "index": index}
