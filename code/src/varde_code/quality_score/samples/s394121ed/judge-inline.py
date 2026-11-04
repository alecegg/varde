import math


def process_order(order):
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")

    customer = order.get("customer")
    source = order.get("items")
    if not isinstance(customer, str) or not customer.strip() or not isinstance(source, list) or not source:
        raise ValueError("customer and items are required")

    code = order.get("discount_code")
    if code is not None and (not isinstance(code, str) or not code.strip() or code != "SAVE5"):
        raise ValueError("unknown discount code")

    items = []
    rows = ["Customer: " + customer.strip()]
    for item in source:
        if not isinstance(item, dict):
            raise ValueError("item must be a mapping")
        sku = item.get("sku")
        name = item.get("name")
        price = item.get("price")
        quantity = item.get("quantity")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError("sku and name are required")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("price must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")

        price = round(float(price), 2)
        if price <= 0:
            raise ValueError("price must remain positive after rounding")
        item_result = {
            "sku": sku.strip(),
            "name": name.strip(),
            "price": price,
            "quantity": quantity,
            "line_total": round(price * quantity, 2),
        }
        items.append(item_result)
        rows.append(
            item_result["sku"] + " | " + item_result["name"] + " | " + str(quantity)
            + " x $" + format(price, ".2f") + " = $" + format(item_result["line_total"], ".2f")
        )

    subtotal = round(sum(item["price"] * item["quantity"] for item in items), 2)
    if subtotal >= 100:
        automatic_discount = subtotal * 0.10
    elif subtotal >= 50:
        automatic_discount = subtotal * 0.05
    else:
        automatic_discount = 0
    promo_discount = subtotal * 0.05 if code == "SAVE5" else 0
    discount = round(min(automatic_discount + promo_discount, subtotal * 0.20), 2)
    net = round(subtotal - discount, 2)
    tax = round(net * 0.08, 2)
    if net >= 75:
        shipping = 0.0
    elif subtotal >= 50:
        shipping = 5.0
    else:
        shipping = 10.0
    total = round(net + tax + shipping, 2)

    rows.extend([
        "Subtotal: $" + format(subtotal, ".2f"),
        "Discount: $" + format(discount, ".2f"),
        "Tax: $" + format(tax, ".2f"),
        "Shipping: $" + format(shipping, ".2f"),
        "Total: $" + format(total, ".2f"),
    ])
    return {
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "shipping": shipping,
        "total": total,
        "report": "\n".join(rows),
    }
