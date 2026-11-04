TAX_RATE = 0.08
DISCOUNT_THRESHOLD = 100.0
DISCOUNT_RATE = 0.10


def price_order(items):
    subtotal = 0.0
    for price, quantity in items:
        if price < 0 or quantity < 1:
            raise ValueError("invalid item")
        subtotal += price * quantity
    savings = subtotal * DISCOUNT_RATE if subtotal > DISCOUNT_THRESHOLD else 0.0
    taxable = subtotal - savings
    tax = round(taxable * TAX_RATE, 2)
    total = round(taxable + tax, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(savings, 2),
        "tax": tax,
        "total": total,
    }
