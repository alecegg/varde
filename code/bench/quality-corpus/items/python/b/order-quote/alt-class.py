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
    this = Quote(request)
    error = this.check_items()
    if error:
        return error
    error = this.combine_items()
    if error:
        return error
    error = this.check_options()
    if error:
        return error
    return this.build_result()


class Quote:
    def __init__(self, request):
        self.rows = [
            (row["sku"].strip().upper(), row["qty"], row["price"])
            for row in request["items"]
        ]
        self.tier = request["tier"].strip().lower()
        self.coupon = request["coupon"].strip().upper()
        self.region = request["region"].strip().upper()
        self.merged = {}

    def check_items(self):
        if not self.rows or len(self.rows) > 50:
            return {
                "error": "EMPTY_ORDER" if not self.rows else "TOO_MANY_ITEMS",
                "index": None,
            }
        for index, row in enumerate(self.rows):
            checked, error = self.check_item(row, index)
            if error:
                return error
            self.rows[index] = checked
        return None

    def check_item(self, row, index):
        if not SKU.fullmatch(row[0]):
            return None, {"error": "BAD_SKU", "index": index}
        if type(row[1]) is not int or not 1 <= row[1] <= 1000:
            return None, {"error": "BAD_QTY", "index": index}
        cents = self.price_cents(row[2])
        if cents is None:
            return None, {"error": "BAD_PRICE", "index": index}
        return (row[0], row[1], cents), None

    def price_cents(self, value):
        if not isinstance(value, str) or not PRICE.fullmatch(value):
            return None
        whole, dot, fraction = value.partition(".")
        cents = int(whole) * 100 + int((fraction if dot else "").ljust(2, "0"))
        return cents if cents else None

    def combine_items(self):
        for index, (sku, qty, cents) in enumerate(self.rows):
            prior = self.merged.get(sku)
            if prior and prior[1] != cents:
                return {"error": "PRICE_CONFLICT", "index": index}
            total_qty = qty + (prior[0] if prior else 0)
            if total_qty > 1000:
                return {"error": "BAD_QTY", "index": index}
            self.merged[sku] = total_qty, cents
        return None

    def check_options(self):
        if self.tier not in TIER_BP:
            return {"error": "BAD_TIER", "index": None}
        if self.coupon and not COUPON.fullmatch(self.coupon):
            return {"error": "BAD_COUPON", "index": None}
        if self.region not in REGIONS:
            return {"error": "BAD_REGION", "index": None}
        return None

    def discount(self, amount):
        if self.coupon.startswith("PCT"):
            return (2 * amount * int(self.coupon[3:]) + 100) // 200
        if self.coupon.startswith("FIXED"):
            return min(int(self.coupon[5:]) * 100, amount)
        return 0

    def build_result(self):
        lines = self.make_lines()
        subtotal = sum(row["line_cents"] for row in lines)
        tier_discount = (2 * subtotal * TIER_BP[self.tier] + 10000) // 20000
        coupon_discount = self.discount(subtotal - tier_discount)
        net = subtotal - tier_discount - coupon_discount
        shipping, tax = self.delivery_costs(net)
        return self.result_fields(
            lines, subtotal, tier_discount, coupon_discount, net, shipping, tax
        )

    def make_lines(self):
        return [
            {"sku": sku, "qty": qty, "unit_cents": cents, "line_cents": qty * cents}
            for sku, (qty, cents) in sorted(self.merged.items())
        ]

    def delivery_costs(self, net):
        tax_rate, base_shipping, threshold = REGIONS[self.region]
        shipping = 0 if self.coupon == "FREESHIP" or net >= threshold else base_shipping
        tax = (2 * net * tax_rate + 10000) // 20000
        return shipping, tax

    def result_fields(
        self, lines, subtotal, tier_discount, coupon_discount, net, shipping, tax
    ):
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
