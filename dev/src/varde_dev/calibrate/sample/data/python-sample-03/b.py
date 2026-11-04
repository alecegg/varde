TAX_RATE, DISCOUNT_THRESHOLD, DISCOUNT_RATE = 0.08, 100.0, 0.10


def _read_quantity(item):
    return item[1]


def _read_price(item):
    return item[0]


def _quantity_ok(item):
    return _read_quantity(item) > 0


def _price_ok(item):
    return _read_price(item) >= 0


def _valid(item):
    return _quantity_ok(item) and _price_ok(item)


def _extended(item):
    return _read_price(item) * _read_quantity(item)


def _subtotal(lines):
    return sum(lines)


def _discount(total):
    return total * DISCOUNT_RATE if total > DISCOUNT_THRESHOLD else 0.0


def _tax(amount):
    return round(amount * TAX_RATE, 2)


def price_order(items):
    rows = tuple(items)
    if not all(_valid(row) for row in rows):
        raise ValueError("invalid item")
    subtotal = _subtotal(_extended(row) for row in rows)
    discount = _discount(subtotal)
    taxable = subtotal - discount
    tax = _tax(taxable)
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tax": tax,
        "total": round(taxable + tax, 2),
    }
