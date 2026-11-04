from decimal import Decimal, ROUND_HALF_UP


_CENT_AMOUNT = Decimal("0.01")
_ZERO_AMOUNT = Decimal("0.00")


def _round_currency_amount(input_value):
    return input_value.quantize(_CENT_AMOUNT, rounding=ROUND_HALF_UP)


def _format_currency_amount(input_value):
    return format(input_value, ".2f")


def _validate_record_fields(field_parts, physical_line_number):
    if len(field_parts) != 3:
        raise ValueError(f"line {physical_line_number}: expected three fields")


def _parse_positive_integer(input_value, integer_field_label, physical_line_number):
    try:
        parsed_integer_value = int(input_value)
    except (TypeError, ValueError):
        raise ValueError(f"line {physical_line_number}: invalid {integer_field_label}") from None
    if not input_value.isdecimal() or parsed_integer_value < 1:
        raise ValueError(f"line {physical_line_number}: invalid {integer_field_label}")
    return parsed_integer_value


def _loan_period_fee_per_item(loan_period_days):
    if loan_period_days <= 7:
        return Decimal("1.00")
    if loan_period_days <= 14:
        return Decimal("1.75")
    return Decimal("2.50")


def _late_fine_per_item(loan_period_days):
    total_amount = _ZERO_AMOUNT
    for day_number in range(8, loan_period_days + 1):
        if day_number <= 14:
            total_amount += Decimal("0.25")
        else:
            total_amount += Decimal("0.50")
    return total_amount


def _membership_discount_rate(membership_type):
    return {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}[membership_type]


def _calculate_record_amounts(membership_type, loan_period_days, item_quantity):
    loan_fees = _loan_period_fee_per_item(loan_period_days) * item_quantity
    late_fine_amount = _late_fine_per_item(loan_period_days) * item_quantity
    membership_discount_rate = _membership_discount_rate(membership_type)
    discounted_record_amount = _round_currency_amount((loan_fees + late_fine_amount) * (Decimal("1") - membership_discount_rate))
    discount_amount = loan_fees + late_fine_amount - discounted_record_amount
    return {"fees": loan_fees, "late_fines": late_fine_amount, "discount": discount_amount, "discounted_record_amount": discounted_record_amount}


def _parse_loan_records(loan_records_text):
    if not isinstance(loan_records_text, str):
        raise ValueError("input must be text")
    loan_records = []
    for physical_line_number, raw_line_text in enumerate(loan_records_text.splitlines(), 1):
        if not raw_line_text.strip():
            continue
        record_fields = [field_part.strip() for field_part in raw_line_text.split(",")]
        _validate_record_fields(record_fields, physical_line_number)
        membership_type = record_fields[0]
        if membership_type not in ("none", "basic", "plus"):
            raise ValueError(f"line {physical_line_number}: invalid membership")
        loan_period_days = _parse_positive_integer(record_fields[1], "days", physical_line_number)
        item_quantity = _parse_positive_integer(record_fields[2], "quantity", physical_line_number)
        if loan_period_days > 21:
            raise ValueError(f"line {physical_line_number}: days must be 1-21")
        loan_records.append((physical_line_number, membership_type, loan_period_days, item_quantity))
    return loan_records


def _calculate_taxable_amount_and_tax(currency_amount):
    taxable_amount = max(_ZERO_AMOUNT, currency_amount - Decimal("2.00"))
    return taxable_amount, _round_currency_amount(taxable_amount * Decimal("0.08"))


def _empty_loan_totals():
    return {"fees": _ZERO_AMOUNT, "late_fines": _ZERO_AMOUNT, "discount": _ZERO_AMOUNT,
            "taxable": _ZERO_AMOUNT, "tax": _ZERO_AMOUNT, "total": _ZERO_AMOUNT}


def price_loans(loan_records_text):
    """Parse loan records and return the monetary totals as Decimals."""
    loan_records = _parse_loan_records(loan_records_text)
    if not loan_records:
        return _empty_loan_totals()
    loan_fees = _ZERO_AMOUNT
    late_fine_amount = _ZERO_AMOUNT
    discount_amount = _ZERO_AMOUNT
    net_amount = _ZERO_AMOUNT
    for _, membership_type, loan_period_days, item_quantity in loan_records:
        record_amounts = _calculate_record_amounts(membership_type, loan_period_days, item_quantity)
        loan_fees += record_amounts["fees"]
        late_fine_amount += record_amounts["late_fines"]
        discount_amount += record_amounts["discount"]
        net_amount += record_amounts["discounted_record_amount"]
    taxable_amount, tax_amount = _calculate_taxable_amount_and_tax(net_amount)
    total_amount = net_amount + tax_amount
    return {"fees": _round_currency_amount(loan_fees), "late_fines": _round_currency_amount(late_fine_amount),
            "discount": _round_currency_amount(discount_amount), "taxable": _round_currency_amount(taxable_amount),
            "tax": tax_amount, "total": _round_currency_amount(total_amount)}


def _format_receipt_line(physical_line_number, record_amounts):
    return (f"Line {physical_line_number}: fees ${_format_currency_amount(record_amounts['fees'])}, late ${_format_currency_amount(record_amounts['late_fines'])}, "
            f"discount ${_format_currency_amount(record_amounts['discount'])}")


def _format_receipt_detail_lines(loan_records):
    detail_lines = []
    for physical_line_number, membership_type, loan_period_days, item_quantity in loan_records:
        detail_lines.append(_format_receipt_line(physical_line_number, _calculate_record_amounts(membership_type, loan_period_days, item_quantity)))
    return detail_lines


def receipt(loan_records_text):
    """Return an itemized text receipt for the supplied loan records."""
    loan_records = _parse_loan_records(loan_records_text)
    if not loan_records:
        return "TOTAL $0.00 (tax $0.00)"
    totals = price_loans(loan_records_text)
    receipt_lines = _format_receipt_detail_lines(loan_records)
    receipt_lines.append(f"TOTAL ${_format_currency_amount(totals['total'])} (tax ${_format_currency_amount(totals['tax'])})")
    return "\n".join(receipt_lines)
