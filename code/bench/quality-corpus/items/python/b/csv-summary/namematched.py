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
    checked = valid_rows(rows)
    return summary_lines(ordered_totals(grouped_totals(rows))) if checked else INVALID


def summary_lines(items):
    return [product_summary(name, entry) for name, entry in items]


def product_summary(name, entry):
    rounded = entry[REVENUE].quantize(CENTS, rounding=ROUND_HALF_UP)
    return {PRODUCT: name, **entry, REVENUE: float(rounded)}


def ordered_totals(totals):
    return sorted(totals.items())


def grouped_totals(rows):
    return {name: product_counts(name, rows) for name in seen_names(rows)}


def seen_names(rows):
    return {row[PRODUCT] for row in rows}


def product_counts(name, rows):
    return {QUANTITY: quantity_count(name, rows), REVENUE: revenue_count(name, rows)}


def quantity_count(name, rows):
    return sum(row[QUANTITY] for row in rows if row[PRODUCT] == name)


def revenue_count(name, rows):
    return sum(exact_revenue(row) for row in rows if row[PRODUCT] == name)


def exact_revenue(row):
    unit = row[PRICE]
    return (unit if type(unit) is Decimal else Decimal(str(unit))) * row[QUANTITY]


def valid_rows(rows):
    return isinstance(rows, list) and all(sane_row(row) for row in rows)


def sane_row(row):
    return isinstance(row, dict) and name_ok(row) and quantity_ok(row) and price_ok(row)


def name_ok(row):
    name = row.get(PRODUCT)
    return isinstance(name, str) and name != "" and name.isascii()


def quantity_ok(row):
    quantity = row.get(QUANTITY)
    return type(quantity) is int and quantity >= 1


def price_ok(row):
    return price_value_ok(row.get(PRICE))


def price_value_ok(price):
    price_type = type(price)
    return price_type in MONEY and MONEY_FINITE[price_type](price) and price >= 0
