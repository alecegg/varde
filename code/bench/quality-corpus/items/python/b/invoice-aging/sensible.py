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
    if not invoices_are_valid(invoices):
        raise ValueError(ERROR)
    if not fields_are_valid(invoices):
        raise ValueError(ERROR)
    if not amounts_are_valid(invoices):
        raise ValueError(ERROR)
    ordered = sorted(invoices, key=itemgetter(ID))
    return {"invoices": invoice_rows(ordered), "totals": bucket_totals(ordered)}


def invoices_are_valid(invoices):
    if not isinstance(invoices, list):
        return False
    for invoice in invoices:
        if not isinstance(invoice, dict):
            return False
    return True


def fields_are_valid(invoices):
    for invoice in invoices:
        invoice_id = invoice.get(ID)
        if not (isinstance(invoice_id, str) and invoice_id.isascii() and invoice_id):
            return False
        if not isinstance(invoice.get(DAYS), int):
            return False
    return True


def amounts_are_valid(invoices):
    for invoice in invoices:
        balance = invoice.get(BALANCE)
        if isinstance(balance, bool) or not isinstance(balance, KINDS):
            return False
        amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
        if not amount.is_finite() or not 0 <= amount <= LIMIT:
            return False
    return True


def invoice_rows(invoices):
    rows = []
    for invoice in invoices:
        place = NAMES[bisect_right(BOUNDS, invoice[DAYS])]
        balance = invoice[BALANCE]
        amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
        fee = float((amount * RATES[place]).quantize(CENTS, rounding=ROUND_HALF_UP))
        rows.append({ID: invoice[ID], BUCKET: place, FEE: fee})
    return rows


def bucket_totals(invoices):
    totals = {}
    for name in NAMES:
        running = Decimal(0)
        for invoice in invoices:
            place = NAMES[bisect_right(BOUNDS, invoice[DAYS])]
            if place != name:
                continue
            given = invoice[BALANCE]
            amount = given if isinstance(given, Decimal) else Decimal(str(given))
            running = running + amount
        totals[name] = float(running.quantize(CENTS, rounding=ROUND_HALF_UP))
    return totals
