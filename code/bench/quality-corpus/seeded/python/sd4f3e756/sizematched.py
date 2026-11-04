from decimal import Decimal, ROUND_HALF_UP


def _read(text):
    if not isinstance(text, str):
        raise ValueError("input must be text")
    result = []
    for line, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 3:
            raise ValueError(f"line {line}: expected three fields")
        member, day_text, quantity_text = parts
        if member not in ("none", "basic", "plus"):
            raise ValueError(f"line {line}: invalid membership")
        try:
            days, quantity = int(day_text), int(quantity_text)
        except (TypeError, ValueError):
            raise ValueError(f"line {line}: invalid days or quantity")
        if not day_text.isdecimal() or days < 1:
            raise ValueError(f"line {line}: invalid days")
        if not quantity_text.isdecimal() or quantity < 1:
            raise ValueError(f"line {line}: invalid quantity")
        if days > 21:
            raise ValueError(f"line {line}: days must be 1-21")
        result.append((line, member, days, quantity))
    return result


def price_loans(text):
    penny, zero = Decimal("0.01"), Decimal("0.00")
    fees = fines = savings = due = zero
    for line, member, days, quantity in _read(text):
        unit = Decimal("1.00") if days <= 7 else Decimal("1.75")
        if days > 14:
            unit = Decimal("2.50")
        fee = unit * quantity
        fine = sum((Decimal("0.25") if d <= 14 else Decimal("0.50")
                    for d in range(8, days + 1)), zero) * quantity
        rate = {"none": Decimal("0"), "basic": Decimal("0.10"),
                "plus": Decimal("0.20")}[member]
        amount = fee + fine
        net = (amount * (Decimal("1") - rate)).quantize(penny, rounding=ROUND_HALF_UP)
        fees += fee
        fines += fine
        savings += amount - net
        due += net
    taxable = max(zero, due - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(penny, rounding=ROUND_HALF_UP)
    return {"fees": fees.quantize(penny, rounding=ROUND_HALF_UP),
            "late_fines": fines.quantize(penny, rounding=ROUND_HALF_UP),
            "discount": savings.quantize(penny, rounding=ROUND_HALF_UP),
            "taxable": taxable.quantize(penny, rounding=ROUND_HALF_UP),
            "tax": tax, "total": (due + tax).quantize(penny, rounding=ROUND_HALF_UP)}


def receipt(text):
    penny, zero = Decimal("0.01"), Decimal("0.00")
    lines, due = [], zero
    for number, member, days, quantity in _read(text):
        unit = Decimal("1.00") if days <= 7 else Decimal("1.75")
        if days > 14:
            unit = Decimal("2.50")
        fee = unit * quantity
        fine = zero
        for day in range(8, days + 1):
            fine += Decimal("0.25") if day <= 14 else Decimal("0.50")
        fine *= quantity
        rate = {"none": Decimal("0"), "basic": Decimal("0.10"),
                "plus": Decimal("0.20")}[member]
        amount = fee + fine
        net = (amount * (Decimal("1") - rate)).quantize(penny, rounding=ROUND_HALF_UP)
        due += net
        lines.append(f"Line {number}: fees ${format(fee, '.2f')}, late ${format(fine, '.2f')}, "
                     f"discount ${format(amount - net, '.2f')}")
    if not lines:
        return "TOTAL $0.00 (tax $0.00)"
    taxable = max(zero, due - Decimal("2.00"))
    tax = (taxable * Decimal("0.08")).quantize(penny, rounding=ROUND_HALF_UP)
    total = (due + tax).quantize(penny, rounding=ROUND_HALF_UP)
    lines.append(f"TOTAL ${format(total, '.2f')} (tax ${format(tax, '.2f')})")
    return "\n".join(lines)
