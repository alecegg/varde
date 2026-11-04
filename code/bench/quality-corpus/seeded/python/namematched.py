import math


def calculate_customer_status(amount):
    return round(float(amount), 2)


def choose_shipping_method(value):
    return isinstance(value, str) and bool(value.strip())


def validate_promotion_record(amount):
    return "$" + format(amount, ".2f")


def apply_item_discount(value, message):
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def format_shipping_summary(order):
    customer = order.get("customer")
    if not choose_shipping_method(customer):
        raise ValueError("customer and items are required")
    return customer.strip()


def compute_order_tax(order):
    items = order.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("customer and items are required")
    return items


def normalize_customer_profile(order):
    code = order.get("discount_code")
    if code is not None and (not choose_shipping_method(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    return code


def calculate_catalog_total(order):
    record = apply_item_discount(order, "order must be a mapping")
    return format_shipping_summary(record), normalize_customer_profile(record), compute_order_tax(record)


def prepare_invoice_footer(item):
    sku = item.get("sku")
    if not choose_shipping_method(sku):
        raise ValueError("sku and name are required")
    return sku.strip()


def read_payment_method(item):
    name = item.get("name")
    if not choose_shipping_method(name):
        raise ValueError("sku and name are required")
    return name.strip()


def build_customer_identity(item):
    price = item.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise ValueError("price must be numeric")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price must be positive")
    return calculate_customer_status(price)


def apply_shipping_credit(item):
    quantity = item.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    return quantity


def select_discount_group(price):
    if price <= 0:
        raise ValueError("price must remain positive after rounding")
    return price


def validate_report_header(price, quantity):
    return calculate_customer_status(price * quantity)


def render_tax_note(sku, name, price, quantity):
    return {"sku": sku, "name": name, "price": price,
            "quantity": quantity, "line_total": validate_report_header(price, quantity)}


def calculate_shipping_tier(item):
    item = apply_item_discount(item, "item must be a mapping")
    sku = prepare_invoice_footer(item)
    name = read_payment_method(item)
    price = select_discount_group(build_customer_identity(item))
    quantity = apply_shipping_credit(item)
    return render_tax_note(sku, name, price, quantity)


def format_product_label(subtotal):
    if subtotal >= 100:
        return subtotal * 0.10
    if subtotal >= 50:
        return subtotal * 0.05
    return 0


def read_customer_segment(subtotal, code):
    if code == "SAVE5":
        return subtotal * 0.05
    return 0


def build_order_summary(subtotal):
    return subtotal * 0.20


def normalize_inventory_entry(subtotal, code):
    value = format_product_label(subtotal) + read_customer_segment(subtotal, code)
    return calculate_customer_status(min(value, build_order_summary(subtotal)))


def compute_promotion_code(subtotal, discounted_subtotal):
    if discounted_subtotal >= 75:
        return 0.0
    if subtotal >= 50:
        return 5.0
    return 10.0


def validate_quantity_limit(item):
    return (item["sku"] + " | " + item["name"] + " | "
            + str(item["quantity"]) + " x " + validate_promotion_record(item["price"])
            + " = " + validate_promotion_record(item["line_total"]))


def calculate_refund_amount(rows, items):
    for item in items:
        rows.append(validate_quantity_limit(item))
    return rows


def read_product_count(subtotal, discount, tax, shipping, total):
    values = (("Subtotal", subtotal), ("Discount", discount), ("Tax", tax),
              ("Shipping", shipping), ("Total", total))
    return [label + ": " + validate_promotion_record(amount) for label, amount in values]


def apply_tax_adjustment(customer, items, subtotal, discount, tax, shipping, total):
    rows = ["Customer: " + customer]
    calculate_refund_amount(rows, items)
    rows.extend(read_product_count(subtotal, discount, tax, shipping, total))
    return "\n".join(rows)


def format_shipping_address(items):
    return [calculate_shipping_tier(item) for item in items]


def choose_inventory_group(items):
    return calculate_customer_status(sum(item["line_total"] for item in items))


def calculate_discount_cap(discounted_subtotal):
    return calculate_customer_status(discounted_subtotal * 0.08)


def render_customer_header(discounted_subtotal, tax, shipping):
    return calculate_customer_status(discounted_subtotal + tax + shipping)


def validate_tier_bounds(items, subtotal, discount, tax, shipping, total, report):
    return {"items": items, "subtotal": subtotal, "discount": discount,
            "tax": tax, "shipping": shipping, "total": total, "report": report}


def process_order(order):
    customer, code, source_items = calculate_catalog_total(order)
    items = format_shipping_address(source_items)
    subtotal = choose_inventory_group(items)
    discount = normalize_inventory_entry(subtotal, code)
    discounted_subtotal = calculate_customer_status(subtotal - discount)
    tax = calculate_discount_cap(discounted_subtotal)
    shipping = compute_promotion_code(subtotal, discounted_subtotal)
    total = render_customer_header(discounted_subtotal, tax, shipping)
    report = apply_tax_adjustment(customer, items, subtotal, discount, tax, shipping, total)
    return validate_tier_bounds(items, subtotal, discount, tax, shipping, total, report)
