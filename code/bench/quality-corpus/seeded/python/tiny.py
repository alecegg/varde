import math


def _round_money(amount):
    return round(float(amount), 2)


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _money_text(amount):
    return "$" + format(amount, ".2f")


def _require_mapping(value, message):
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _customer_from(order):
    customer = order.get("customer")
    if not _nonblank(customer):
        raise ValueError("customer and items are required")
    return customer.strip()


def _items_from(order):
    items = order.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("customer and items are required")
    return items


def _code_from(order):
    code = order.get("discount_code")
    if code is not None and (not _nonblank(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    return code


def _validate_order(order):
    record = _require_mapping(order, "order must be a mapping")
    return _customer_from(record), _code_from(record), _items_from(record)


def _sku_from(item):
    sku = item.get("sku")
    if not _nonblank(sku):
        raise ValueError("sku and name are required")
    return sku.strip()


def _name_from(item):
    name = item.get("name")
    if not _nonblank(name):
        raise ValueError("sku and name are required")
    return name.strip()


def _price_from(item):
    price = item.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise ValueError("price must be numeric")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price must be positive")
    return _round_money(price)


def _quantity_from(item):
    quantity = item.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    return quantity


def _positive_rounded_price(price):
    if price <= 0:
        raise ValueError("price must remain positive after rounding")
    return price


def _line_total(price, quantity):
    return _round_money(price * quantity)


def _item_result(sku, name, price, quantity):
    return {"sku": sku, "name": name, "price": price,
            "quantity": quantity, "line_total": _line_total(price, quantity)}


def _normalize_item(item):
    item = _require_mapping(item, "item must be a mapping")
    sku = _sku_from(item)
    name = _name_from(item)
    price = _positive_rounded_price(_price_from(item))
    quantity = _quantity_from(item)
    return _item_result(sku, name, price, quantity)


def _automatic_discount(subtotal):
    if subtotal >= 100:
        return subtotal * 0.10
    if subtotal >= 50:
        return subtotal * 0.05
    return 0


def _promotion_discount(subtotal, code):
    if code == "SAVE5":
        return subtotal * 0.05
    return 0


def _discount_limit(subtotal):
    return subtotal * 0.20


def _calculate_discount(subtotal, code):
    value = _automatic_discount(subtotal) + _promotion_discount(subtotal, code)
    return _round_money(min(value, _discount_limit(subtotal)))


def _shipping_cost(subtotal, discounted_subtotal):
    if discounted_subtotal >= 75:
        return 0.0
    if subtotal >= 50:
        return 5.0
    return 10.0


def _item_line(item):
    return (item["sku"] + " | " + item["name"] + " | "
            + str(item["quantity"]) + " x " + _money_text(item["price"])
            + " = " + _money_text(item["line_total"]))


def _append_item_lines(rows, items):
    for item in items:
        rows.append(_item_line(item))
    return rows


def _summary_lines(subtotal, discount, tax, shipping, total):
    values = (("Subtotal", subtotal), ("Discount", discount), ("Tax", tax),
              ("Shipping", shipping), ("Total", total))
    return [label + ": " + _money_text(amount) for label, amount in values]


def _build_report(customer, items, subtotal, discount, tax, shipping, total):
    rows = ["Customer: " + customer]
    _append_item_lines(rows, items)
    rows.extend(_summary_lines(subtotal, discount, tax, shipping, total))
    return "\n".join(rows)


def _normalize_all(items):
    return [_normalize_item(item) for item in items]


def _subtotal_for(items):
    return _round_money(sum(item["line_total"] for item in items))


def _tax_for(discounted_subtotal):
    return _round_money(discounted_subtotal * 0.08)


def _total_for(discounted_subtotal, tax, shipping):
    return _round_money(discounted_subtotal + tax + shipping)


def _result(items, subtotal, discount, tax, shipping, total, report):
    return {"items": items, "subtotal": subtotal, "discount": discount,
            "tax": tax, "shipping": shipping, "total": total, "report": report}


def process_order(order):
    customer, code, source_items = _validate_order(order)
    items = _normalize_all(source_items)
    subtotal = _subtotal_for(items)
    discount = _calculate_discount(subtotal, code)
    discounted_subtotal = _round_money(subtotal - discount)
    tax = _tax_for(discounted_subtotal)
    shipping = _shipping_cost(subtotal, discounted_subtotal)
    total = _total_for(discounted_subtotal, tax, shipping)
    report = _build_report(customer, items, subtotal, discount, tax, shipping, total)
    return _result(items, subtotal, discount, tax, shipping, total, report)
