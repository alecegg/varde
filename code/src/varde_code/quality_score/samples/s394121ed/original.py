import math


def _n(v):
    return round(float(v), 2)


def _s(v):
    return isinstance(v, str) and bool(v.strip())


def _money(v):
    return "$" + format(v, ".2f")


def _line(x):
    return _money(x["price"] * x["quantity"])


def _limit(v, cap):
    return min(v, cap)


def _tax(v):
    return _n(v * 0.08)


def _ship(subtotal, net):
    if net >= 75:
        return 0.0
    if subtotal >= 50:
        return 5.0
    return 10.0


def _label(x):
    return str(x).strip()


def _amount(items):
    return sum(x["price"] * x["quantity"] for x in items)


def _report(customer, items, subtotal, discount, tax, shipping, total):
    rows = ["Customer: " + customer]
    for x in items:
        rows.append(x["sku"] + " | " + x["name"] + " | " + str(x["quantity"]) + " x " + _money(x["price"]) + " = " + _line(x))
    rows.extend([
        "Subtotal: " + _money(subtotal),
        "Discount: " + _money(discount),
        "Tax: " + _money(tax),
        "Shipping: " + _money(shipping),
        "Total: " + _money(total),
    ])
    return "\n".join(rows)


def _extra(code, subtotal):
    if code == "SAVE5":
        return subtotal * 0.05
    return 0


def process_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    customer = order.get("customer")
    source = order.get("items")
    if not _s(customer) or not isinstance(source, list) or len(source) == 0:
        raise ValueError("customer and items are required")
    code = order.get("discount_code")
    if code is not None and (not _s(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    items = []
    for item in source:
        if not isinstance(item, dict):
            raise ValueError("item must be a mapping")
        sku = item.get("sku")
        name = item.get("name")
        price = item.get("price")
        quantity = item.get("quantity")
        if not _s(sku) or not _s(name):
            raise ValueError("sku and name are required")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("price must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        p = _n(price)
        if p <= 0:
            raise ValueError("price must remain positive after rounding")
        items.append({
            "sku": _label(sku),
            "name": _label(name),
            "price": p,
            "quantity": quantity,
            "line_total": _n(p * quantity),
        })
    subtotal = _n(_amount(items))
    if subtotal >= 100:
        automatic = subtotal * 0.10
    elif subtotal >= 50:
        automatic = subtotal * 0.05
    else:
        automatic = 0
    promo = _extra(code, subtotal)
    discount = _n(_limit(automatic + promo, subtotal * 0.20))
    net = _n(subtotal - discount)
    tax = _tax(net)
    shipping = _ship(subtotal, net)
    total = _n(net + tax + shipping)
    report = _report(_label(customer), items, subtotal, discount, tax, shipping, total)
    return {
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "shipping": shipping,
        "total": total,
        "report": report,
    }
