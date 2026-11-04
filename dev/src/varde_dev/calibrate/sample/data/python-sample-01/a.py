TAX_RATE = 0.08
DISCOUNT_THRESHOLD = 100.0
DISCOUNT_RATE = 0.10


def validate_items(items):
    for price, qty in items:
        if qty <= 0 or price < 0:
            raise ValueError("invalid item")


def price_order(items):
    """Return subtotal, discount, tax and total for a list of (price, qty) items."""
    validate_items(items)
    subtotal = sum(price * qty for price, qty in items)
    discount = subtotal * DISCOUNT_RATE if subtotal > DISCOUNT_THRESHOLD else 0.0
    taxable = subtotal - discount
    tax = round(taxable * TAX_RATE, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tax": tax,
        "total": round(taxable + tax, 2),
    }
