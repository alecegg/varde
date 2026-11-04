"""TypeScript (incl. TSX) snapshot sources (embedded strings)."""

from __future__ import annotations

_DEBT_BLOCK = (
    "  if ((a > {i} && b < {j}) || c == {i}) {{\n"
    "    for (let q = 0; q < a; q++) {{\n"
    "      if (q % 2 == 0 && b) {{\n"
    "        if (q > {i} || c) {{\n"
    "          r = r + q - {i};\n"
    "        }} else {{\n"
    "          r = r - 1;\n"
    "        }}\n"
    "      }} else if (q % 3 == 0) {{\n"
    "        r = r ? r * 2 : q;\n"
    "      }}\n"
    "    }}\n"
    "  }}\n"
)



def _debt(blocks: int) -> str:
    return (
        "export function x(a: number, b: number, c: number, d: number, "
        "e: number, f: number): number {\n  let r = 0;\n"
        + "".join(_DEBT_BLOCK.format(i=i, j=i + 5) for i in range(blocks))
        + "  return r;\n}\n"
    )


DEBT = _debt(14)

CLEAN = """// Small, clear helpers.
export function addTax(price: number, rate: number): number {
  return price + price * rate;
}

export function labelFor(count: number): string {
  if (count === 1) {
    return "item";
  }
  return "items";
}

export function totalPrice(prices: number[]): number {
  return prices.reduce((sum, price) => sum + price, 0);
}

export const clampValue = (value: number, low: number, high: number): number =>
  Math.max(low, Math.min(high, value));
"""

MID = """// Moderately branching code.
export function classifyOrder(total: number, items: number, vip: boolean): string {
  if (total > 100 && items > 3) {
    if (vip) {
      return "priority";
    }
    return "bulk";
  }
  if (total > 50 || items > 1) {
    for (let i = 0; i < items; i++) {
      if (vip && total > 70) {
        return "vip-split";
      }
    }
    return "standard";
  }
  return "small";
}

export function shippingCost(weight: number, zone: string, express: boolean): number {
  let cost = 5;
  if (weight > 10) {
    cost += 3;
  }
  if (zone === "far" && express) {
    cost += 9;
  } else if (zone === "far") {
    cost += 4;
  }
  return cost;
}
"""

NEAR_X = MID + "\n" + _debt(3)

EXEMPT = """export { addTax, labelFor, totalPrice, clampValue } from "./clean";
export { classifyOrder, shippingCost } from "./mid";
export { compute } from "./callee";
"""

CALLEE = """export function compute(value: number): number {
  return value + 1;
}
"""

CALLER = """import { compute } from "./callee";

export function run(): number {
  return compute(2);
}
"""

VIEW = """export function label(value: number): string {
  return String(value);
}

export const View = (props: { value: number }) => <span>{label(props.value)}</span>;
"""

CLEAN_FILLER = "".join(
    f"export function helper{{n}}x{k}(item: number): number {{\n  return item + {k};\n}}\n\n"
    for k in range(40)
)

SPEC = {
    "language": "typescript",
    "module_dir": "gate",
    "files": {
        "gate/debt.ts": DEBT,
        "gate/clean.ts": CLEAN,
        "gate/mid.ts": MID,
        "gate/near_x.ts": NEAR_X,
        "gate/exempt.ts": EXEMPT,
        "gate/callee.ts": CALLEE,
        "gate/caller.ts": CALLER,
        "gate/view.tsx": VIEW,
    },
    "roles": {
        "debt": "gate/debt.ts",
        "clean": "gate/clean.ts",
        "mid": "gate/mid.ts",
        "exempt": "gate/exempt.ts",
        "near_x": "gate/near_x.ts",
        "floor_exempt": "gate/callee.ts",
        "tsx": "gate/view.tsx",
    },
    "syntax_error": "export function broken(: number {\n  return (\n",
    "edge_caller": "gate/caller.ts",
    "edge_callee": "gate/callee.ts",
    "edge_verdict": "resolved",
    "marker_comment": "// @generated\n",
    "generated_header": None,
    "long_comment": "// " + "x " * 3000 + "\n",
    "suppress_file": "// varde-ignore-file\n",
    "suppress_next_line": "// varde-ignore-next-line\n",
    "test_paths": ("tests/debt.test.ts", "gate/debt.test.ts"),
    "ext": "ts",
    "filler_clean": CLEAN_FILLER,
    "filler_tiny": "export function value{n}(item: number): number {\n  return item + {n};\n}\n",
}
