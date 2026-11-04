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
    items = invoices if all_invoices_valid(invoices) else reject_invalid()
    return {"invoices": invoice_rows(items), "totals": bucket_totals(items)}


def all_invoices_valid(invoices):
    listed = isinstance(invoices, list)
    return listed and all(invoice_valid(item) for item in invoices)


def invoice_valid(item):
    shaped = isinstance(item, dict) and isinstance(item.get(DAYS), int)
    return shaped and id_valid(item) and balance_valid(item)


def id_valid(item):
    value = item.get(ID)
    return isinstance(value, str) and value and value.isascii()


def balance_valid(item):
    value = item.get(BALANCE)
    return number_accepted(value) and amount_within_limit(value)


def number_accepted(value):
    return not isinstance(value, bool) and isinstance(value, KINDS)


def amount_within_limit(value):
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.is_finite() and 0 <= amount <= LIMIT


def reject_invalid():
    raise ValueError(ERROR)


def invoice_rows(invoices):
    return [invoice_row(item) for item in sorted(invoices, key=itemgetter(ID))]


def invoice_row(item):
    return {ID: item[ID], BUCKET: aging_bucket(item), FEE: aging_fee(item)}


def aging_bucket(invoice):
    return bucket_name(invoice[DAYS])


def bucket_name(days):
    return NAMES[bisect_right(BOUNDS, days)]


def aging_fee(invoice):
    place = bucket_name(invoice[DAYS])
    return rounded_amount(exact_balance(invoice) * RATES[place])


def exact_balance(invoice):
    balance = invoice[BALANCE]
    return balance if isinstance(balance, Decimal) else Decimal(str(balance))


def rounded_amount(value):
    return float(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def bucket_totals(invoices):
    return {name: bucket_total(invoices, name) for name in NAMES}


def bucket_total(invoices, name):
    return rounded_amount(sum(balances_in(invoices, name), Decimal(0)))


def balances_in(invoices, name):
    return [exact_balance(item) for item in invoices if bucket_name(item[DAYS]) == name]
