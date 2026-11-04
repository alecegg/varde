import math


def process_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    customer = order.get("customer")
    source_items = order.get("items")
    code = order.get("discount_code")
    if not isinstance(customer, str) or not customer.strip() or not isinstance(source_items, list) or not source_items:
        raise ValueError("customer and items are required")
    if code is not None and (not isinstance(code, str) or not code.strip() or code != "SAVE5"):
        raise ValueError("unknown discount code")
    customer = customer.strip()
    items = []
    for item in source_items:
        if not isinstance(item, dict):
            raise ValueError("item must be a mapping")
        sku = item.get("sku")
        name = item.get("name")
        price = item.get("price")
        quantity = item.get("quantity")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError("sku and name are required")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        price = round(float(price), 2)
        if price <= 0:
            raise ValueError("price must remain positive after rounding")
        items.append({"sku": sku.strip(), "name": name.strip(), "price": price, "quantity": quantity, "line_total": round(price * quantity, 2)})
    subtotal = round(sum(item["line_total"] for item in items), 2)
    if subtotal >= 100:
        automatic = subtotal * 0.10
    elif subtotal >= 50:
        automatic = subtotal * 0.05
    else:
        automatic = 0
    promotional = subtotal * 0.05 if code == "SAVE5" else 0
    discount = round(min(automatic + promotional, subtotal * 0.20), 2)
    discounted_subtotal = round(subtotal - discount, 2)
    tax = round(discounted_subtotal * 0.08, 2)
    if discounted_subtotal >= 75:
        shipping = 0.0
    elif subtotal >= 50:
        shipping = 5.0
    else:
        shipping = 10.0
    total = round(discounted_subtotal + tax + shipping, 2)
    rows = ["Customer: " + customer]
    for item in items:
        rows.append(item["sku"] + " | " + item["name"] + " | " + str(item["quantity"]) + " x $" + format(item["price"], ".2f") + " = $" + format(item["line_total"], ".2f"))
    for label, amount in (("Subtotal", subtotal), ("Discount", discount), ("Tax", tax), ("Shipping", shipping), ("Total", total)):
        rows.append(label + ": $" + format(amount, ".2f"))
    return {"items": items, "subtotal": subtotal, "discount": discount, "tax": tax, "shipping": shipping, "total": total, "report": "\n".join(rows)}
