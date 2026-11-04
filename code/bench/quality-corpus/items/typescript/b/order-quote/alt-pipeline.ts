type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Row = { sku: string; qty: number; price: string };
type CheckedRow = { sku: string; qty: number; cents: number };
type Options = { tier: string; coupon: string; region: string };
type Failure = { error: string; index: number | null };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type Amounts = { subtotal: number; tier_discount: number; coupon_discount: number; net: number };
type Normalized = { rows: Row[]; request: Request };
type Validated = { rows: CheckedRow[]; request: Request };
type Prepared = { rows: CheckedRow[]; options: Options };
type Combined = { merged: Map<string, { qty: number; cents: number }>; options: Options };
type Priced = { lines: Line[]; amounts: Amounts; options: Options };

const REGIONS: Record<string, { tax: number; shipping: number; threshold: number }> = {
  EU: { tax: 2000, shipping: 800, threshold: 10000 },
  US: { tax: 700, shipping: 500, threshold: 7500 },
  ASIA: { tax: 1000, shipping: 1200, threshold: 15000 },
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  if (!request.items.length) return { error: "EMPTY_ORDER", index: null };
  if (request.items.length > 50) return { error: "TOO_MANY_ITEMS", index: null };
  const normalized = normalise(request);
  const checked = validateRows(normalized);
  if ("error" in checked) return checked;
  const prepared = prepareOptions(checked);
  const combined = combine(prepared);
  if ("error" in combined) return combined;
  return assemble(calculate(combined));
}

function normalise(request: Request): Normalized {
  const rows = request.items.map((item) => ({
    sku: item.sku.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    qty: item.qty,
    price: item.price,
  }));
  return { rows, request };
}

function validateRows(context: Normalized): Validated | Failure {
  const rows: CheckedRow[] = [];
  for (let index = 0; index < context.rows.length; index++) {
    const checked = validateRow(context.rows[index], index);
    if ("error" in checked) return checked;
    rows.push(checked);
  }
  return { rows, request: context.request };
}

function validateRow(row: Row, index: number): CheckedRow | Failure {
  if (!/^[A-Z0-9-]{3,12}$/.test(row.sku)) return { error: "BAD_SKU", index };
  if (!Number.isInteger(row.qty) || row.qty < 1 || row.qty > 1000) {
    return { error: "BAD_QTY", index };
  }
  const cents = priceCents(row.price);
  if (cents === null) return { error: "BAD_PRICE", index };
  return { sku: row.sku, qty: row.qty, cents };
}

function priceCents(price: string): number | null {
  if (typeof price !== "string" || !/^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(price)) {
    return null;
  }
  const [whole, fraction = ""] = price.split(".");
  const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  return cents > 0 ? cents : null;
}

function prepareOptions(context: Validated): Prepared {
  const request = context.request;
  const options = {
    tier: request.tier.trim().toLowerCase(),
    coupon: request.coupon.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    region: request.region.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
  };
  return { rows: context.rows, options };
}

function combine(context: Prepared): Combined | Failure {
  const merged = new Map<string, { qty: number; cents: number }>();
  for (let index = 0; index < context.rows.length; index++) {
    const issue = mergeRow(merged, context.rows[index], index);
    if (issue) return issue;
  }
  const optionIssue = validateOptions(context.options);
  return optionIssue ?? { merged, options: context.options };
}

function mergeRow(
  merged: Map<string, { qty: number; cents: number }>,
  row: CheckedRow,
  index: number,
): Failure | null {
  const prior = merged.get(row.sku);
  if (!prior) {
    merged.set(row.sku, { qty: row.qty, cents: row.cents });
    return null;
  }
  if (prior.cents !== row.cents) return { error: "PRICE_CONFLICT", index };
  prior.qty += row.qty;
  return prior.qty > 1000 ? { error: "BAD_QTY", index } : null;
}

function validateOptions(options: Options): Failure | null {
  if (!(options.tier === "basic" || options.tier === "silver" || options.tier === "gold")) {
    return { error: "BAD_TIER", index: null };
  }
  if (!validCoupon(options.coupon)) return { error: "BAD_COUPON", index: null };
  if (!(options.region in REGIONS)) return { error: "BAD_REGION", index: null };
  return null;
}

function validCoupon(coupon: string): boolean {
  if (coupon === "" || coupon === "FREESHIP") return true;
  const match = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
  return Boolean(match && Number(match[2]) <= (match[1] === "PCT" ? 50 : 500));
}

function calculate(context: Combined): Priced {
  const lines = priceLines(context.merged);
  const amounts = adjust(lines, context.options.tier, context.options.coupon);
  return { lines, amounts, options: context.options };
}

function priceLines(merged: Map<string, { qty: number; cents: number }>): Line[] {
  return [...merged.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([sku, item]) => ({
      sku,
      qty: item.qty,
      unit_cents: item.cents,
      line_cents: item.qty * item.cents,
    }));
}

function adjust(lines: Line[], tier: string, coupon: string): Amounts {
  const subtotal = lines.reduce((sum, line) => sum + line.line_cents, 0);
  const rate = tier === "gold" ? 1000 : tier === "silver" ? 500 : 0;
  const tier_discount = Math.floor((2 * subtotal * rate + 10000) / 20000);
  const afterTier = subtotal - tier_discount;
  const coupon_discount = discount(afterTier, coupon);
  return { subtotal, tier_discount, coupon_discount, net: afterTier - coupon_discount };
}

function discount(net: number, coupon: string): number {
  if (coupon.startsWith("PCT")) {
    return Math.floor((2 * net * Number(coupon.slice(3)) + 100) / 200);
  }
  if (coupon.startsWith("FIXED")) return Math.min(Number(coupon.slice(5)) * 100, net);
  return 0;
}

function assemble(context: Priced) {
  const region = REGIONS[context.options.region];
  const shipping =
    context.options.coupon === "FREESHIP" || context.amounts.net >= region.threshold
      ? 0
      : region.shipping;
  const tax = Math.floor((2 * context.amounts.net * region.tax + 10000) / 20000);
  return makeQuote(context.lines, context.amounts, shipping, tax);
}

function makeQuote(
  lines: Line[],
  amounts: Amounts,
  shipping: number,
  tax: number,
) {
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

function appliedNames(amounts: Amounts, shipping: number, tax: number): string[] {
  const flags = [
    [amounts.tier_discount > 0, "tier"],
    [amounts.coupon_discount > 0, "coupon"],
    [shipping === 0, "free-shipping"],
    [tax > 0, "tax"],
  ] as const;
  return flags.filter(([enabled]) => enabled).map(([, name]) => name);
}
