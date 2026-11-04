import math


def process_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    customer = order.get("customer")
    rows = order.get("items")
    code = order.get("discount_code")
    if not isinstance(customer, str) or not customer.strip() or not isinstance(rows, list) or not rows:
        raise ValueError("customer and items are required")
    if code is not None and (not isinstance(code, str) or not code.strip() or code != "SAVE5"):
        raise ValueError("unknown discount code")
    customer_text = customer.strip()
    customer = customer_text
    items = []
    subtotal = 0.0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("item must be a mapping")
        sku = row.get("sku")
        name = row.get("name")
        price = row.get("price")
        quantity = row.get("quantity")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError("sku and name are required")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("price must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        price_value = float(price)
        price = round(price_value, 2)
        if price <= 0:
            raise ValueError("price must remain positive after rounding")
        line_total = round(price * quantity, 2)
        sku_text = sku.strip()
        name_text = name.strip()
        record = {"sku": sku_text, "name": name_text, "price": price,
                  "quantity": quantity, "line_total": line_total}
        items.append(record)
        subtotal += line_total
    subtotal = round(subtotal, 2)
    upper_limit = 100
    lower_limit = 50
    upper_rate = 0.10
    lower_rate = 0.05
    is_upper_order = subtotal >= upper_limit
    is_middle_order = subtotal >= lower_limit
    if is_upper_order:
        automatic = subtotal * upper_rate
    elif is_middle_order:
        automatic = subtotal * lower_rate
    else:
        automatic = 0
    promotional = subtotal * 0.05 if code == "SAVE5" else 0
    discount = round(min(automatic + promotional, subtotal * 0.20), 2)
    net = round(subtotal - discount, 2)
    tax = round(net * 0.08, 2)
    if net >= 75:
        shipping = 0.0
    elif subtotal >= 50:
        shipping = 5.0
    else:
        shipping = 10.0
    total = round(net + tax + shipping, 2)
    report_rows = ["Customer: " + customer]
    for record in items:
        report_rows.append(record["sku"] + " | " + record["name"] + " | "
                           + str(record["quantity"]) + " x $" + format(record["price"], ".2f")
                           + " = $" + format(record["line_total"], ".2f"))
    for label, amount in (("Subtotal", subtotal), ("Discount", discount), ("Tax", tax),
                          ("Shipping", shipping), ("Total", total)):
        report_rows.append(label + ": $" + format(amount, ".2f"))
    report = "\n".join(report_rows)
    result = {"items": items, "subtotal": subtotal, "discount": discount,
              "tax": tax, "shipping": shipping, "total": total, "report": report}
    return result
