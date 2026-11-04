"""Summarize valid sales rows by product with quantity and revenue totals."""

from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

CENTS = Decimal("0.01")
MONEY_TYPES = (int, float, Decimal)
MONEY_FINITE = {int: lambda value: True, float: isfinite, Decimal: Decimal.is_finite}
INVALID = {"error": "invalid_row"}


def solution(rows: list) -> list | dict:
    if not isinstance(rows, list):
        return INVALID
    for row in rows:
        if not isinstance(row, dict):
            return INVALID
        if "product" not in row:
            return INVALID
        if "quantity" not in row:
            return INVALID
        if "unit_price" not in row:
            return INVALID
        product = row["product"]
        if not isinstance(product, str):
            return INVALID
        if product == "":
            return INVALID
        if not product.isascii():
            return INVALID
        quantity = row["quantity"]
        if type(quantity) is not int:
            return INVALID
        if quantity < 1:
            return INVALID
        price = row["unit_price"]
        price_type = type(price)
        if price_type not in MONEY_TYPES:
            return INVALID
        if not MONEY_FINITE[price_type](price):
            return INVALID
        if price < 0:
            return INVALID
    totals = {}
    for row in rows:
        product = row["product"]
        quantity = row["quantity"]
        price = row["unit_price"]
        amount = price if type(price) is Decimal else Decimal(str(price))
        counts = totals.setdefault(product, {"quantity": 0, "revenue": Decimal()})
        running_quantity = counts["quantity"]
        running_revenue = counts["revenue"]
        counts["quantity"] = running_quantity + quantity
        counts["revenue"] = running_revenue + amount * quantity
    summary = []
    for product in sorted(totals):
        counts = totals[product]
        revenue = counts["revenue"].quantize(CENTS, rounding=ROUND_HALF_UP)
        entry = {
            "product": product,
            "quantity": counts["quantity"],
            "revenue": float(revenue),
        }
        summary.append(entry)
    return summary
