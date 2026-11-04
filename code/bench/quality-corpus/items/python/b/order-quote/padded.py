"""Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""

import re
from typing import NamedTuple

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


class Item(NamedTuple):
    sku: str
    quantity: int
    price_text: str
    cents: int | None


class Order(NamedTuple):
    items: list
    tier: str
    coupon: str
    region: str


class Adjustment(NamedTuple):
    name: str
    cents: int
    active: bool


class Quote(NamedTuple):
    lines: list
    subtotal: int
    tier_discount: int
    coupon_discount: int
    shipping: int
    tax: int
    total: int
    applied: list


def solution(request: dict) -> dict:
    """Quote normalized order lines with discounts, shipping, tax, and applied adjustments."""
    order = normalise(request)
    if failure := check_item_count(order):
        return result_dict(failure)
    return result_dict(make_quote(order))


def make_quote(order):
    validated = validate_items(order.items)
    if isinstance(validated, tuple):
        return validated
    merged = merge_items(validated)
    if isinstance(merged, tuple):
        return merged
    failure = check_options(order)
    if failure is not None:
        return failure
    return build_quote(merged, order)


def normalise(request):
    return Order(
        [normalise_item(row) for row in request["items"]],
        request["tier"].strip().lower(),
        request["coupon"].strip().upper(),
        request["region"].strip().upper(),
    )


def normalise_item(row):
    raw_sku = row["sku"]
    sku = raw_sku.strip().upper()
    quantity = row["qty"]
    price_text = row["price"]
    return Item(sku, quantity, price_text, None)


def check_item_count(order):
    item_count = len(order.items)
    if item_count == 0:
        return ("EMPTY_ORDER", None)
    if item_count > 50:
        return ("TOO_MANY_ITEMS", None)
    return None


def validate_items(items):
    validated = []
    for index, row in enumerate(items):
        result = check_item(row, index)
        if not isinstance(result, Item):
            return result
        validated.append(result)
    return validated


def check_item(row, index):
    failure = check_sku_quantity(row, index)
    if failure is not None:
        return failure
    cents = price_cents(row.price_text)
    if cents is None:
        return ("BAD_PRICE", index)
    return Item(row.sku, row.quantity, row.price_text, cents)


def check_sku_quantity(row, index):
    sku_is_valid = SKU.fullmatch(row.sku) is not None
    if not sku_is_valid:
        return ("BAD_SKU", index)
    quantity = row.quantity
    quantity_is_valid = type(quantity) is int and 1 <= quantity <= 1000
    if not quantity_is_valid:
        return ("BAD_QTY", index)
    return None


def price_cents(text):
    if not isinstance(text, str):
        return None
    if PRICE.fullmatch(text) is None:
        return None
    whole, _, fraction = text.partition(".")
    whole_cents = int(whole) * 100
    fractional_cents = int(fraction.ljust(2, "0"))
    cents = whole_cents + fractional_cents
    return cents if cents > 0 else None


def merge_items(items):
    merged = {}
    for index, row in enumerate(items):
        failure = merge_duplicate(merged, row, index)
        if failure is not None:
            return failure
    return merged


def merge_duplicate(merged, row, index):
    prior = merged.setdefault(row.sku, [0, row.cents])
    if prior[1] != row.cents:
        return ("PRICE_CONFLICT", index)
    combined_quantity = prior[0] + row.quantity
    if combined_quantity > 1000:
        return ("BAD_QTY", index)
    prior[0] = combined_quantity
    return None


def check_options(order):
    if order.tier not in TIER_BP:
        return ("BAD_TIER", None)
    if order.coupon and COUPON.fullmatch(order.coupon) is None:
        return ("BAD_COUPON", None)
    if order.region not in REGIONS:
        return ("BAD_REGION", None)
    return None


def build_quote(merged, order):
    lines = make_lines(merged)
    subtotal = sum(line["line_cents"] for line in lines)
    tier = tier_adjustment(subtotal, order.tier)
    after_tier = subtotal - tier.cents
    coupon = coupon_adjustment(after_tier, order.coupon)
    net = after_tier - coupon.cents
    return assemble_quote(lines, subtotal, tier, coupon, net, order)


def assemble_quote(lines, subtotal, tier, coupon, net, order):
    shipping = shipping_adjustment(net, order)
    tax = tax_adjustment(net, order)
    return Quote(
        lines,
        subtotal,
        tier.cents,
        coupon.cents,
        shipping.cents,
        tax.cents,
        net + shipping.cents + tax.cents,
        collect_applied(tier, coupon, shipping, tax),
    )


def make_lines(merged):
    lines = []
    for sku, values in sorted(merged.items()):
        quantity = values[0]
        cents = values[1]
        line_cents = quantity * cents
        lines.append(
            {"sku": sku, "qty": quantity, "unit_cents": cents, "line_cents": line_cents}
        )
    return lines


def round_half_up(numerator, denominator):
    whole, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        return whole + 1
    return whole


def tier_adjustment(subtotal, tier):
    basis_points = TIER_BP[tier]
    numerator = subtotal * basis_points
    cents = round_half_up(numerator, 10000)
    return Adjustment("tier", cents, cents > 0)


def coupon_adjustment(net, coupon):
    if coupon.startswith("PCT"):
        cents = round_half_up(net * int(coupon[3:]), 100)
    elif coupon.startswith("FIXED"):
        cents = min(int(coupon[5:]) * 100, net)
    else:
        cents = 0
    return Adjustment("coupon", cents, cents > 0)


def shipping_adjustment(net, order):
    _, base, threshold = REGIONS[order.region]
    free_shipping = order.coupon == "FREESHIP" or net >= threshold
    cents = 0 if free_shipping else base
    return Adjustment("free-shipping", cents, cents == 0)


def tax_adjustment(net, order):
    basis_points = REGIONS[order.region][0]
    numerator = net * basis_points
    cents = round_half_up(numerator, 10000)
    return Adjustment("tax", cents, cents > 0)


def collect_applied(tier, coupon, shipping, tax):
    applied = []
    adjustments = (tier, coupon, shipping, tax)
    for adjustment in adjustments:
        if adjustment.active:
            applied.append(adjustment.name)
    return applied


def result_dict(quote):
    if not isinstance(quote, Quote):
        return {"error": quote[0], "index": quote[1]}
    return quote._asdict()
