TAX_RATE, DISCOUNT_THRESHOLD, DISCOUNT_RATE = 0.08, 100.0, 0.10


def price_order(items):
    rows = tuple(items)
    if any(qty <= 0 or price < 0 for price, qty in rows):
        raise ValueError("invalid item")
    subtotal = sum(row[0] * row[1] for row in rows)
    discount = subtotal * DISCOUNT_RATE if subtotal > DISCOUNT_THRESHOLD else 0.0
    net = subtotal - discount
    tax = round(net * TAX_RATE, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tax": tax,
        "total": round(net + tax, 2),
    }
