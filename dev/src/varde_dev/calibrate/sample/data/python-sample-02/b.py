TAX_RATE, DISCOUNT_THRESHOLD, DISCOUNT_RATE = 0.08, 100.0, 0.10


def _qty(row):
    return row[1]


def _price(row):
    return row[0]


def _valid(row):
    return _qty(row) > 0 and _price(row) >= 0


def _line(row):
    return _price(row) * _qty(row)


def _discount(amount):
    return amount * DISCOUNT_RATE if amount > DISCOUNT_THRESHOLD else 0.0


def _tax(amount):
    return round(amount * TAX_RATE, 2)


def price_order(items):
    rows = list(items)
    if not all(map(_valid, rows)):
        raise ValueError("invalid item")
    subtotal = sum(map(_line, rows))
    discount = _discount(subtotal)
    taxable = subtotal - discount
    tax = _tax(taxable)
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tax": tax,
        "total": round(taxable + tax, 2),
    }
