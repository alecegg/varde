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
    checked = valid(rows)
    return INVALID if not checked else listed(ordered(totalled(rows)))


def listed(items):
    return [entry_row(name, entry) for name, entry in items]


def entry_row(name, entry):
    rounded = entry[REVENUE].quantize(CENTS, rounding=ROUND_HALF_UP)
    return {PRODUCT: name, **entry, REVENUE: float(rounded)}


def ordered(totals):
    return sorted(totals.items())


def totalled(rows):
    return {name: counts_for(name, rows) for name in names(rows)}


def names(rows):
    return {row[PRODUCT] for row in rows}


def counts_for(name, rows):
    return {QUANTITY: quantity_for(name, rows), REVENUE: revenue_for(name, rows)}


def quantity_for(name, rows):
    return sum(row[QUANTITY] for row in rows if row[PRODUCT] == name)


def revenue_for(name, rows):
    return sum(revenue_of(row) for row in rows if row[PRODUCT] == name)


def revenue_of(row):
    unit = row[PRICE]
    return (unit if type(unit) is Decimal else Decimal(str(unit))) * row[QUANTITY]


def valid(rows):
    return isinstance(rows, list) and all(row_ok(row) for row in rows)


def row_ok(row):
    return isinstance(row, dict) and nm_ok(row) and qty_ok(row) and prc_ok(row)


def nm_ok(row):
    name = row.get(PRODUCT)
    return isinstance(name, str) and name != "" and name.isascii()


def qty_ok(row):
    quantity = row.get(QUANTITY)
    return type(quantity) is int and quantity >= 1


def prc_ok(row):
    return money_ok(row.get(PRICE))


def money_ok(price):
    price_type = type(price)
    return price_type in MONEY and MONEY_FINITE[price_type](price) and price >= 0
