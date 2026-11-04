from decimal import Decimal, ROUND_HALF_UP


def price_loans(text):
    """Parse loan records and return the monetary totals as Decimals."""
    cent = Decimal("0.01")
    zero = Decimal("0.00")
    if not isinstance(text, str):
        raise ValueError("input must be text")

    fees = zero
    late_fines = zero
    discount = zero
    net = zero
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [part.strip() for part in raw.split(",")]
        if len(fields) != 3:
            raise ValueError(f"line {line_number}: expected three fields")
        member, day_text, quantity_text = fields
        if member not in ("none", "basic", "plus"):
            raise ValueError(f"line {line_number}: invalid membership")
        try:
            days = int(day_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid days") from None
        if not day_text.isdecimal() or days < 1:
            raise ValueError(f"line {line_number}: invalid days")
        try:
            quantity = int(quantity_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid quantity") from None
        if not quantity_text.isdecimal() or quantity < 1:
            raise ValueError(f"line {line_number}: invalid quantity")
        if days > 21:
            raise ValueError(f"line {line_number}: days must be 1-21")

        if days <= 7:
            fee_per_item = Decimal("1.00")
        elif days <= 14:
            fee_per_item = Decimal("1.75")
        else:
            fee_per_item = Decimal("2.50")
        fees += fee_per_item * quantity

        fine_per_item = zero
        for day in range(8, days + 1):
            if day <= 14:
                fine_per_item += Decimal("0.25")
            else:
                fine_per_item += Decimal("0.50")
        row_late = fine_per_item * quantity
        late_fines += row_late

        if member == "basic":
            rate = Decimal("0.10")
        elif member == "plus":
            rate = Decimal("0.20")
        else:
            rate = Decimal("0")
        gross = fee_per_item * quantity + row_late
        charge = (gross * (Decimal("1") - rate)).quantize(cent, rounding=ROUND_HALF_UP)
        discount += gross - charge
        net += charge

    taxable = max(zero, net - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(cent, rounding=ROUND_HALF_UP)
    total = net + tax
    return {
        "fees": fees.quantize(cent, rounding=ROUND_HALF_UP),
        "late_fines": late_fines.quantize(cent, rounding=ROUND_HALF_UP),
        "discount": discount.quantize(cent, rounding=ROUND_HALF_UP),
        "taxable": taxable.quantize(cent, rounding=ROUND_HALF_UP),
        "tax": tax,
        "total": total.quantize(cent, rounding=ROUND_HALF_UP),
    }


def receipt(text):
    """Return an itemized text receipt for the supplied loan records."""
    cent = Decimal("0.01")
    zero = Decimal("0.00")
    if not isinstance(text, str):
        raise ValueError("input must be text")

    lines = []
    net = zero
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        fields = [part.strip() for part in raw.split(",")]
        if len(fields) != 3:
            raise ValueError(f"line {line_number}: expected three fields")
        member, day_text, quantity_text = fields
        if member not in ("none", "basic", "plus"):
            raise ValueError(f"line {line_number}: invalid membership")
        try:
            days = int(day_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid days") from None
        if not day_text.isdecimal() or days < 1:
            raise ValueError(f"line {line_number}: invalid days")
        try:
            quantity = int(quantity_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid quantity") from None
        if not quantity_text.isdecimal() or quantity < 1:
            raise ValueError(f"line {line_number}: invalid quantity")
        if days > 21:
            raise ValueError(f"line {line_number}: days must be 1-21")

        if days <= 7:
            fee_per_item = Decimal("1.00")
        elif days <= 14:
            fee_per_item = Decimal("1.75")
        else:
            fee_per_item = Decimal("2.50")
        row_fees = fee_per_item * quantity
        row_late_per_item = zero
        for day in range(8, days + 1):
            if day <= 14:
                row_late_per_item += Decimal("0.25")
            else:
                row_late_per_item += Decimal("0.50")
        row_late = row_late_per_item * quantity
        if member == "basic":
            rate = Decimal("0.10")
        elif member == "plus":
            rate = Decimal("0.20")
        else:
            rate = Decimal("0")
        gross = row_fees + row_late
        charge = (gross * (Decimal("1") - rate)).quantize(cent, rounding=ROUND_HALF_UP)
        row_discount = gross - charge
        net += charge
        lines.append(
            f"Line {line_number}: fees ${row_fees:.2f}, late ${row_late:.2f}, discount ${row_discount:.2f}"
        )

    taxable = max(zero, net - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(cent, rounding=ROUND_HALF_UP)
    total = (net + tax).quantize(cent, rounding=ROUND_HALF_UP)
    lines.append(f"TOTAL ${total:.2f} (tax ${tax:.2f})")
    return "\n".join(lines)
