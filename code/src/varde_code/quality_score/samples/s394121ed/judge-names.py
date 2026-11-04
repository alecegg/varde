import math


def _round_to_cents(monetary_amount):
    return round(float(monetary_amount), 2)


def _is_nonblank_text(text_value):
    return isinstance(text_value, str) and bool(text_value.strip())


def _format_currency(monetary_amount):
    return "$" + format(monetary_amount, ".2f")


def _format_line_total(order_item):
    return _format_currency(order_item["price"] * order_item["quantity"])


def _cap_discount(discount_amount, maximum_discount_amount):
    return min(discount_amount, maximum_discount_amount)


def _calculate_tax(taxable_amount):
    return _round_to_cents(taxable_amount * 0.08)


def _calculate_shipping(subtotal_amount, discounted_merchandise_amount):
    if discounted_merchandise_amount >= 75:
        return 0.0
    if subtotal_amount >= 50:
        return 5.0
    return 10.0


def _normalize_label(label_text):
    return str(label_text).strip()


def _calculate_subtotal(order_items):
    return sum(order_item["price"] * order_item["quantity"] for order_item in order_items)


def _build_report(customer_name, order_items, subtotal_amount, discount_amount, tax_amount, shipping_amount, total_amount):
    report_lines = ["Customer: " + customer_name]
    for order_item in order_items:
        report_lines.append(order_item["sku"] + " | " + order_item["name"] + " | " + str(order_item["quantity"]) + " x " + _format_currency(order_item["price"]) + " = " + _format_line_total(order_item))
    report_lines.extend([
        "Subtotal: " + _format_currency(subtotal_amount),
        "Discount: " + _format_currency(discount_amount),
        "Tax: " + _format_currency(tax_amount),
        "Shipping: " + _format_currency(shipping_amount),
        "Total: " + _format_currency(total_amount),
    ])
    return "\n".join(report_lines)


def _calculate_promotion_discount(discount_code, subtotal_amount):
    if discount_code == "SAVE5":
        return subtotal_amount * 0.05
    return 0


def process_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    customer_name = order.get("customer")
    source_order_items = order.get("items")
    if not _is_nonblank_text(customer_name) or not isinstance(source_order_items, list) or len(source_order_items) == 0:
        raise ValueError("customer and items are required")
    discount_code = order.get("discount_code")
    if discount_code is not None and (not _is_nonblank_text(discount_code) or discount_code != "SAVE5"):
        raise ValueError("unknown discount code")
    normalized_order_items = []
    for source_order_item in source_order_items:
        if not isinstance(source_order_item, dict):
            raise ValueError("item must be a mapping")
        stock_keeping_unit = source_order_item.get("sku")
        item_name = source_order_item.get("name")
        unit_price = source_order_item.get("price")
        item_quantity = source_order_item.get("quantity")
        if not _is_nonblank_text(stock_keeping_unit) or not _is_nonblank_text(item_name):
            raise ValueError("sku and name are required")
        if isinstance(unit_price, bool) or not isinstance(unit_price, (int, float)):
            raise ValueError("price must be numeric")
        if not math.isfinite(unit_price) or unit_price <= 0:
            raise ValueError("price must be positive")
        if isinstance(item_quantity, bool) or not isinstance(item_quantity, int) or item_quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        normalized_unit_price = _round_to_cents(unit_price)
        if normalized_unit_price <= 0:
            raise ValueError("price must remain positive after rounding")
        normalized_order_items.append({
            "sku": _normalize_label(stock_keeping_unit),
            "name": _normalize_label(item_name),
            "price": normalized_unit_price,
            "quantity": item_quantity,
            "line_total": _round_to_cents(normalized_unit_price * item_quantity),
        })
    subtotal_amount = _round_to_cents(_calculate_subtotal(normalized_order_items))
    if subtotal_amount >= 100:
        automatic_discount_amount = subtotal_amount * 0.10
    elif subtotal_amount >= 50:
        automatic_discount_amount = subtotal_amount * 0.05
    else:
        automatic_discount_amount = 0
    promotion_discount_amount = _calculate_promotion_discount(discount_code, subtotal_amount)
    discount_amount = _round_to_cents(_cap_discount(automatic_discount_amount + promotion_discount_amount, subtotal_amount * 0.20))
    discounted_merchandise_amount = _round_to_cents(subtotal_amount - discount_amount)
    tax_amount = _calculate_tax(discounted_merchandise_amount)
    shipping_amount = _calculate_shipping(subtotal_amount, discounted_merchandise_amount)
    total_amount = _round_to_cents(discounted_merchandise_amount + tax_amount + shipping_amount)
    report = _build_report(_normalize_label(customer_name), normalized_order_items, subtotal_amount, discount_amount, tax_amount, shipping_amount, total_amount)
    return {
        "items": normalized_order_items,
        "subtotal": subtotal_amount,
        "discount": discount_amount,
        "tax": tax_amount,
        "shipping": shipping_amount,
        "total": total_amount,
        "report": report,
    }
