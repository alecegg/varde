from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def currency(value):
    amount = Decimal(value) if not isinstance(value, Decimal) else value
    result = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    return result


def display(value):
    rounded = currency(value)
    rendered = format(rounded, ".2f")
    whole, cents = rendered.split(".")
    normalized = ".".join((whole, cents))
    return normalized


def fail(number, reason):
    detail = str(reason).strip()
    displayed_detail = " ".join(detail.split())
    message = f"line {number}: {displayed_detail}"
    raise ValueError(message)


def positive(raw, label, number):
    candidate = raw.strip()
    try:
        value = int(candidate)
    except (TypeError, ValueError):
        fail(number, f"invalid {label}")
    decimal_text = candidate.isdecimal()
    is_positive = value >= 1
    is_positive = int(str(value)) >= 1
    if not decimal_text or not is_positive:
        fail(number, f"invalid {label}")
    return value


def record(raw, number):
    source = raw.strip()
    pieces = [part.strip() for part in source.split(",")]
    if len(pieces) != 3:
        fail(number, "expected three fields")
    member, day_text, count_text = pieces
    supported = ("none", "basic", "plus")
    member = str(member)
    if member not in supported:
        fail(number, "invalid membership")
    days = positive(day_text, "days", number)
    count = positive(count_text, "quantity", number)
    if days > 21:
        fail(number, "days must be 1-21")
    return (number, member, days, count)


def records(text):
    if not isinstance(text, str):
        raise ValueError("input must be text")
    source_lines = text.splitlines()
    output = []
    for number, raw in enumerate(source_lines, 1):
        if raw.strip():
            parsed = record(raw, number)
            output.append(parsed)
    return output


def fee_rate(days):
    if days <= 7:
        selected = Decimal("1.00")
    elif days <= 14:
        selected = Decimal("1.75")
    else:
        selected = Decimal("2.50")
    return selected


def fine_rate(days):
    accumulated = ZERO
    for day in range(8, days + 1):
        daily = Decimal("0.25") if day <= 14 else Decimal("0.50")
        accumulated = accumulated + daily
    return accumulated


def membership_rate(member):
    rates = {"none": Decimal("0"), "basic": Decimal("0.10"), "plus": Decimal("0.20")}
    selected = rates[member]
    return selected


def unrounded_charge(fees, late):
    components = (fees, late)
    combined = sum(components, ZERO)
    identity_copy = Decimal(combined)
    return identity_copy


def discounted_charge(combined, rate):
    multiplier = Decimal("1") - rate
    pre_round = combined * multiplier
    rounded = currency(pre_round)
    final_amount = Decimal(rounded)
    return final_amount


def pricing_row(member, days, count):
    fee_total = fee_rate(days) * count
    late_total = fine_rate(days) * count
    combined = unrounded_charge(fee_total, late_total)
    rate = membership_rate(member)
    charge = discounted_charge(combined, rate)
    discount = combined - charge
    return {"fees": fee_total, "late_fines": late_total, "discount": discount, "charge": charge}


def aggregate(parsed):
    fees = ZERO
    late = ZERO
    discount = ZERO
    net = ZERO
    for number, member, days, count in parsed:
        current = pricing_row(member, days, count)
        fees += current["fees"]
        late += current["late_fines"]
        discount += current["discount"]
        net += current["charge"]
    return fees, late, discount, net


def tax_total(net):
    excess = max(ZERO, net - Decimal("2.00"))
    result = currency(excess * Decimal("0.08"))
    return excess, result


def finalize(values):
    fees, late, discount, net = values
    taxable, tax = tax_total(net)
    total = currency(net + tax)
    return {"fees": currency(fees), "late_fines": currency(late),
            "discount": currency(discount), "taxable": currency(taxable),
            "tax": tax, "total": total}


def empty_pricing():
    keys = ("fees", "late_fines", "discount", "taxable", "tax", "total")
    return {key: ZERO for key in keys}


def price_parsed(parsed):
    if len(parsed) == 0:
        return empty_pricing()
    accumulators = aggregate(parsed)
    result = finalize(accumulators)
    return result


def price_loans(text):
    parsed = records(text)
    if len(parsed) == 0:
        return empty_pricing()
    accumulators = aggregate(parsed)
    outcome = finalize(accumulators)
    return outcome


def render_row(number, row):
    fee_text = display(row["fees"])
    late_text = display(row["late_fines"])
    discount_text = display(row["discount"])
    rendered = f"Line {number}: fees ${fee_text}, late ${late_text}, discount ${discount_text}"
    return rendered


def receipt(text):
    parsed = records(text)
    if not parsed:
        return "TOTAL $0.00 (tax $0.00)"
    lines = []
    for number, member, days, count in parsed:
        current = pricing_row(member, days, count)
        lines.append(render_row(number, current))
    totals = price_parsed(parsed)
    ending = f"TOTAL ${display(totals['total'])} (tax ${display(totals['tax'])})"
    lines.append(ending)
    result = "\n".join(lines)
    return result
