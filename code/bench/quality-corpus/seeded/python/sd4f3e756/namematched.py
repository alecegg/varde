from decimal import Decimal, ROUND_HALF_UP
currency_quantization_unit = Decimal('0.01')
zero_currency_amount = Decimal('0.00')

def quantize_currency_amount(monetary_value):
    return monetary_value.quantize(currency_quantization_unit, rounding=ROUND_HALF_UP)

def render_currency_amount(monetary_value):
    return format(monetary_value, '.2f')

def raise_record_validation_error(source_line_number, membership_category):
    raise ValueError(f'line {source_line_number}: {membership_category}')

def parse_positive_integer_field(monetary_value, field_label, source_line_number):
    try:
        field_content = int(monetary_value)
    except (TypeError, ValueError):
        raise_record_validation_error(source_line_number, f'invalid {field_label}')
    if not monetary_value.isdecimal() or field_content < 1:
        raise_record_validation_error(source_line_number, f'invalid {field_label}')
    if field_label == 'days':
        return validate_loan_day_limit(field_content, source_line_number)
    return field_content

def split_and_trim_record_fields(physical_line_content, source_line_number):
    trimmed_record_fields = [field_content.strip()
                             for field_content in physical_line_content.split(',')]
    if len(trimmed_record_fields) != 3:
        raise_record_validation_error(source_line_number, 'expected three fields')
    trimmed_record_fields[0] = validate_membership_value(
        trimmed_record_fields[0], source_line_number)
    return trimmed_record_fields

def validate_membership_value(membership_category, source_line_number):
    if membership_category not in ('none', 'basic', 'plus'):
        raise_record_validation_error(source_line_number, 'invalid membership')
    return membership_category

def validate_loan_day_limit(loan_period_days, source_line_number):
    if loan_period_days > 21:
        raise_record_validation_error(source_line_number, 'days must be 1-21')
    return loan_period_days

def parse_validated_loan_record(physical_line_content, source_line_number):
    membership_category, loan_period_days, requested_copies = (
        split_and_trim_record_fields(physical_line_content, source_line_number))
    loan_period_days = parse_positive_integer_field(
        loan_period_days, 'days', source_line_number)
    requested_copies = parse_positive_integer_field(
        requested_copies, 'quantity', source_line_number)
    return (source_line_number, membership_category, loan_period_days, requested_copies)

def is_nonblank_physical_line(physical_line_content):
    return bool(physical_line_content.strip())

def enumerate_physical_input_lines(input_document_text):
    return enumerate(input_document_text.splitlines(), 1)

def parse_all_loan_records(input_document_text):
    if not isinstance(input_document_text, str):
        raise ValueError('input must be text')
    return [parse_validated_loan_record(physical_line_content, source_line_number)
            for source_line_number, physical_line_content in
            enumerate_physical_input_lines(input_document_text)
            if is_nonblank_physical_line(physical_line_content)]

def lowest_loan_period_fee():
    return Decimal('1.00')

def middle_loan_period_fee():
    return Decimal('1.75')

def highest_loan_period_fee():
    return Decimal('2.50')

def select_loan_period_fee(loan_period_days):
    if loan_period_days <= 7:
        return lowest_loan_period_fee()
    if loan_period_days <= 14:
        return middle_loan_period_fee()
    return highest_loan_period_fee()

def zero_late_fine_amount():
    return zero_currency_amount

def late_fine_for_calendar_day(marginal_charge_day):
    return Decimal('0.25') if marginal_charge_day <= 14 else Decimal('0.50')

def sum_marginal_late_fines(loan_period_days):
    running_fine_total = zero_late_fine_amount()
    for marginal_charge_day in range(8, loan_period_days + 1):
        running_fine_total += late_fine_for_calendar_day(marginal_charge_day)
    return running_fine_total

def multiply_unit_amount_by_quantity(amount_before_adjustment, requested_copies):
    return amount_before_adjustment * requested_copies

def calculate_loan_period_fees(loan_period_days, requested_copies):
    unit_period_fee = select_loan_period_fee(loan_period_days)
    return multiply_unit_amount_by_quantity(unit_period_fee, requested_copies)

def calculate_late_fines(loan_period_days, requested_copies):
    marginal_fine_total = sum_marginal_late_fines(loan_period_days)
    return multiply_unit_amount_by_quantity(marginal_fine_total, requested_copies)

def select_membership_discount_rate(membership_category):
    return {'none': Decimal('0'), 'basic': Decimal('0.10'),
            'plus': Decimal('0.20')}[membership_category]

def combine_fee_and_fine_amounts(loan_fee_amount, late_fine_amount):
    return loan_fee_amount + late_fine_amount

def apply_membership_discount_rate(amount_before_adjustment, membership_discount_rate):
    return amount_before_adjustment * (Decimal('1') - membership_discount_rate)

def calculate_discount_amount(amount_before_adjustment, membership_discount_rate):
    discounted_amount = apply_membership_discount_rate(
        amount_before_adjustment, membership_discount_rate)
    return amount_before_adjustment - quantize_currency_amount(discounted_amount)

def calculate_net_charge_amount(amount_before_adjustment, membership_discount_rate):
    discounted_amount = apply_membership_discount_rate(
        amount_before_adjustment, membership_discount_rate)
    return quantize_currency_amount(discounted_amount)

def calculate_record_pricing_breakdown(membership_type, loan_period,
                                       requested_copies):
    record_fee_amount = calculate_loan_period_fees(loan_period, requested_copies)
    record_late_amount = calculate_late_fines(loan_period, requested_copies)
    combined_amount = combine_fee_and_fine_amounts(record_fee_amount, record_late_amount)
    membership_discount_rate = select_membership_discount_rate(membership_type)
    record_discount = calculate_discount_amount(combined_amount, membership_discount_rate)
    net_charge = calculate_net_charge_amount(combined_amount, membership_discount_rate)
    return {'fees': record_fee_amount, 'late_fines': record_late_amount,
            'discount': record_discount, 'charge': net_charge}

def create_zeroed_pricing_totals():
    keys = ('fees', 'late_fines', 'discount', 'taxable', 'tax', 'total')
    return {total_field_name: zero_currency_amount for total_field_name in keys}

def accumulate_record_pricing_amounts(aggregate_totals, record_pricing):
    aggregate_totals[0] += record_pricing['fees']
    aggregate_totals[1] += record_pricing['late_fines']
    aggregate_totals[2] += record_pricing['discount']
    aggregate_totals[3] += record_pricing['charge']

def aggregate_all_record_pricing_amounts(parsed_loan_records):
    aggregate_totals = [zero_currency_amount] * 4
    for (_, membership_category, loan_period_days, requested_copies) in parsed_loan_records:
        current_record = calculate_record_pricing_breakdown(
            membership_category, loan_period_days, requested_copies)
        accumulate_record_pricing_amounts(aggregate_totals, current_record)
    return aggregate_totals

def calculate_amount_subject_to_tax(net_total):
    return max(zero_currency_amount, net_total - Decimal('2.00'))

def calculate_sales_tax_amount(taxable_charge_total):
    return quantize_currency_amount(taxable_charge_total * Decimal('0.08'))

def calculate_total_including_tax(net_total, sales_tax_total):
    return quantize_currency_amount(net_total + sales_tax_total)

def format_aggregate_pricing_totals(aggregate_totals):
    record_fee_amount, record_late_amount, discounts_total, net_total = aggregate_totals
    taxable_charge_total = calculate_amount_subject_to_tax(net_total)
    return {'fees': quantize_currency_amount(record_fee_amount),
            'late_fines': quantize_currency_amount(record_late_amount),
            'discount': quantize_currency_amount(discounts_total),
            'taxable': quantize_currency_amount(taxable_charge_total),
            'tax': calculate_sales_tax_amount(taxable_charge_total),
            'total': calculate_total_including_tax(
                net_total, calculate_sales_tax_amount(taxable_charge_total))}

def price_parsed_loan_records(parsed_loan_records):
    if not parsed_loan_records:
        return create_zeroed_pricing_totals()
    aggregate_values = aggregate_all_record_pricing_amounts(parsed_loan_records)
    return format_aggregate_pricing_totals(aggregate_values)

def price_loans(input_document_text):
    parsed_loan_records = parse_all_loan_records(input_document_text)
    if not parsed_loan_records:
        return create_zeroed_pricing_totals()
    aggregate_values = aggregate_all_record_pricing_amounts(parsed_loan_records)
    return format_aggregate_pricing_totals(aggregate_values)

def render_record_receipt_line(source_line_number, record_pricing):
    return (f"Line {source_line_number}: fees ${render_currency_amount(record_pricing['fees'])}, "
            f"late ${render_currency_amount(record_pricing['late_fines'])}, "
            f"discount ${render_currency_amount(record_pricing['discount'])}")

def render_loan_record_receipt(loan_record):
    (source_line_number, membership_category, loan_period_days,
     requested_copies) = loan_record
    current_record = calculate_record_pricing_breakdown(
        membership_category, loan_period_days, requested_copies)
    return render_record_receipt_line(source_line_number, current_record)

def render_receipt_total_line(running_fine_total):
    return (f"TOTAL ${render_currency_amount(running_fine_total['total'])} "
            f"(tax ${render_currency_amount(running_fine_total['tax'])})")

def receipt(input_document_text):
    parsed_loan_records = parse_all_loan_records(input_document_text)
    if not parsed_loan_records:
        return 'TOTAL $0.00 (tax $0.00)'
    receipt_lines = [render_loan_record_receipt(record_pricing)
                    for record_pricing in parsed_loan_records]
    receipt_lines.append(render_receipt_total_line(price_parsed_loan_records(parsed_loan_records)))
    return '\n'.join(receipt_lines)
