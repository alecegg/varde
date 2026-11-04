"""Summarize valid sales rows by product with quantity and revenue totals."""

from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

CENTS = Decimal("0.01")
MONEY_TYPES = (int, float, Decimal)
MONEY_FINITE = {int: lambda value: True, float: isfinite, Decimal: Decimal.is_finite}
ERROR = {"error": "invalid_row"}


def solution(rows: list) -> list | dict:
    rows_is_list = isinstance(rows, list)
    if not rows_is_list:
        return ERROR
    for row in rows:
        row_is_mapping = isinstance(row, dict)
        if not row_is_mapping:
            return ERROR
        has_product = "product" in row
        if not has_product:
            return ERROR
        has_quantity = "quantity" in row
        if not has_quantity:
            return ERROR
        has_price = "unit_price" in row
        if not has_price:
            return ERROR
    for row in rows:
        product = row["product"]
        name_is_text = isinstance(product, str)
        if not name_is_text:
            return ERROR
        name_is_empty = product == ""
        if name_is_empty:
            return ERROR
        name_is_ascii = product.isascii()
        if not name_is_ascii:
            return ERROR
        quantity = row["quantity"]
        quantity_type = type(quantity)
        quantity_is_integer = quantity_type is int
        if not quantity_is_integer:
            return ERROR
        quantity_is_positive = quantity >= 1
        if not quantity_is_positive:
            return ERROR
        price = row["unit_price"]
        price_type = type(price)
        price_is_money = price_type in MONEY_TYPES
        if not price_is_money:
            return ERROR
        price_is_finite = MONEY_FINITE[price_type](price)
        if not price_is_finite:
            return ERROR
        price_is_positive = price >= 0
        if not price_is_positive:
            return ERROR
    groups = {}
    for row in rows:
        product = row["product"]
        quantity = row["quantity"]
        unit = row["unit_price"]
        unit_is_exact = type(unit) is Decimal
        if unit_is_exact:
            line_revenue = unit * quantity
        else:
            line_revenue = Decimal(str(unit)) * quantity
        product_is_known = product in groups
        if not product_is_known:
            groups[product] = []
        rows_for_product = groups[product]
        rows_for_product.append((quantity, line_revenue))
    products = sorted(groups)
    quantities = {}
    for product in products:
        running_total = 0
        rows_for_product = groups[product]
        for quantity, _ in rows_for_product:
            running_total = running_total + quantity
        quantities[product] = running_total
    revenues = {}
    for product in products:
        running_total = Decimal()
        rows_for_product = groups[product]
        for _, line_revenue in rows_for_product:
            running_total = running_total + line_revenue
        revenues[product] = running_total
    rounded_revenue = {}
    for product in products:
        revenue = revenues[product]
        rounded = revenue.quantize(CENTS, rounding=ROUND_HALF_UP)
        amount = float(rounded)
        rounded_revenue[product] = amount
    summary = []
    for product in products:
        quantity = quantities[product]
        amount = rounded_revenue[product]
        entry = {}
        entry["product"] = product
        entry["quantity"] = quantity
        entry["revenue"] = amount
        summary.append(entry)
    return summary
