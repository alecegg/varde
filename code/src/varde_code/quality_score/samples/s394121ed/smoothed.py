import math


def _round_money(amount):
    return round(float(amount), 2)


def _is_nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _format_money(amount):
    return "$" + format(amount, ".2f")


def _validate_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")

    customer = order.get("customer")
    items = order.get("items")
    if not _is_nonblank(customer) or not isinstance(items, list) or not items:
        raise ValueError("customer and items are required")

    code = order.get("discount_code")
    if code is not None and (not _is_nonblank(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    return customer.strip(), code, items


def _normalize_item(item):
    if not isinstance(item, dict):
        raise ValueError("item must be a mapping")

    sku = item.get("sku")
    name = item.get("name")
    price = item.get("price")
    quantity = item.get("quantity")
    if not _is_nonblank(sku) or not _is_nonblank(name):
        raise ValueError("sku and name are required")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise ValueError("price must be numeric")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price must be positive")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")

    price = _round_money(price)
    if price <= 0:
        raise ValueError("price must remain positive after rounding")
    return {
        "sku": sku.strip(),
        "name": name.strip(),
        "price": price,
        "quantity": quantity,
        "line_total": _round_money(price * quantity),
    }


def _calculate_discount(subtotal, code):
    if subtotal >= 100:
        automatic = subtotal * 0.10
    elif subtotal >= 50:
        automatic = subtotal * 0.05
    else:
        automatic = 0
    promotional = subtotal * 0.05 if code == "SAVE5" else 0
    return _round_money(min(automatic + promotional, subtotal * 0.20))


def _shipping_cost(subtotal, discounted_subtotal):
    if discounted_subtotal >= 75:
        return 0.0
    if subtotal >= 50:
        return 5.0
    return 10.0


def _build_report(customer, items, subtotal, discount, tax, shipping, total):
    rows = ["Customer: " + customer]
    for item in items:
        line = (
            item["sku"] + " | " + item["name"] + " | "
            + str(item["quantity"]) + " x " + _format_money(item["price"])
            + " = " + _format_money(item["line_total"])
        )
        rows.append(line)

    for label, amount in (
        ("Subtotal", subtotal),
        ("Discount", discount),
        ("Tax", tax),
        ("Shipping", shipping),
        ("Total", total),
    ):
        rows.append(label + ": " + _format_money(amount))
    return "\n".join(rows)


def process_order(order):
    customer, code, source_items = _validate_order(order)
    items = [_normalize_item(item) for item in source_items]

    subtotal = _round_money(sum(item["line_total"] for item in items))
    discount = _calculate_discount(subtotal, code)
    discounted_subtotal = _round_money(subtotal - discount)
    tax = _round_money(discounted_subtotal * 0.08)
    shipping = _shipping_cost(subtotal, discounted_subtotal)
    total = _round_money(discounted_subtotal + tax + shipping)

    return {
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "shipping": shipping,
        "total": total,
        "report": _build_report(
            customer, items, subtotal, discount, tax, shipping, total
        ),
    }
