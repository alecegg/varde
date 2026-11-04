from decimal import Decimal, ROUND_HALF_UP


_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _text(value):
    return format(value, ".2f")


def _header(parts, number):
    if len(parts) != 3:
        raise ValueError(f"line {number}: expected three fields")


def _integer(value, label, number):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"line {number}: invalid {label}") from None
    if not value.isdecimal() or result < 1:
        raise ValueError(f"line {number}: invalid {label}")
    return result


def _tier(days):
    if days <= 7:
        return Decimal("1.00")
    if days <= 14:
        return Decimal("1.75")
    return Decimal("2.50")


def _fine(days):
    total = _ZERO
    for day in range(8, days + 1):
        if day <= 14:
            total += Decimal("0.25")
        else:
            total += Decimal("0.50")
    return total


def _rate(member):
    return {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}[member]


def _row(member, days, quantity):
    fees = _tier(days) * quantity
    late = _fine(days) * quantity
    rate = _rate(member)
    charge = _money((fees + late) * (Decimal("1") - rate))
    discount = fees + late - charge
    return {"fees": fees, "late_fines": late, "discount": discount, "charge": charge}


def _records(text):
    if not isinstance(text, str):
        raise ValueError("input must be text")
    records = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [part.strip() for part in raw.split(",")]
        _header(fields, line_number)
        member = fields[0]
        if member not in ("none", "basic", "plus"):
            raise ValueError(f"line {line_number}: invalid membership")
        days = _integer(fields[1], "days", line_number)
        quantity = _integer(fields[2], "quantity", line_number)
        if days > 21:
            raise ValueError(f"line {line_number}: days must be 1-21")
        records.append((line_number, member, days, quantity))
    return records


def _tax(amount):
    taxable = max(_ZERO, amount - Decimal("2.00"))
    return taxable, _money(taxable * Decimal("0.08"))


def _blank_totals():
    return {"fees": _ZERO, "late_fines": _ZERO, "discount": _ZERO,
            "taxable": _ZERO, "tax": _ZERO, "total": _ZERO}


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    records = _records(text)
    if not records:
        return _blank_totals()
    fees = _ZERO
    late = _ZERO
    discount = _ZERO
    net = _ZERO
    for _, member, days, quantity in records:
        row = _row(member, days, quantity)
        fees += row["fees"]
        late += row["late_fines"]
        discount += row["discount"]
        net += row["charge"]
    taxable, tax = _tax(net)
    total = net + tax
    return {"fees": _money(fees), "late_fines": _money(late),
            "discount": _money(discount), "taxable": _money(taxable),
            "tax": tax, "total": _money(total)}


def _line_text(number, row):
    return (f"Line {number}: fees ${_text(row['fees'])}, late ${_text(row['late_fines'])}, "
            f"discount ${_text(row['discount'])}")


def _detail_rows(records):
    output = []
    for number, member, days, quantity in records:
        output.append(_line_text(number, _row(member, days, quantity)))
    return output


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    records = _records(text)
    if not records:
        return "TOTAL $0.00 (tax $0.00)"
    totals = price_loans(text)
    lines = _detail_rows(records)
    lines.append(f"TOTAL ${_text(totals['total'])} (tax ${_text(totals['tax'])})")
    return "\n".join(lines)
