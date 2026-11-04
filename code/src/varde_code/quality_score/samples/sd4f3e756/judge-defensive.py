from decimal import Decimal, ROUND_HALF_UP


# Keep monetary constants exact so all calculations stay in Decimal arithmetic.
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value):
    # Reject unexpected values before applying the required cent rounding.
    if not isinstance(value, Decimal):
        raise TypeError("money value must be Decimal")
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _text(value):
    # Format only Decimal currency values as two-place strings.
    if not isinstance(value, Decimal):
        raise TypeError("formatted value must be Decimal")
    return format(value, ".2f")


def _header(parts, number):
    # Ensure a parsed row has exactly the three required columns.
    if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
        raise TypeError("fields must be a list of strings")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise TypeError("line number must be a positive integer")
    if len(parts) != 3:
        raise ValueError(f"line {number}: expected three fields")


def _integer(value, label, number):
    # Validate the parser inputs before converting a base-10 positive integer.
    if not isinstance(value, str):
        raise TypeError("integer value must be text")
    if not isinstance(label, str) or not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise TypeError("invalid integer field context")
    # Normalize conversion failures to the public line-specific validation error.
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"line {number}: invalid {label}") from None
    # Reject signs, decimals, zero, and other non-positive/non-decimal values.
    if not value.isdecimal() or result < 1:
        raise ValueError(f"line {number}: invalid {label}")
    return result


def _tier(days):
    # Accept only valid integer loan periods before selecting a fee band.
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 21:
        raise ValueError("days must be 1-21")
    # Return the fixed per-item loan fee for the applicable period.
    if days <= 7:
        return Decimal("1.00")
    if days <= 14:
        return Decimal("1.75")
    return Decimal("2.50")


def _fine(days):
    # Reject invalid days before calculating marginal late charges.
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 21:
        raise ValueError("days must be 1-21")
    # Add the per-day charge only for days after the first seven.
    total = _ZERO
    for day in range(8, days + 1):
        if day <= 14:
            total += Decimal("0.25")
        else:
            total += Decimal("0.50")
    return total


def _rate(member):
    # Require one of the supported membership names before lookup.
    if not isinstance(member, str):
        raise TypeError("membership must be text")
    if member not in ("none", "basic", "plus"):
        raise ValueError("invalid membership")
    # Map each membership to its discount fraction.
    return {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}[member]


def _row(member, days, quantity):
    # Validate the quantity before multiplying any per-item amounts.
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ValueError("quantity must be a positive integer")
    # Calculate fees, fines, and the rounded discounted charge for one record.
    fees = _tier(days) * quantity
    late = _fine(days) * quantity
    rate = _rate(member)
    charge = _money((fees + late) * (Decimal("1") - rate))
    discount = fees + late - charge
    return {"fees": fees, "late_fines": late, "discount": discount, "charge": charge}


def _records(text):
    # Require textual input so physical lines can be reported consistently.
    if not isinstance(text, str):
        raise ValueError("input must be text")
    # Parse each nonblank physical line and validate all of its fields.
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
    # Require a Decimal total before applying the tax-free fee allowance.
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be Decimal")
    # Tax only the amount above the two-dollar cap and round to cents.
    taxable = max(_ZERO, amount - Decimal("2.00"))
    return taxable, _money(taxable * Decimal("0.08"))


def _blank_totals():
    # Supply the complete public result shape for empty input.
    return {"fees": _ZERO, "late_fines": _ZERO, "discount": _ZERO,
            "taxable": _ZERO, "tax": _ZERO, "total": _ZERO}


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    # Parse once so validation completes before any totals are returned.
    records = _records(text)
    if not records:
        return _blank_totals()
    # Accumulate each record's itemized amounts and discounted charge.
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
    # Compute tax from the net charge and return cent-rounded totals.
    taxable, tax = _tax(net)
    total = net + tax
    return {"fees": _money(fees), "late_fines": _money(late),
            "discount": _money(discount), "taxable": _money(taxable),
            "tax": tax, "total": _money(total)}


def _line_text(number, row):
    # Validate row fields before producing a receipt detail line.
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise TypeError("line number must be a positive integer")
    if not isinstance(row, dict) or not all(isinstance(row.get(key), Decimal) for key in ("fees", "late_fines", "discount")):
        raise TypeError("row must contain Decimal amounts")
    # Render the three monetary components in the receipt's fixed format.
    return (f"Line {number}: fees ${_text(row['fees'])}, late ${_text(row['late_fines'])}, "
            f"discount ${_text(row['discount'])}")


def _detail_rows(records):
    # Ensure records are iterable before rendering their details.
    if not isinstance(records, (list, tuple)):
        raise TypeError("records must be a list or tuple")
    # Preserve input order and physical line numbers in the receipt output.
    output = []
    for number, member, days, quantity in records:
        output.append(_line_text(number, _row(member, days, quantity)))
    return output


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    # Validate input and handle the empty case using the same parser as totals.
    records = _records(text)
    if not records:
        return "TOTAL $0.00 (tax $0.00)"
    # Build detail rows and append the aggregate total and tax line.
    totals = price_loans(text)
    lines = _detail_rows(records)
    lines.append(f"TOTAL ${_text(totals['total'])} (tax ${_text(totals['tax'])})")
    return "\n".join(lines)
