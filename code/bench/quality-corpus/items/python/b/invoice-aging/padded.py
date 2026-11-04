"""Build an invoice aging report with each bucket, fee, and total."""

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
    items = invoices if all_invoices_valid(invoices) else reject_invalid(invoices)
    return {"invoices": invoice_rows(items), "totals": bucket_totals(items)}


def all_invoices_valid(invoices: list) -> bool:
    if not isinstance(invoices, list):
        return False
    for invoice in invoices:
        if not invoice_valid(invoice):
            return False
    return True


def invoice_valid(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if not id_valid(item):
        return False
    if not balance_valid(item):
        return False
    return isinstance(item.get(DAYS), int)


def id_valid(item: dict) -> bool:
    value = item.get(ID)
    if not isinstance(value, str):
        return False
    if value == "":
        return False
    return value.isascii()


def balance_valid(item: dict) -> bool:
    value = item.get(BALANCE)
    if not number_accepted(value):
        return False
    return amount_within_limit(value)


def number_accepted(value) -> bool:
    flagged = isinstance(value, bool)
    if flagged:
        return False
    allowed = isinstance(value, KINDS)
    return allowed


def amount_within_limit(value) -> bool:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        return False
    below = 0 <= amount
    above = amount <= LIMIT
    return below and above


def reject_invalid(invoices: list) -> None:
    if not isinstance(invoices, list):
        raise ValueError(ERROR)
    for invoice in invoices:
        if not isinstance(invoice, dict):
            raise ValueError(ERROR)
    raise ValueError(ERROR)


def invoice_rows(invoices: list) -> list:
    ordered = sorted(invoices, key=itemgetter(ID))
    rows = []
    for invoice in ordered:
        rows.append(invoice_row(invoice))
    return rows


def invoice_row(invoice: dict) -> dict:
    bucket = aging_bucket(invoice)
    fee = aging_fee(invoice)
    row = {ID: invoice[ID], BUCKET: bucket, FEE: fee}
    return row


def aging_bucket(invoice: dict) -> str:
    days = invoice[DAYS]
    position = bucket_index(days)
    name = NAMES[position]
    return name


def bucket_index(days: int) -> int:
    position = 0
    for limit in BOUNDS:
        if days >= limit:
            position = position + 1
    return position


def aging_fee(invoice: dict) -> float:
    days = invoice[DAYS]
    position = bucket_index(days)
    bucket = NAMES[position]
    rate = RATES[bucket]
    amount = exact_balance(invoice)
    product = amount * rate
    return rounded_amount(product)


def exact_balance(invoice: dict) -> Decimal:
    balance = invoice[BALANCE]
    if isinstance(balance, Decimal):
        return balance
    return Decimal(str(balance))


def rounded_amount(value: Decimal) -> float:
    rounded = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    amount = float(rounded)
    return amount


def bucket_totals(invoices: list) -> dict:
    collected = {}
    for name in NAMES:
        amount = bucket_total(invoices, name)
        collected[name] = amount
    return collected


def bucket_total(invoices: list, name: str) -> float:
    amounts = balances_in(invoices, name)
    total = sum(amounts, Decimal(0))
    return rounded_amount(total)


def balances_in(invoices: list, name: str) -> list:
    amounts = []
    for invoice in invoices:
        position = bucket_index(invoice[DAYS])
        if NAMES[position] == name:
            amounts.append(exact_balance(invoice))
    return amounts
