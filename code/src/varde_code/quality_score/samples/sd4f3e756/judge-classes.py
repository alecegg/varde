from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _text(value):
    return format(value, ".2f")


@dataclass(frozen=True)
class Loan:
    line: int
    membership: str
    days: int
    quantity: int


@dataclass(frozen=True)
class Charge:
    fees: Decimal
    late_fines: Decimal
    discount: Decimal
    amount: Decimal


class LoanParser:
    MEMBERSHIPS = ("none", "basic", "plus")

    def parse(self, text):
        if not isinstance(text, str):
            raise ValueError("input must be text")
        loans = []
        for number, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            fields = [part.strip() for part in raw.split(",")]
            if len(fields) != 3:
                raise ValueError(f"line {number}: expected three fields")
            membership = fields[0]
            if membership not in self.MEMBERSHIPS:
                raise ValueError(f"line {number}: invalid membership")
            days = self._integer(fields[1], "days", number)
            quantity = self._integer(fields[2], "quantity", number)
            if days > 21:
                raise ValueError(f"line {number}: days must be 1-21")
            loans.append(Loan(number, membership, days, quantity))
        return loans

    @staticmethod
    def _integer(value, label, number):
        try:
            result = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"line {number}: invalid {label}") from None
        if not value.isdecimal() or result < 1:
            raise ValueError(f"line {number}: invalid {label}")
        return result


class FeeSchedule:
    @staticmethod
    def loan_fee(days):
        if days <= 7:
            return Decimal("1.00")
        if days <= 14:
            return Decimal("1.75")
        return Decimal("2.50")

    @staticmethod
    def late_fine(days):
        total = _ZERO
        for day in range(8, days + 1):
            total += Decimal("0.25") if day <= 14 else Decimal("0.50")
        return total


class DiscountPolicy:
    RATES = {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}

    def charge(self, loan):
        fees = FeeSchedule.loan_fee(loan.days) * loan.quantity
        late = FeeSchedule.late_fine(loan.days) * loan.quantity
        amount = _money((fees + late) * (Decimal("1") - self.RATES[loan.membership]))
        return Charge(fees, late, fees + late - amount, amount)


@dataclass(frozen=True)
class Totals:
    fees: Decimal = _ZERO
    late_fines: Decimal = _ZERO
    discount: Decimal = _ZERO
    taxable: Decimal = _ZERO
    tax: Decimal = _ZERO
    total: Decimal = _ZERO

    def as_dict(self):
        return {"fees": self.fees, "late_fines": self.late_fines,
                "discount": self.discount, "taxable": self.taxable,
                "tax": self.tax, "total": self.total}


class LoanPricing:
    def __init__(self, parser=None, policy=None):
        self.parser = parser or LoanParser()
        self.policy = policy or DiscountPolicy()

    def price(self, text):
        loans = self.parser.parse(text)
        if not loans:
            return Totals().as_dict()
        charges = [self.policy.charge(loan) for loan in loans]
        fees = sum((charge.fees for charge in charges), _ZERO)
        late = sum((charge.late_fines for charge in charges), _ZERO)
        discount = sum((charge.discount for charge in charges), _ZERO)
        net = sum((charge.amount for charge in charges), _ZERO)
        taxable = max(_ZERO, net - Decimal("2.00"))
        tax = _money(taxable * Decimal("0.08"))
        return Totals(_money(fees), _money(late), _money(discount),
                      _money(taxable), tax, _money(net + tax)).as_dict()

    def receipt(self, text):
        loans = self.parser.parse(text)
        if not loans:
            return "TOTAL $0.00 (tax $0.00)"
        charges = [self.policy.charge(loan) for loan in loans]
        lines = [self._format_line(loan, charge) for loan, charge in zip(loans, charges)]
        totals = self.price(text)
        lines.append(f"TOTAL ${_text(totals['total'])} (tax ${_text(totals['tax'])})")
        return "\n".join(lines)

    @staticmethod
    def _format_line(loan, charge):
        return (f"Line {loan.line}: fees ${_text(charge.fees)}, late ${_text(charge.late_fines)}, "
                f"discount ${_text(charge.discount)}")


_pricing = LoanPricing()


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    return _pricing.price(text)


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    return _pricing.receipt(text)
