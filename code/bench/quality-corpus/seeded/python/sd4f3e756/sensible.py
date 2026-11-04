from decimal import Decimal, ROUND_HALF_UP


_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _text(value):
    return format(value, ".2f")


def _line_error(number, message):
    raise ValueError(f"line {number}: {message}")


def _integer(value, label, number):
    try:
        result = int(value)
    except (TypeError, ValueError):
        _line_error(number, f"invalid {label}")
    if not value.isdecimal() or result < 1:
        _line_error(number, f"invalid {label}")
    return result


def _records(text):
    if not isinstance(text, str):
        raise ValueError("input must be text")
    records = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [part.strip() for part in raw.split(",")]
        if len(fields) != 3:
            _line_error(number, "expected three fields")
        member = fields[0]
        if member not in ("none", "basic", "plus"):
            _line_error(number, "invalid membership")
        days = _integer(fields[1], "days", number)
        quantity = _integer(fields[2], "quantity", number)
        if days > 21:
            _line_error(number, "days must be 1-21")
        records.append((number, member, days, quantity))
    return records


def _tier(days):
    if days <= 7:
        return Decimal("1.00")
    if days <= 14:
        return Decimal("1.75")
    return Decimal("2.50")


def _fine(days):
    total = _ZERO
    for day in range(8, days + 1):
        total += Decimal("0.25") if day <= 14 else Decimal("0.50")
    return total


def _row(member, days, quantity):
    fees = _tier(days) * quantity
    late = _fine(days) * quantity
    rate = {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}[member]
    charge = _money((fees + late) * (Decimal("1") - rate))
    return {"fees": fees, "late_fines": late,
            "discount": fees + late - charge, "charge": charge}


def _empty_totals():
    return {key: _ZERO for key in ("fees", "late_fines", "discount", "taxable", "tax", "total")}


def _price_records(records):
    if not records:
        return _empty_totals()
    fees = late = discount = net = _ZERO
    for _, member, days, quantity in records:
        row = _row(member, days, quantity)
        fees += row["fees"]
        late += row["late_fines"]
        discount += row["discount"]
        net += row["charge"]
    taxable = max(_ZERO, net - Decimal("2.00"))
    tax = _money(taxable * Decimal("0.08"))
    return {"fees": _money(fees), "late_fines": _money(late),
            "discount": _money(discount), "taxable": _money(taxable),
            "tax": tax, "total": _money(net + tax)}


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    return _price_records(_records(text))


def _line_text(number, row):
    return (f"Line {number}: fees ${_text(row['fees'])}, late ${_text(row['late_fines'])}, "
            f"discount ${_text(row['discount'])}")


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    records = _records(text)
    if not records:
        return "TOTAL $0.00 (tax $0.00)"
    lines = [_line_text(number, _row(member, days, quantity))
             for number, member, days, quantity in records]
    totals = _price_records(records)
    lines.append(f"TOTAL ${_text(totals['total'])} (tax ${_text(totals['tax'])})")
    return "\n".join(lines)
