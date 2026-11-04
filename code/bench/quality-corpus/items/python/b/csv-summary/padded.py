"""Summarize valid sales rows by product with quantity and revenue totals."""

from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

CENTS = Decimal("0.01")
PRODUCT = "product"
QUANTITY = "quantity"
REVENUE = "revenue"
PRICE = "unit_price"
MONEY = (int, float, Decimal)
MONEY_FINITE = {int: lambda value: True, float: isfinite, Decimal: Decimal.is_finite}
INVALID = {"error": "invalid_row"}


def solution(rows: list) -> list | dict:
    if not validate(rows):
        return INVALID
    return render_lines(sorted_entries(grouped_totals(rows)))


def validate(rows: list) -> bool:
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not row_valid(row):
            return False
    return True


def row_valid(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if not name_is_valid(row):
        return False
    if not quantity_is_valid(row):
        return False
    return price_is_valid(row)


def name_is_valid(row: dict) -> bool:
    if PRODUCT not in row:
        return False
    name = row[PRODUCT]
    if not isinstance(name, str):
        return False
    if name == "":
        return False
    return name.isascii()


def quantity_is_valid(row: dict) -> bool:
    if QUANTITY not in row:
        return False
    quantity = row[QUANTITY]
    if type(quantity) is not int:
        return False
    return quantity >= 1


def price_is_valid(row: dict) -> bool:
    if PRICE not in row:
        return False
    price = row[PRICE]
    if type(price) not in MONEY:
        return False
    return price_is_acceptable(price)


def price_is_acceptable(price: int | float | Decimal) -> bool:
    price_type = type(price)
    return MONEY_FINITE[price_type](price) and price >= 0


def grouped_totals(rows: list) -> dict:
    names = product_names(rows)
    totals = {}
    for name in names:
        totals[name] = totals_for_product(name, rows)
    return totals


def product_names(rows: list) -> set:
    names = []
    for row in rows:
        name = row[PRODUCT]
        names.append(name)
    unique = set(names)
    return unique


def totals_for_product(name: str, items: list) -> dict:
    quantity = quantity_total(name, items)
    revenue = revenue_total(name, items)
    return {QUANTITY: quantity, REVENUE: revenue}


def quantity_total(name: str, items: list) -> int:
    total = 0
    for row in items:
        if row[PRODUCT] == name:
            total = total + row[QUANTITY]
    return total


def revenue_total(name: str, items: list) -> Decimal:
    total = Decimal(0)
    for row in items:
        if row[PRODUCT] == name:
            total = total + row_revenue(row)
    return total


def row_revenue(row: dict) -> Decimal:
    price = row[PRICE]
    amount = price if type(price) is Decimal else Decimal(str(price))
    quantity = row[QUANTITY]
    return amount * quantity


def sorted_entries(totals: dict) -> list:
    names = sorted(totals)
    entries = []
    for name in names:
        entry = totals[name]
        entries.append((name, entry))
    return entries


def render_lines(items: list) -> list:
    lines = []
    for name, entry in items:
        line = summary_line(name, entry)
        lines.append(line)
    return lines


def summary_line(name: str, entry: dict) -> dict:
    revenue = entry[REVENUE]
    rounded = revenue.quantize(CENTS, rounding=ROUND_HALF_UP)
    amount = float(rounded)
    quantity = entry[QUANTITY]
    return {PRODUCT: name, QUANTITY: quantity, REVENUE: amount}
