from decimal import Decimal, ROUND_HALF_UP


_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _text(value):
    return format(value, ".2f")


def _line_error(number, message):
    raise ValueError(f"line {number}: {message}")


def _check_field_count(fields, number):
    if len(fields) != 3:
        _line_error(number, "expected three fields")


def _valid_membership(member):
    return member in ("none", "basic", "plus")


def _check_membership(member, number):
    if not _valid_membership(member):
        _line_error(number, "invalid membership")


def _parse_integer(value, label, number):
    try:
        result = int(value)
    except (TypeError, ValueError):
        _line_error(number, f"invalid {label}")
    if not value.isdecimal() or result < 1:
        _line_error(number, f"invalid {label}")
    return result


def _check_day_range(days, number):
    if days > 21:
        _line_error(number, "days must be 1-21")


def _parse_record(raw, number):
    fields = [part.strip() for part in raw.split(",")]
    _check_field_count(fields, number)
    member = fields[0]
    _check_membership(member, number)
    days = _parse_integer(fields[1], "days", number)
    quantity = _parse_integer(fields[2], "quantity", number)
    _check_day_range(days, number)
    return number, member, days, quantity


def _is_text(text):
    return isinstance(text, str)


def _check_text(text):
    if not _is_text(text):
        raise ValueError("input must be text")


def _nonblank(raw):
    return bool(raw.strip())


def _records(text):
    _check_text(text)
    return [_parse_record(raw, number) for number, raw in enumerate(text.splitlines(), 1)
            if _nonblank(raw)]


def _tier(days):
    if days <= 7:
        return Decimal("1.00")
    if days <= 14:
        return Decimal("1.75")
    return Decimal("2.50")


def _fine_day(day):
    return Decimal("0.25") if day <= 14 else Decimal("0.50")


def _fine_days(days):
    return range(8, days + 1)


def _fine(days):
    return sum((_fine_day(day) for day in _fine_days(days)), _ZERO)


def _rate(member):
    return {"none": Decimal("0"), "basic": Decimal("0.10"),
            "plus": Decimal("0.20")}[member]


def _fees(days, quantity):
    return _tier(days) * quantity


def _late_fines(days, quantity):
    return _fine(days) * quantity


def _gross(fees, late):
    return fees + late


def _discounted_charge(gross, member):
    return _money(gross * (Decimal("1") - _rate(member)))


def _row_discount(gross, charge):
    return gross - charge


def _row(member, days, quantity):
    fees = _fees(days, quantity)
    late = _late_fines(days, quantity)
    gross = _gross(fees, late)
    charge = _discounted_charge(gross, member)
    discount = _row_discount(gross, charge)
    return {"fees": fees, "late_fines": late, "discount": discount, "charge": charge}


def _empty_totals():
    keys = ("fees", "late_fines", "discount", "taxable", "tax", "total")
    return {key: _ZERO for key in keys}


def _zero_if_empty(records):
    if not records:
        return _empty_totals()
    return None


def _add_row(totals, row):
    totals["fees"] += row["fees"]
    totals["late_fines"] += row["late_fines"]
    totals["discount"] += row["discount"]
    totals["net"] += row["charge"]


def _sum_rows(records):
    totals = {"fees": _ZERO, "late_fines": _ZERO, "discount": _ZERO, "net": _ZERO}
    for _, member, days, quantity in records:
        _add_row(totals, _row(member, days, quantity))
    return totals


def _taxable(net):
    return max(_ZERO, net - Decimal("2.00"))


def _tax(taxable):
    return _money(taxable * Decimal("0.08"))


def _round_totals(totals, taxable, tax):
    return {"fees": _money(totals["fees"]),
            "late_fines": _money(totals["late_fines"]),
            "discount": _money(totals["discount"]),
            "taxable": _money(taxable), "tax": tax,
            "total": _money(totals["net"] + tax)}


def _calculated_totals(records):
    totals = _sum_rows(records)
    taxable = _taxable(totals["net"])
    return _round_totals(totals, taxable, _tax(taxable))


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    records = _records(text)
    empty = _zero_if_empty(records)
    return empty if empty is not None else _calculated_totals(records)


def _line_text(number, row):
    return (f"Line {number}: fees ${_text(row['fees'])}, late ${_text(row['late_fines'])}, "
            f"discount ${_text(row['discount'])}")


def _record_line(record):
    number, member, days, quantity = record
    return _line_text(number, _row(member, days, quantity))


def _detail_rows(records):
    return [_record_line(record) for record in records]


def _total_line(totals):
    return f"TOTAL ${_text(totals['total'])} (tax ${_text(totals['tax'])})"


def _receipt_lines(records, totals):
    return _detail_rows(records) + [_total_line(totals)]


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    records = _records(text)
    totals = price_loans(text)
    return "\n".join(_receipt_lines(records, totals))
