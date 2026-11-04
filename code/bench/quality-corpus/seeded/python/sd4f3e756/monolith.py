from decimal import Decimal, ROUND_HALF_UP


def price_loans(text):
    cent = Decimal("0.01")
    zero = Decimal("0.00")
    if not isinstance(text, str):
        raise ValueError("input must be text")
    fees = late_fines = discount = net = zero
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
            raise ValueError(f"line {line_number}: invalid days")
        if not day_text.isdecimal() or days < 1:
            raise ValueError(f"line {line_number}: invalid days")
        try:
            quantity = int(quantity_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid quantity")
        if not quantity_text.isdecimal() or quantity < 1:
            raise ValueError(f"line {line_number}: invalid quantity")
        if days > 21:
            raise ValueError(f"line {line_number}: days must be 1-21")
        if days <= 7:
            fee_unit = Decimal("1.00")
        elif days <= 14:
            fee_unit = Decimal("1.75")
        else:
            fee_unit = Decimal("2.50")
        fee_value = fee_unit * quantity
        fine_unit = zero
        for borrowed_day in range(8, days + 1):
            fine_unit += Decimal("0.25") if borrowed_day <= 14 else Decimal("0.50")
        fine_value = fine_unit * quantity
        if member == "none":
            reduction = Decimal("0")
        elif member == "basic":
            reduction = Decimal("0.10")
        else:
            reduction = Decimal("0.20")
        gross = fee_value + fine_value
        charge = (gross * (Decimal("1") - reduction)).quantize(cent, rounding=ROUND_HALF_UP)
        fees += fee_value
        late_fines += fine_value
        discount += gross - charge
        net += charge
    taxable = max(zero, net - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(cent, rounding=ROUND_HALF_UP)
    total = (net + tax).quantize(cent, rounding=ROUND_HALF_UP)
    return {"fees": fees.quantize(cent, rounding=ROUND_HALF_UP),
            "late_fines": late_fines.quantize(cent, rounding=ROUND_HALF_UP),
            "discount": discount.quantize(cent, rounding=ROUND_HALF_UP),
            "taxable": taxable.quantize(cent, rounding=ROUND_HALF_UP),
            "tax": tax, "total": total}


def receipt(text):
    cent = Decimal("0.01")
    zero = Decimal("0.00")
    if not isinstance(text, str):
        raise ValueError("input must be text")
    records = []
    fee_sum = late_sum = discount_sum = net_sum = zero
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
            raise ValueError(f"line {line_number}: invalid days")
        if not day_text.isdecimal() or days < 1:
            raise ValueError(f"line {line_number}: invalid days")
        try:
            quantity = int(quantity_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line_number}: invalid quantity")
        if not quantity_text.isdecimal() or quantity < 1:
            raise ValueError(f"line {line_number}: invalid quantity")
        if days > 21:
            raise ValueError(f"line {line_number}: days must be 1-21")
        if days <= 7:
            fee_unit = Decimal("1.00")
        elif days <= 14:
            fee_unit = Decimal("1.75")
        else:
            fee_unit = Decimal("2.50")
        fee_value = fee_unit * quantity
        fine_unit = zero
        for borrowed_day in range(8, days + 1):
            fine_unit += Decimal("0.25") if borrowed_day <= 14 else Decimal("0.50")
        fine_value = fine_unit * quantity
        reduction = {"none": Decimal("0"), "basic": Decimal("0.10"),
                     "plus": Decimal("0.20")}[member]
        gross = fee_value + fine_value
        charge = (gross * (Decimal("1") - reduction)).quantize(cent, rounding=ROUND_HALF_UP)
        row_discount = gross - charge
        records.append((line_number, fee_value, fine_value, row_discount))
        fee_sum += fee_value
        late_sum += fine_value
        discount_sum += row_discount
        net_sum += charge
    if not records:
        return "TOTAL $0.00 (tax $0.00)"
    output = []
    for line_number, fee_value, fine_value, row_discount in records:
        output.append(f"Line {line_number}: fees ${format(fee_value, '.2f')}, "
                      f"late ${format(fine_value, '.2f')}, "
                      f"discount ${format(row_discount, '.2f')}")
    taxable = max(zero, net_sum - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(cent, rounding=ROUND_HALF_UP)
    total = (net_sum + tax).quantize(cent, rounding=ROUND_HALF_UP)
    output.append(f"TOTAL ${format(total, '.2f')} (tax ${format(tax, '.2f')})")
    return "\n".join(output)
