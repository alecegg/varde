type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type CheckedItem = { sku: string; qty: number; cents: number };
type Failure = { error: string; index: number | null };
type Result<T> = { ok: true; value: T } | { ok: false; failure: Failure };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type Options = { tier: string; coupon: string; region: string };
type Merged = Map<string, { qty: number; cents: number }>;
type Rule<T> = [(value: T) => boolean, string];

const REGIONS: Record<string, { tax: number; shipping: number; threshold: number }> = {
  EU: { tax: 2000, shipping: 800, threshold: 10000 },
  US: { tax: 700, shipping: 500, threshold: 7500 },
  ASIA: { tax: 1000, shipping: 1200, threshold: 15000 },
};
const PRICE_TEXT = /^[0-9]{1,6}(\.[0-9]{1,2})?$/;
const ROW_RULES: Rule<Item>[] = [
  [(row) => !/^[A-Z0-9-]{3,12}$/.test(row.sku), "BAD_SKU"],
  [(row) => !Number.isInteger(row.qty) || row.qty < 1 || row.qty > 1000, "BAD_QTY"],
  [(row) => typeof row.price !== "string" || !PRICE_TEXT.test(row.price), "BAD_PRICE"],
];
const OPTION_RULES: Rule<Options>[] = [
  [
    (options) =>
      !(options.tier === "basic" || options.tier === "silver" || options.tier === "gold"),
    "BAD_TIER",
  ],
  [
    (options) => {
      const coupon = options.coupon;
      if (coupon === "" || coupon === "FREESHIP") return false;
      const match = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
      return !match || Number(match[2]) > (match[1] === "PCT" ? 50 : 500);
    },
    "BAD_COUPON",
  ],
  [(options) => !(options.region in REGIONS), "BAD_REGION"],
];

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  if (!request.items.length) return { error: "EMPTY_ORDER", index: null };
  if (request.items.length > 50) return { error: "TOO_MANY_ITEMS", index: null };
  const rows = normalise(request);
  const checked = validateRows(rows);
  if (!checked.ok) return checked.failure;
  const options = normaliseOptions(request);
  const merged = merge(checked.value);
  if (!merged.ok) return merged.failure;
  const optionIssue = firstRule(options, OPTION_RULES);
  if (optionIssue) return { error: optionIssue, index: null };
  return result(merged.value, options);
}

function normalise(request: Request): Item[] {
  return request.items.map((item) => ({
    sku: item.sku.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    qty: item.qty,
    price: item.price,
  }));
}

function normaliseOptions(request: Request): Options {
  return {
    tier: request.tier.trim().toLowerCase(),
    coupon: request.coupon.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    region: request.region.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
  };
}

function validateRows(rows: Item[]): Result<CheckedItem[]> {
  const checked: CheckedItem[] = [];
  for (let index = 0; index < rows.length; index++) {
    const item = validateRow(rows[index], index);
    if (!item.ok) return item;
    checked.push(item.value);
  }
  return { ok: true, value: checked };
}

function validateRow(row: Item, index: number): Result<CheckedItem> {
  const issue = firstRule(row, ROW_RULES);
  if (issue) return { ok: false, failure: { error: issue, index } };
  const [whole, fraction = ""] = row.price.split(".");
  const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  if (!cents) return { ok: false, failure: { error: "BAD_PRICE", index } };
  return { ok: true, value: { sku: row.sku, qty: row.qty, cents } };
}

function firstRule<T>(value: T, rules: Rule<T>[]): string | null {
  for (const [invalid, code] of rules) if (invalid(value)) return code;
  return null;
}

function merge(rows: CheckedItem[]): Result<Merged> {
  const merged: Merged = new Map();
  for (let index = 0; index < rows.length; index++) {
    const issue = mergeOne(merged, rows[index], index);
    if (issue) return { ok: false, failure: issue };
  }
  return { ok: true, value: merged };
}

function mergeOne(merged: Merged, row: CheckedItem, index: number): Failure | null {
  const prior = merged.get(row.sku);
  if (prior && prior.cents !== row.cents) return { error: "PRICE_CONFLICT", index };
  const qty = row.qty + (prior?.qty ?? 0);
  if (qty > 1000) return { error: "BAD_QTY", index };
  merged.set(row.sku, { qty, cents: row.cents });
  return null;
}

function result(merged: Merged, options: Options) {
  const lines = linesFrom(merged);
  const amounts = calculate(lines, options.tier, options.coupon);
  const region = REGIONS[options.region];
  const shipping =
    options.coupon === "FREESHIP" || amounts.net >= region.threshold ? 0 : region.shipping;
  const tax = Math.floor((2 * amounts.net * region.tax + 10000) / 20000);
  return {
    lines,
    subtotal: amounts.subtotal,
    tier_discount: amounts.tier_discount,
    coupon_discount: amounts.coupon_discount,
    shipping,
    tax,
    total: amounts.net + shipping + tax,
    applied: appliedNames(amounts, shipping, tax),
  };
}

function linesFrom(merged: Merged): Line[] {
  return [...merged.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([sku, item]) => ({
      sku,
      qty: item.qty,
      unit_cents: item.cents,
      line_cents: item.qty * item.cents,
    }));
}

function calculate(lines: Line[], tier: string, coupon: string) {
  const subtotal = lines.reduce((sum, line) => sum + line.line_cents, 0);
  const rate = tier === "gold" ? 1000 : tier === "silver" ? 500 : 0;
  const tier_discount = Math.floor((2 * subtotal * rate + 10000) / 20000);
  const afterTier = subtotal - tier_discount;
  const coupon_discount = discount(afterTier, coupon);
  return { subtotal, tier_discount, coupon_discount, net: afterTier - coupon_discount };
}

function discount(amount: number, coupon: string): number {
  if (coupon.startsWith("PCT")) {
    return Math.floor((2 * amount * Number(coupon.slice(3)) + 100) / 200);
  }
  if (coupon.startsWith("FIXED")) return Math.min(Number(coupon.slice(5)) * 100, amount);
  return 0;
}

function appliedNames(
  amounts: ReturnType<typeof calculate>,
  shipping: number,
  tax: number,
): string[] {
  const enabled = [
    [amounts.tier_discount > 0, "tier"],
    [amounts.coupon_discount > 0, "coupon"],
    [shipping === 0, "free-shipping"],
    [tax > 0, "tax"],
  ] as const;
  return enabled.filter(([active]) => active).map(([, name]) => name);
}
