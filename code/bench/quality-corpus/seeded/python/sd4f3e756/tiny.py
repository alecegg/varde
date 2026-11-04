from decimal import Decimal, ROUND_HALF_UP

C = Decimal("0.01")
Z = Decimal("0.00")


def q(v):
    return v.quantize(C, rounding=ROUND_HALF_UP)


def s(v):
    return format(v, ".2f")


def err(n, m):
    raise ValueError(f"line {n}: {m}")


def integer(v, label, n):
    try:
        x = int(v)
    except (TypeError, ValueError):
        err(n, f"invalid {label}")
    if not v.isdecimal() or x < 1:
        err(n, f"invalid {label}")
    return x


def fields(raw, n):
    parts = [x.strip() for x in raw.split(",")]
    if len(parts) != 3:
        err(n, "expected three fields")
    return parts


def member_ok(m, n):
    if m not in ("none", "basic", "plus"):
        err(n, "invalid membership")
    return m


def bounded_days(d, n):
    if d > 21:
        err(n, "days must be 1-21")
    return d


def parse_record(raw, n):
    m, d, a = fields(raw, n)
    m = member_ok(m, n)
    d = bounded_days(integer(d, "days", n), n)
    a = integer(a, "quantity", n)
    return (n, m, d, a)


def include(raw):
    return bool(raw.strip())


def numbered(text):
    return enumerate(text.splitlines(), 1)


def parse_rows(text):
    if not isinstance(text, str):
        raise ValueError("input must be text")
    return [parse_record(raw, n) for n, raw in numbered(text) if include(raw)]


def tier_low():
    return Decimal("1.00")


def tier_mid():
    return Decimal("1.75")


def tier_high():
    return Decimal("2.50")


def tier(days):
    if days <= 7:
        return tier_low()
    if days <= 14:
        return tier_mid()
    return tier_high()


def zero_fine():
    return Z


def fine_step(day):
    return Decimal("0.25") if day <= 14 else Decimal("0.50")


def fine_days(days):
    total = zero_fine()
    for day in range(8, days + 1):
        total += fine_step(day)
    return total


def quantity_cost(value, amount):
    return value * amount


def fees(days, amount):
    return quantity_cost(tier(days), amount)


def late(days, amount):
    return quantity_cost(fine_days(days), amount)


def rate_for(member):
    return {"none": Decimal("0"), "basic": Decimal("0.10"),
            "plus": Decimal("0.20")}[member]


def before_discount(fee, fine):
    return fee + fine


def after_rate(value, rate):
    return value * (Decimal("1") - rate)


def discount_amount(value, rate):
    return value - q(after_rate(value, rate))


def charge_amount(value, rate):
    return q(after_rate(value, rate))


def make_row(member, days, amount):
    f = fees(days, amount)
    l = late(days, amount)
    base = before_discount(f, l)
    rate = rate_for(member)
    return {"fees": f, "late_fines": l,
            "discount": discount_amount(base, rate),
            "charge": charge_amount(base, rate)}


def empty_values():
    return {k: Z for k in ("fees", "late_fines", "discount", "taxable", "tax", "total")}


def add_row(acc, row):
    acc[0] += row["fees"]
    acc[1] += row["late_fines"]
    acc[2] += row["discount"]
    acc[3] += row["charge"]


def sum_rows(rows):
    acc = [Z, Z, Z, Z]
    for _, m, d, a in rows:
        add_row(acc, make_row(m, d, a))
    return acc


def taxable_amount(net):
    return max(Z, net - Decimal("2.00"))


def tax_amount(taxable):
    return q(taxable * Decimal("0.08"))


def final_total(net, tax):
    return q(net + tax)


def totals_from(acc):
    f, l, discount, net = acc
    taxable = taxable_amount(net)
    tax = tax_amount(taxable)
    return {"fees": q(f), "late_fines": q(l), "discount": q(discount),
            "taxable": q(taxable), "tax": tax, "total": final_total(net, tax)}


def price_rows(rows):
    if not rows:
        return empty_values()
    return totals_from(sum_rows(rows))


def price_loans(text):
    rows = parse_rows(text)
    if not rows:
        return empty_values()
    return totals_from(sum_rows(rows))


def row_text(number, row):
    return (f"Line {number}: fees ${s(row['fees'])}, late ${s(row['late_fines'])}, "
            f"discount ${s(row['discount'])}")


def receipt_line(record):
    n, m, d, a = record
    return row_text(n, make_row(m, d, a))


def total_text(total):
    return f"TOTAL ${s(total['total'])} (tax ${s(total['tax'])})"


def receipt(text):
    rows = parse_rows(text)
    if not rows:
        return "TOTAL $0.00 (tax $0.00)"
    lines = [receipt_line(row) for row in rows]
    lines.append(total_text(price_rows(rows)))
    return "\n".join(lines)
