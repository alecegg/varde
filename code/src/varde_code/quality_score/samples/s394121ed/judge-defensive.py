import math


def _n(value):
    # Reject values that cannot be converted before applying the shared money rounding rule.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("amount must be numeric")
    # Keep the conversion and rounding behavior consistent for every monetary result.
    return round(float(value), 2)


def _s(value):
    # Strings are accepted only when they contain visible, non-whitespace content.
    if not isinstance(value, str):
        return False
    # Strip only for the presence check so callers can decide whether to preserve or normalize it.
    return bool(value.strip())


def _money(value):
    # Format a validated monetary number with a fixed two-decimal representation.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("amount must be numeric")
    # Currency formatting is deterministic across report rows.
    return "$" + format(value, ".2f")


def _line(item):
    # Require the expected item mapping before reading its price and quantity.
    if not isinstance(item, dict) or "price" not in item or "quantity" not in item:
        raise ValueError("item is malformed")
    # Calculate the displayed extended price from the normalized item values.
    return _money(item["price"] * item["quantity"])


def _limit(value, cap):
    # Guard both operands so the cap operation has predictable numeric semantics.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("amount must be numeric")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)):
        raise ValueError("cap must be numeric")
    # Apply the requested upper bound to the discount.
    return min(value, cap)


def _tax(value):
    # Reject invalid inputs before calculating tax.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("amount must be numeric")
    # Tax uses the module's standard two-decimal rounding helper.
    return _n(value * 0.08)


def _ship(subtotal, net):
    # Validate both amounts before applying the shipping thresholds.
    if isinstance(subtotal, bool) or not isinstance(subtotal, (int, float)):
        raise ValueError("subtotal must be numeric")
    if isinstance(net, bool) or not isinstance(net, (int, float)):
        raise ValueError("net must be numeric")
    # Discounted merchandise above the free-shipping threshold ships at no cost.
    if net >= 75:
        return 0.0
    # Mid-sized orders use the standard five-dollar shipping rate.
    if subtotal >= 50:
        return 5.0
    # Smaller orders use the standard ten-dollar shipping rate.
    return 10.0


def _label(value):
    # Require a nonblank string before normalizing user-facing labels.
    if not _s(value):
        raise ValueError("label must be a nonblank string")
    # Trim surrounding whitespace for stable item and customer display.
    return value.strip()


def _amount(items):
    # Accept only a list of item mappings for subtotal calculation.
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    # Sum each validated line using its stored normalized price and quantity.
    return sum(item["price"] * item["quantity"] for item in items)


def _report(customer, items, subtotal, discount, tax, shipping, total):
    # Validate the customer and item collection before building report rows.
    if not _s(customer) or not isinstance(items, list):
        raise ValueError("report inputs are malformed")
    # Begin the report with the normalized customer label.
    rows = ["Customer: " + customer]
    # Add each item in the original order with its line extension.
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("item must be a mapping")
        rows.append(item["sku"] + " | " + item["name"] + " | " + str(item["quantity"]) + " x " + _money(item["price"]) + " = " + _line(item))
    # Append the monetary summary in its required deterministic order.
    rows.extend([
        "Subtotal: " + _money(subtotal),
        "Discount: " + _money(discount),
        "Tax: " + _money(tax),
        "Shipping: " + _money(shipping),
        "Total: " + _money(total),
    ])
    # Join all rows into the multiline report string.
    return "\n".join(rows)


def _extra(code, subtotal):
    # Validate the code and subtotal before determining promotional savings.
    if code is not None and not _s(code):
        raise ValueError("unknown discount code")
    if isinstance(subtotal, bool) or not isinstance(subtotal, (int, float)):
        raise ValueError("subtotal must be numeric")
    # SAVE5 adds five percent of the subtotal; absent codes add no savings.
    if code == "SAVE5":
        return subtotal * 0.05
    # Keep unsupported nonempty codes from silently receiving a zero discount.
    if code is not None:
        raise ValueError("unknown discount code")
    return 0


def process_order(order):
    # Require an order mapping before looking up any order fields.
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    # Read customer, item list, and optional code from the supplied order.
    customer = order.get("customer")
    source = order.get("items")
    if not _s(customer) or not isinstance(source, list) or len(source) == 0:
        raise ValueError("customer and items are required")
    # Validate the optional code before calculating any amounts.
    code = order.get("discount_code")
    if code is not None and (not _s(code) or code != "SAVE5"):
        raise ValueError("unknown discount code")
    # Normalize each item while preserving the input order.
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
        normalized_price = _n(price)
        if normalized_price <= 0:
            raise ValueError("price must remain positive after rounding")
        items.append({
            "sku": _label(sku),
            "name": _label(name),
            "price": normalized_price,
            "quantity": quantity,
            "line_total": _n(normalized_price * quantity),
        })
    # Round the subtotal after adding all normalized item line values.
    subtotal = _n(_amount(items))
    # Choose the automatic discount tier from the rounded subtotal.
    if subtotal >= 100:
        automatic = subtotal * 0.10
    elif subtotal >= 50:
        automatic = subtotal * 0.05
    else:
        automatic = 0
    # Combine automatic and promotional savings, then enforce the twenty-percent cap.
    promo = _extra(code, subtotal)
    discount = _n(_limit(automatic + promo, subtotal * 0.20))
    # Calculate the taxable net, tax, shipping, and final rounded total.
    net = _n(subtotal - discount)
    tax = _tax(net)
    shipping = _ship(subtotal, net)
    total = _n(net + tax + shipping)
    # Build the deterministic report using the same normalized order details.
    report = _report(_label(customer), items, subtotal, discount, tax, shipping, total)
    # Return item details and every monetary summary field.
    return {
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "shipping": shipping,
        "total": total,
        "report": report,
    }
