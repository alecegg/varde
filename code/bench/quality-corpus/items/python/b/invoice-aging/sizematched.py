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
    if not isinstance(invoices, list):
        raise ValueError(ERROR)
    for invoice in invoices:
        if not isinstance(invoice, dict):
            raise ValueError(ERROR)
        if ID not in invoice or DAYS not in invoice or BALANCE not in invoice:
            raise ValueError(ERROR)
        invoice_id = invoice.get(ID)
        typed_id = isinstance(invoice_id, str)
        if not typed_id:
            raise ValueError(ERROR)
        if not invoice_id:
            raise ValueError(ERROR)
        if not invoice_id.isascii():
            raise ValueError(ERROR)
        days = invoice.get(DAYS)
        counted = isinstance(days, int)
        if not counted:
            raise ValueError(ERROR)
        balance = invoice.get(BALANCE)
        flagged = isinstance(balance, bool)
        allowed = isinstance(balance, KINDS)
        if flagged or not allowed:
            raise ValueError(ERROR)
        amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
        if not amount.is_finite():
            raise ValueError(ERROR)
        if not 0 <= amount <= LIMIT:
            raise ValueError(ERROR)
    ordered = sorted(invoices, key=itemgetter(ID))
    rows = []
    for invoice in ordered:
        place = NAMES[bisect_right(BOUNDS, invoice[DAYS])]
        rate = RATES[place]
        given = invoice[BALANCE]
        amount = given if isinstance(given, Decimal) else Decimal(str(given))
        product = amount * rate
        cents = product.quantize(CENTS, rounding=ROUND_HALF_UP)
        rows.append({ID: invoice[ID], BUCKET: place, FEE: float(cents)})
    totals = {}
    for name in NAMES:
        amounts = []
        for invoice in ordered:
            place = NAMES[bisect_right(BOUNDS, invoice[DAYS])]
            if place != name:
                continue
            given = invoice[BALANCE]
            amount = given if isinstance(given, Decimal) else Decimal(str(given))
            amounts.append(amount)
        total = sum(amounts, Decimal(0))
        totals[name] = float(total.quantize(CENTS, rounding=ROUND_HALF_UP))
    return {"invoices": rows, "totals": totals}
