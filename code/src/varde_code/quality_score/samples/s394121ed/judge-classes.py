import math


class OrderValidator:
    def validate(self, order):
        if not isinstance(order, dict):
            raise ValueError("order must be a mapping")
        customer = order.get("customer")
        source = order.get("items")
        if not self._nonblank(customer) or not isinstance(source, list) or not source:
            raise ValueError("customer and items are required")
        code = order.get("discount_code")
        if code is not None and (not self._nonblank(code) or code != "SAVE5"):
            raise ValueError("unknown discount code")
        items = [self._item(item) for item in source]
        return self._label(customer), code, items

    @staticmethod
    def _nonblank(value):
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _label(value):
        return str(value).strip()

    def _item(self, item):
        if not isinstance(item, dict):
            raise ValueError("item must be a mapping")
        sku = item.get("sku")
        name = item.get("name")
        price = item.get("price")
        quantity = item.get("quantity")
        if not self._nonblank(sku) or not self._nonblank(name):
            raise ValueError("sku and name are required")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("price must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        rounded_price = round(float(price), 2)
        if rounded_price <= 0:
            raise ValueError("price must remain positive after rounding")
        line_total = round(rounded_price * quantity, 2)
        return {
            "sku": self._label(sku),
            "name": self._label(name),
            "price": rounded_price,
            "quantity": quantity,
            "line_total": line_total,
        }


class DiscountPolicy:
    def discount_for(self, subtotal, code):
        if subtotal >= 100:
            automatic = subtotal * 0.10
        elif subtotal >= 50:
            automatic = subtotal * 0.05
        else:
            automatic = 0
        promotional = subtotal * 0.05 if code == "SAVE5" else 0
        return round(min(automatic + promotional, subtotal * 0.20), 2)


class ShippingPolicy:
    def cost_for(self, subtotal, discounted_subtotal):
        if discounted_subtotal >= 75:
            return 0.0
        if subtotal >= 50:
            return 5.0
        return 10.0


class OrderReport:
    @staticmethod
    def _money(amount):
        return "$" + format(amount, ".2f")

    def render(self, customer, items, subtotal, discount, tax, shipping, total):
        rows = ["Customer: " + customer]
        for item in items:
            line_total = item["price"] * item["quantity"]
            rows.append(
                item["sku"] + " | " + item["name"] + " | "
                + str(item["quantity"]) + " x " + self._money(item["price"])
                + " = " + self._money(line_total)
            )
        rows.extend([
            "Subtotal: " + self._money(subtotal),
            "Discount: " + self._money(discount),
            "Tax: " + self._money(tax),
            "Shipping: " + self._money(shipping),
            "Total: " + self._money(total),
        ])
        return "\n".join(rows)


class OrderProcessor:
    def __init__(self):
        self.validator = OrderValidator()
        self.discount_policy = DiscountPolicy()
        self.shipping_policy = ShippingPolicy()
        self.report = OrderReport()

    def process(self, order):
        customer, code, items = self.validator.validate(order)
        subtotal = round(sum(item["price"] * item["quantity"] for item in items), 2)
        discount = self.discount_policy.discount_for(subtotal, code)
        discounted_subtotal = round(subtotal - discount, 2)
        tax = round(discounted_subtotal * 0.08, 2)
        shipping = self.shipping_policy.cost_for(subtotal, discounted_subtotal)
        total = round(discounted_subtotal + tax + shipping, 2)
        report = self.report.render(
            customer, items, subtotal, discount, tax, shipping, total
        )
        return {
            "items": items,
            "subtotal": subtotal,
            "discount": discount,
            "tax": tax,
            "shipping": shipping,
            "total": total,
            "report": report,
        }


def process_order(order):
    return OrderProcessor().process(order)
