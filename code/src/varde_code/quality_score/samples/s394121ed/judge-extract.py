import math


def _n(value):
    return round(float(value), 2)


def _s(value):
    return isinstance(value, str) and bool(value.strip())


def _money(value):
    return "$" + format(value, ".2f")


def _line(item):
    return _money(item["price"] * item["quantity"])


def _label(value):
    return str(value).strip()


def _mapping(value, message):
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _required_order_fields(order):
    customer, items = order.get("customer"), order.get("items")
    if not _s(customer) or not isinstance(items, list) or not items:
        raise ValueError("customer and items are required")
    return customer, items


def _validate_code(code):
    if code is not None and (not _s(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    return code


def _required_item_fields(item):
    sku, name = item.get("sku"), item.get("name")
    if not _s(sku) or not _s(name):
        raise ValueError("sku and name are required")
    return sku, name


def _valid_price(price):
    numeric = isinstance(price, (int, float)) and not isinstance(price, bool)
    if not numeric:
        raise ValueError("price must be numeric")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price must be positive")


def _valid_quantity(quantity):
    valid = isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0
    if not valid:
        raise ValueError("quantity must be a positive integer")


def _rounded_price(price):
    price = _n(price)
    if price <= 0:
        raise ValueError("price must remain positive after rounding")
    return price


def _item_result(item):
    item = _mapping(item, "item must be a mapping")
    sku, name = _required_item_fields(item)
    price, quantity = item.get("price"), item.get("quantity")
    _valid_price(price)
    _valid_quantity(quantity)
    return _make_item(sku, name, _rounded_price(price), quantity)


def _make_item(sku, name, price, quantity):
    return {"sku": _label(sku), "name": _label(name), "price": price,
            "quantity": quantity, "line_total": _n(price * quantity)}


def _items(source):
    return [_item_result(item) for item in source]


def _amount(items):
    return sum(item["price"] * item["quantity"] for item in items)


def _automatic_discount(subtotal):
    if subtotal >= 100:
        return subtotal * 0.10
    if subtotal >= 50:
        return subtotal * 0.05
    return 0


def _extra(code, subtotal):
    return subtotal * 0.05 if code == "SAVE5" else 0


def _discount(subtotal, code):
    amount = _automatic_discount(subtotal) + _extra(code, subtotal)
    return _n(min(amount, subtotal * 0.20))


def _tax(net):
    return _n(net * 0.08)


def _ship(subtotal, net):
    if net >= 75:
        return 0.0
    if subtotal >= 50:
        return 5.0
    return 10.0


def _item_row(item):
    fields = (item["sku"], item["name"], str(item["quantity"]))
    return fields[0] + " | " + fields[1] + " | " + fields[2] + " x " + _money(item["price"]) + " = " + _line(item)


def _item_rows(items):
    return [_item_row(item) for item in items]


def _summary_rows(subtotal, discount, tax, shipping, total):
    labels = ("Subtotal", "Discount", "Tax", "Shipping", "Total")
    values = (subtotal, discount, tax, shipping, total)
    return [label + ": " + _money(value) for label, value in zip(labels, values)]


def _report(customer, items, subtotal, discount, tax, shipping, total):
    rows = ["Customer: " + customer] + _item_rows(items)
    rows += _summary_rows(subtotal, discount, tax, shipping, total)
    return "\n".join(rows)


def _totals(items, code):
    subtotal = _n(_amount(items))
    discount = _discount(subtotal, code)
    net = _n(subtotal - discount)
    return _calculate_totals(subtotal, discount, net)


def _calculate_totals(subtotal, discount, net):
    tax = _tax(net)
    shipping = _ship(subtotal, net)
    total = _n(net + tax + shipping)
    return subtotal, discount, tax, shipping, total


def _result(items, customer, totals):
    subtotal, discount, tax, shipping, total = totals
    report = _report(_label(customer), items, subtotal, discount, tax, shipping, total)
    return {"items": items, "subtotal": subtotal, "discount": discount,
            "tax": tax, "shipping": shipping, "total": total, "report": report}


def process_order(order):
    order = _mapping(order, "order must be a mapping")
    customer, source = _required_order_fields(order)
    code = _validate_code(order.get("discount_code"))
    items = _items(source)
    return _result(items, customer, _totals(items, code))
