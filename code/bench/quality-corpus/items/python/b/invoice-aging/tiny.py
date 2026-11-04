"""Build an invoice aging report with each bucket, fee, and total."""

from bisect import bisect_right
from decimal import ROUND_HALF_UP, Decimal
from operator import itemgetter

BOUNDS = (1, 31, 61, 91)
NAMES = ("current", "1-30", "31-60", "61-90", "over-90")
RATES = {
    "current": Decimal("0"),
    "1-30": Decimal("0.02"),
    "31-60": Decimal("0.05"),
    "61-90": Decimal("0.08"),
    "over-90": Decimal("0.10"),
}
CENTS = Decimal("0.01")
LIMIT = 1_000_000
ERROR = "invalid invoice"
KINDS = (int, float, Decimal)
ID = "id"
DAYS = "days_overdue"
BALANCE = "balance"
BUCKET = "bucket"
FEE = "fee"


def solution(invoices: list) -> dict:
    items = invoices if all_ok(invoices) else fail()
    return {"invoices": rows_of(items), "totals": totals_of(items)}


def all_ok(invoices):
    listed = isinstance(invoices, list)
    return listed and all(item_ok(item) for item in invoices)


def item_ok(item):
    shaped = isinstance(item, dict) and isinstance(item.get(DAYS), int)
    return shaped and id_ok(item) and amt_ok(item)


def id_ok(item):
    value = item.get(ID)
    return isinstance(value, str) and value and value.isascii()


def amt_ok(item):
    value = item.get(BALANCE)
    return type_ok(value) and in_range(value)


def type_ok(value):
    return not isinstance(value, bool) and isinstance(value, KINDS)


def in_range(value):
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.is_finite() and 0 <= amount <= LIMIT


def fail():
    raise ValueError(ERROR)


def rows_of(invoices):
    return [row_for(item) for item in sorted(invoices, key=itemgetter(ID))]


def row_for(item):
    return {ID: item[ID], BUCKET: bucket_of(item), FEE: fee_for(item)}


def bucket_of(invoice):
    return place_of(invoice[DAYS])


def place_of(days):
    return NAMES[bisect_right(BOUNDS, days)]


def fee_for(invoice):
    place = place_of(invoice[DAYS])
    return money(amount_of(invoice) * RATES[place])


def amount_of(invoice):
    balance = invoice[BALANCE]
    return balance if isinstance(balance, Decimal) else Decimal(str(balance))


def money(value):
    return float(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def totals_of(invoices):
    return {name: total_for(invoices, name) for name in NAMES}


def total_for(invoices, name):
    return money(sum(amounts_in(invoices, name), Decimal(0)))


def amounts_in(invoices, name):
    return [amount_of(item) for item in invoices if place_of(item[DAYS]) == name]
