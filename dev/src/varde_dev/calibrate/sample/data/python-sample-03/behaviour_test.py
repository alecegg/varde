assert price_order([(60, 2)]) == {
    "subtotal": 120,
    "discount": 12,
    "tax": 8.64,
    "total": 116.64,
}
try:
    price_order([(10, 0)])
except ValueError:
    pass
else:
    raise AssertionError("zero quantity must be rejected")
