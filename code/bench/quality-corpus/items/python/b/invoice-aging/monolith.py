"""Build an invoice aging report with each bucket, fee, and total."""

from decimal import ROUND_HALF_UP, Decimal
from operator import itemgetter

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
        if not isinstance(invoice_id, str):
            raise ValueError(ERROR)
        if invoice_id == "":
            raise ValueError(ERROR)
        if not invoice_id.isascii():
            raise ValueError(ERROR)
        days = invoice.get(DAYS)
        if not isinstance(days, int):
            raise ValueError(ERROR)
        balance = invoice.get(BALANCE)
        if isinstance(balance, bool):
            raise ValueError(ERROR)
        if not isinstance(balance, KINDS):
            raise ValueError(ERROR)
        amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
        if not amount.is_finite():
            raise ValueError(ERROR)
        if amount < 0:
            raise ValueError(ERROR)
        if amount > LIMIT:
            raise ValueError(ERROR)

    ordered = sorted(invoices, key=itemgetter(ID))

    places = []
    for invoice in ordered:
        days = invoice[DAYS]
        if days <= 0:
            places.append("current")
        elif days <= 30:
            places.append("1-30")
        elif days <= 60:
            places.append("31-60")
        elif days <= 90:
            places.append("61-90")
        else:
            places.append("over-90")

    rates = []
    for invoice in ordered:
        days = invoice[DAYS]
        if days <= 0:
            rates.append(RATES["current"])
        elif days <= 30:
            rates.append(RATES["1-30"])
        elif days <= 60:
            rates.append(RATES["31-60"])
        elif days <= 90:
            rates.append(RATES["61-90"])
        else:
            rates.append(RATES["over-90"])

    rows = []
    for position, invoice in enumerate(ordered):
        place = places[position]
        balance = invoice[BALANCE]
        amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
        fee = amount * rates[position]
        cents = fee.quantize(CENTS, rounding=ROUND_HALF_UP)
        rounded = float(cents)
        rows.append({ID: invoice[ID], BUCKET: place, FEE: rounded})

    totals = {}
    for name in NAMES:
        amounts = []
        for invoice in ordered:
            days = invoice[DAYS]
            if days <= 0:
                place = "current"
            elif days <= 30:
                place = "1-30"
            elif days <= 60:
                place = "31-60"
            elif days <= 90:
                place = "61-90"
            else:
                place = "over-90"
            if place != name:
                continue
            balance = invoice[BALANCE]
            amount = balance if isinstance(balance, Decimal) else Decimal(str(balance))
            amounts.append(amount)
        running = Decimal(0)
        for amount in amounts:
            running = running + amount
        totals[name] = float(running.quantize(CENTS, rounding=ROUND_HALF_UP))

    report = {"invoices": rows, "totals": totals}
    return report
