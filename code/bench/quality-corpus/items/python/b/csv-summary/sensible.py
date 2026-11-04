"""Summarize valid sales rows by product with quantity and revenue totals."""

from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

CENTS = Decimal("0.01")
MONEY_TYPES = (int, float, Decimal)
MONEY_FINITE = {int: lambda value: True, float: isfinite, Decimal: Decimal.is_finite}
INVALID = {"error": "invalid_row"}


def solution(rows: list) -> list | dict:
    if not names_are_well_formed(rows) or not values_are_well_formed(rows):
        return INVALID
    return summary_rows(totals_of(rows))


def names_are_well_formed(rows: list) -> bool:
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        name = row.get("product")
        if not isinstance(name, str) or not name or not name.isascii():
            return False
    return True


def values_are_well_formed(rows: list) -> bool:
    for row in rows:
        quantity = row.get("quantity")
        if type(quantity) is not int or quantity < 1:
            return False
        price = row.get("unit_price")
        if type(price) not in MONEY_TYPES or not MONEY_FINITE[type(price)](price):
            return False
        if price < 0:
            return False
    return True


def totals_of(rows: list) -> dict:
    totals = {}
    for row in rows:
        name = row["product"]
        qty = row["quantity"]
        count, total = totals.get(name, (0, Decimal()))
        unit = row["unit_price"]
        if type(unit) is not Decimal:
            unit = Decimal(str(unit))
        totals[name] = (count + qty, total + unit * qty)
    return totals


def summary_rows(totals: dict) -> list:
    rows = []
    for name in sorted(totals):
        quantity, revenue = totals[name]
        amount = revenue.quantize(CENTS, rounding=ROUND_HALF_UP)
        rows.append({"product": name, "quantity": quantity, "revenue": float(amount)})
    return rows
