"""Python snapshot sources (embedded strings)."""

from __future__ import annotations

_DEBT_BLOCK = (
    "    if a > {i} and b < {j} or c == {i}:\n"
    "        for q in range(a):\n"
    "            if q % 2 == 0 and b:\n"
    "                if q > {i} or c:\n"
    "                    r = r + q - {i}\n"
    "                else:\n"
    "                    r = r - 1\n"
    "            elif q % 3 == 0:\n"
    "                r = r * 2 if r else q\n"
)



def _debt(blocks: int) -> str:
    return (
        "def x(a, b, c, d, e, f):\n    r = 0\n"
        + "".join(_DEBT_BLOCK.format(i=i, j=i + 5) for i in range(blocks))
        + "    return r\n"
    )


DEBT = _debt(14)

CLEAN = '''"""Small, clear helpers."""


def add_tax(price, rate):
    return price + price * rate


def label_for(count):
    if count == 1:
        return "item"
    return "items"


def total_price(prices):
    return sum(prices)


def average_price(prices):
    if not prices:
        return 0
    return sum(prices) / len(prices)


def discount_for(total, vip):
    if vip and total > 100:
        return total * 0.1
    return 0


def clamp_value(value, low, high):
    return max(low, min(high, value))
'''

MID = '''"""Moderately branching code."""


def classify_order(total, items, vip):
    if total > 100 and items > 3:
        if vip:
            return "priority"
        return "bulk"
    if total > 50 or items > 1:
        for _ in range(items):
            if vip and total > 70:
                return "vip-split"
        return "standard"
    return "small"


def shipping_cost(weight, zone, express):
    cost = 5
    if weight > 10:
        cost += 3
    if zone == "far" and express:
        cost += 9
    elif zone == "far":
        cost += 4
    return cost
'''

NEAR_X = MID + "\n\n" + _debt(2)

EXEMPT = "".join(
    f"def forward_{name}(value):\n    return {target}(value)\n\n\n"
    for name, target in (
        ("a", "add_tax"),
        ("b", "label_for"),
        ("c", "total_price"),
        ("d", "clamp_value"),
        ("e", "classify_order"),
        ("f", "shipping_cost"),
    )
).rstrip() + "\n"

CALLEE = '''def compute(value):
    return value + 1
'''

CALLER = '''from gate.callee import compute


def run():
    return compute(2)
'''

CLEAN_FILLER = "".join(
    f"def helper_{{n}}_{k}(item):\n    return item + {k}\n\n\n" for k in range(40)
)

SPEC = {
    "language": "python",
    "module_dir": "gate",
    "files": {
        "gate/__init__.py": "",
        "gate/debt.py": DEBT,
        "gate/clean.py": CLEAN,
        "gate/mid.py": MID,
        "gate/near_x.py": NEAR_X,
        "gate/exempt.py": EXEMPT,
        "gate/callee.py": CALLEE,
        "gate/caller.py": CALLER,
    },
    "roles": {
        "debt": "gate/debt.py",
        "clean": "gate/clean.py",
        "mid": "gate/mid.py",
        "exempt": "gate/exempt.py",
        "near_x": "gate/near_x.py",
        "floor_exempt": "gate/callee.py",
    },
    "syntax_error": "def broken(:\n    return (\n",
    "edge_caller": "gate/caller.py",
    "edge_callee": "gate/callee.py",
    "edge_verdict": "resolved",
    "marker_comment": "# @generated\n",
    "generated_header": None,
    "long_comment": "# " + "x " * 3000 + "\n",
    "suppress_file": "# varde-ignore-file\n",
    "suppress_next_line": "# varde-ignore-next-line\n",
    "test_paths": ("tests/test_debt.py", "gate/debt_test.py"),
    "ext": "py",
    "filler_clean": CLEAN_FILLER,
    "filler_tiny": "def value_{n}(item):\n    return item + {n}\n",
}
