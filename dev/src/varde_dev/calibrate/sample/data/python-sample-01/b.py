TAX_RATE = 0.08
DISCOUNT_THRESHOLD = 100.0
DISCOUNT_RATE = 0.10


def _qty_of(item):
    return item[1]


def _price_of(item):
    return item[0]


def _check_qty(qty):
    return qty > 0


def _check_price(price):
    return price >= 0


def _item_ok(item):
    return _check_qty(_qty_of(item)) and _check_price(_price_of(item))


def _all_ok(items):
    return all(_item_ok(item) for item in items)


def _validate(items):
    if not _all_ok(items):
        raise ValueError("invalid item")


def _mul(a, b):
    return a * b


def _line_total(item):
    return _mul(_price_of(item), _qty_of(item))


def _sum_all(values):
    return sum(values)


def _subtotal(items):
    return _sum_all(_line_total(item) for item in items)


def _gt(a, b):
    return a > b


def _discount_applies(subtotal):
    return _gt(subtotal, DISCOUNT_THRESHOLD)


def _apply_rate(amount, rate):
    return amount * rate


def _discount_for(subtotal):
    return _apply_rate(subtotal, DISCOUNT_RATE) if _discount_applies(subtotal) else 0.0


def _taxable(subtotal, discount):
    return subtotal - discount


def _round2(value):
    return round(value, 2)


def _tax_for(taxable):
    return _round2(_apply_rate(taxable, TAX_RATE))


def _assemble(subtotal, discount, tax):
    total = _round2(_taxable(subtotal, discount) + tax)
    return {
        "subtotal": _round2(subtotal),
        "discount": _round2(discount),
        "tax": tax,
        "total": total,
    }


def price_order(items):
    """Return subtotal, discount, tax and total for a list of (price, qty) items."""
    _validate(items)
    subtotal = _subtotal(items)
    discount = _discount_for(subtotal)
    tax = _tax_for(_taxable(subtotal, discount))
    return _assemble(subtotal, discount, tax)
