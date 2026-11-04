type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type OrderItem = { sku: string; qty: number; price: string; cents: number | null };
type Order = { items: OrderItem[]; tier: string; coupon: string; region: string };
type Failure = { error: string; index: number | null };
type Merged = Map<string, { qty: number; cents: number }>;
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type Adjustment = { name: string; cents: number; active: boolean };
type Quote = {
  lines: Line[];
  subtotal: number;
  tier_discount: number;
  coupon_discount: number;
  shipping: number;
  tax: number;
  total: number;
  applied: string[];
};
type Region = { taxRate: number; shipping: number; threshold: number };

const REGIONS: Record<string, Region> = {
  EU: { taxRate: 2000, shipping: 800, threshold: 10000 },
  US: { taxRate: 700, shipping: 500, threshold: 7500 },
  ASIA: { taxRate: 1000, shipping: 1200, threshold: 15000 },
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  const order = normalise(request);
  const countIssue = checkItemCount(order);
  if (countIssue) return countIssue;
  const itemIssue = validateItems(order.items);
  if (itemIssue) return itemIssue;
  const merged = mergeItems(order.items);
  if ("error" in merged) return merged;
  const optionIssue = checkOptions(order);
  if (optionIssue) return optionIssue;
  return buildQuote(merged, order);
}

function normalise(request: Request): Order {
  const items = request.items.map((item) => ({
    sku: asciiUpper(item.sku.trim()),
    qty: item.qty,
    price: item.price,
    cents: null,
  }));
  const tier = request.tier.trim().toLowerCase();
  const coupon = asciiUpper(request.coupon.trim());
  const region = asciiUpper(request.region.trim());
  return { items, tier, coupon, region };
}

function asciiUpper(value: string): string {
  return value.replace(/[a-z]/g, (letter) => letter.toUpperCase());
}

function checkItemCount(order: Order): Failure | null {
  const count = order.items.length;
  if (count === 0) return { error: "EMPTY_ORDER", index: null };
  if (count > 50) return { error: "TOO_MANY_ITEMS", index: null };
  return null;
}

function validateItems(items: OrderItem[]): Failure | null {
  for (let index = 0; index < items.length; index++) {
    const issue = validateItem(items[index], index);
    if (issue) return issue;
  }
  return null;
}

function validateItem(item: OrderItem, index: number): Failure | null {
  const skuIssue = validateSku(item.sku, index);
  if (skuIssue) return skuIssue;
  const quantityIssue = validateQuantity(item.qty, index);
  if (quantityIssue) return quantityIssue;
  const cents = priceCents(item.price);
  if (cents === null) return { error: "BAD_PRICE", index };
  item.cents = cents;
  return null;
}

function validateSku(sku: string, index: number): Failure | null {
  return /^[A-Z0-9-]{3,12}$/.test(sku) ? null : { error: "BAD_SKU", index };
}

function validateQuantity(quantity: number, index: number): Failure | null {
  const isInteger = Number.isInteger(quantity);
  const isInRange = quantity >= 1 && quantity <= 1000;
  return isInteger && isInRange ? null : { error: "BAD_QTY", index };
}

function priceCents(text: string): number | null {
  const decimalText = /^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(text);
  if (!decimalText) return null;
  const [whole, fraction = ""] = text.split(".");
  const wholeCents = Number(whole) * 100;
  const fractionalCents = Number((fraction + "00").slice(0, 2));
  const cents = wholeCents + fractionalCents;
  return cents > 0 ? cents : null;
}

function mergeItems(items: OrderItem[]): Merged | Failure {
  const merged: Merged = new Map();
  for (let index = 0; index < items.length; index++) {
    const issue = mergeDuplicate(merged, items[index], index);
    if (issue) return issue;
  }
  return merged;
}

function mergeDuplicate(merged: Merged, item: OrderItem, index: number): Failure | null {
  const cents = item.cents as number;
  const prior = merged.get(item.sku);
  if (!prior) {
    merged.set(item.sku, { qty: item.qty, cents });
    return null;
  }
  if (prior.cents !== cents) return { error: "PRICE_CONFLICT", index };
  const combinedQuantity = prior.qty + item.qty;
  if (combinedQuantity > 1000) return { error: "BAD_QTY", index };
  prior.qty = combinedQuantity;
  return null;
}

function checkOptions(order: Order): Failure | null {
  const knownTier = order.tier === "basic" || order.tier === "silver" || order.tier === "gold";
  if (!knownTier) return { error: "BAD_TIER", index: null };
  const couponIssue = checkCoupon(order.coupon);
  if (couponIssue) return couponIssue;
  if (!(order.region in REGIONS)) return { error: "BAD_REGION", index: null };
  return null;
}

function checkCoupon(coupon: string): Failure | null {
  const match = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
  const maximum = match?.[1] === "PCT" ? 50 : 500;
  const validValue = match !== null && Number(match[2]) <= maximum;
  const knownCode = coupon === "" || coupon === "FREESHIP" || validValue;
  return knownCode ? null : { error: "BAD_COUPON", index: null };
}

function buildQuote(merged: Merged, order: Order): Quote {
  const lines = makeLines(merged);
  let subtotal = 0;
  for (const line of lines) {
    subtotal += line.line_cents;
  }
  const tier = tierAdjustment(subtotal, order.tier);
  const afterTier = subtotal - tier.cents;
  const coupon = couponAdjustment(afterTier, order.coupon);
  const net = afterTier - coupon.cents;
  return assembleQuote(lines, subtotal, tier, coupon, net, order);
}

function makeLines(merged: Merged): Line[] {
  const entries = [...merged.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  const lines: Line[] = [];
  for (const [sku, item] of entries) {
    const lineCents = item.qty * item.cents;
    lines.push({ sku, qty: item.qty, unit_cents: item.cents, line_cents: lineCents });
  }
  return lines;
}

function roundHalfUp(numerator: number, denominator: number): number {
  const doubledNumerator = 2 * numerator;
  const roundedNumerator = doubledNumerator + denominator;
  const roundedDenominator = 2 * denominator;
  return Math.floor(roundedNumerator / roundedDenominator);
}

function tierAdjustment(subtotal: number, tierName: string): Adjustment {
  const basisPoints = tierName === "gold" ? 1000 : tierName === "silver" ? 500 : 0;
  const numerator = subtotal * basisPoints;
  const cents = roundHalfUp(numerator, 10000);
  const active = cents > 0;
  return { name: "tier", cents, active };
}

function couponAdjustment(net: number, code: string): Adjustment {
  let cents = 0;
  if (code.startsWith("PCT")) {
    const rate = Number(code.slice(3));
    cents = roundHalfUp(net * rate, 100);
  } else if (code.startsWith("FIXED")) {
    const requested = Number(code.slice(5)) * 100;
    cents = Math.min(requested, net);
  }
  const active = cents > 0;
  return { name: "coupon", cents, active };
}

function shippingAdjustment(net: number, order: Order): Adjustment {
  const region = REGIONS[order.region];
  const qualifiesByTotal = net >= region.threshold;
  const qualifiesByCode = order.coupon === "FREESHIP";
  const waived = qualifiesByTotal || qualifiesByCode;
  const cents = waived ? 0 : region.shipping;
  return { name: "free-shipping", cents, active: waived };
}

function taxAdjustment(net: number, order: Order): Adjustment {
  const region = REGIONS[order.region];
  const numerator = net * region.taxRate;
  const cents = roundHalfUp(numerator, 10000);
  return { name: "tax", cents, active: cents > 0 };
}

function assembleQuote(
  lines: Line[],
  subtotal: number,
  tier: Adjustment,
  coupon: Adjustment,
  net: number,
  order: Order,
): Quote {
  const shipping = shippingAdjustment(net, order);
  const tax = taxAdjustment(net, order);
  const applied = collectApplied([tier, coupon, shipping, tax]);
  const total = net + shipping.cents + tax.cents;
  return {
    lines,
    subtotal,
    tier_discount: tier.cents,
    coupon_discount: coupon.cents,
    shipping: shipping.cents,
    tax: tax.cents,
    total,
    applied,
  };
}

function collectApplied(adjustments: Adjustment[]): string[] {
  const applied: string[] = [];
  for (const adjustment of adjustments) {
    if (adjustment.active) applied.push(adjustment.name);
  }
  return applied;
}

