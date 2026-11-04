type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Checked = { sku: string; qty: number; cents: number; price: string };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type Amounts = { subtotal: number; tier_discount: number; coupon_discount: number; net: number };
type Failure = { error: string; index: number | null };
type Region = { taxRate: number; shipping: number; threshold: number };
type Merged = Map<string, { qty: number; cents: number }>;
type Options = { tier: string; coupon: string; region: string };

const REGIONS: Record<string, Region> = {
  EU: { taxRate: 2000, shipping: 800, threshold: 10000 },
  US: { taxRate: 700, shipping: 500, threshold: 7500 },
  ASIA: { taxRate: 1000, shipping: 1200, threshold: 15000 },
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  const items = normalise(request.items);
  if ("error" in items) return items;
  const options = normaliseOptions(request);
  const merged = mergeItems(items, options);
  if ("error" in merged) return merged;
  const lines = priceLines(merged);
  const amounts = adjust(lines, options.tier, options.coupon);
  return finish(lines, amounts, options.coupon, options.region);
}

function normalise(items: Item[]): Checked[] | Failure {
  if (!items.length) return { error: "EMPTY_ORDER", index: null };
  if (items.length > 50) return { error: "TOO_MANY_ITEMS", index: null };
  const checked = items.map((item) => ({
    ...item,
    sku: item.sku.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    cents: 0,
  }));
  for (let index = 0; index < checked.length; index++) {
    const issue = checkItem(checked[index], index);
    if (issue) return issue;
  }
  return checked;
}

function normaliseOptions(request: Request): Options {
  return {
    tier: request.tier.trim().toLowerCase(),
    coupon: request.coupon.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    region: request.region.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
  };
}

function checkItem(item: Checked, index: number): Failure | null {
  if (!/^[A-Z0-9-]{3,12}$/.test(item.sku)) return { error: "BAD_SKU", index };
  if (!Number.isInteger(item.qty) || item.qty < 1 || item.qty > 1000) {
    return { error: "BAD_QTY", index };
  }
  const cents = priceCents(item.price);
  if (cents === null) return { error: "BAD_PRICE", index };
  item.cents = cents;
  return null;
}

function priceCents(price: string): number | null {
  if (typeof price !== "string" || !/^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(price)) {
    return null;
  }
  const [whole, fraction = ""] = price.split(".");
  const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  return cents > 0 ? cents : null;
}

function mergeItems(items: Checked[], options: Options): Merged | Failure {
  const merged = new Map<string, { qty: number; cents: number }>();
  for (let index = 0; index < items.length; index++) {
    const issue = mergeOne(merged, items[index], index);
    if (issue) return issue;
  }
  const optionIssue = checkOptions(options.tier, options.coupon, options.region);
  return optionIssue ?? merged;
}

function mergeOne(merged: Merged, item: Checked, index: number): Failure | null {
  const prior = merged.get(item.sku);
  if (!prior) {
    merged.set(item.sku, { qty: item.qty, cents: item.cents });
    return null;
  }
  if (prior.cents !== item.cents) return { error: "PRICE_CONFLICT", index };
  prior.qty += item.qty;
  return prior.qty > 1000 ? { error: "BAD_QTY", index } : null;
}

function checkOptions(tier: string, coupon: string, region: string): Failure | null {
  if (!(tier === "basic" || tier === "silver" || tier === "gold")) {
    return { error: "BAD_TIER", index: null };
  }
  if (!validCoupon(coupon)) return { error: "BAD_COUPON", index: null };
  if (!(region in REGIONS)) return { error: "BAD_REGION", index: null };
  return null;
}

function validCoupon(coupon: string): boolean {
  if (coupon === "" || coupon === "FREESHIP") return true;
  const match = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
  return Boolean(match && Number(match[2]) <= (match[1] === "PCT" ? 50 : 500));
}

function priceLines(merged: Merged): Line[] {
  const ordered = [...merged.entries()].sort(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0,
  );
  return ordered.map(([sku, item]) => ({
    sku,
    qty: item.qty,
    unit_cents: item.cents,
    line_cents: item.qty * item.cents,
  }));
}

function adjust(lines: Line[], tier: string, coupon: string): Amounts {
  const subtotal = lines.reduce((sum, line) => sum + line.line_cents, 0);
  const rate = tier === "gold" ? 1000 : tier === "silver" ? 500 : 0;
  const tierDiscount = Math.floor((2 * subtotal * rate + 10000) / 20000);
  const afterTier = subtotal - tierDiscount;
  const couponDiscount = couponDiscountFor(afterTier, coupon);
  return {
    subtotal,
    tier_discount: tierDiscount,
    coupon_discount: couponDiscount,
    net: afterTier - couponDiscount,
  };
}

function couponDiscountFor(net: number, coupon: string): number {
  if (coupon.startsWith("PCT")) {
    return Math.floor((2 * net * Number(coupon.slice(3)) + 100) / 200);
  }
  if (coupon.startsWith("FIXED")) return Math.min(Number(coupon.slice(5)) * 100, net);
  return 0;
}

function finish(lines: Line[], amounts: Amounts, coupon: string, region: string) {
  const config = REGIONS[region];
  const freeShipping = coupon === "FREESHIP" || amounts.net >= config.threshold;
  const shipping = freeShipping ? 0 : config.shipping;
  const tax = Math.floor((2 * amounts.net * config.taxRate + 10000) / 20000);
  const applied = appliedRules(amounts, shipping, tax);
  return {
    lines,
    subtotal: amounts.subtotal,
    tier_discount: amounts.tier_discount,
    coupon_discount: amounts.coupon_discount,
    shipping,
    tax,
    total: amounts.net + shipping + tax,
    applied,
  };
}

function appliedRules(amounts: Amounts, shipping: number, tax: number): string[] {
  const applied: string[] = [];
  if (amounts.tier_discount > 0) applied.push("tier");
  if (amounts.coupon_discount > 0) applied.push("coupon");
  if (shipping === 0) applied.push("free-shipping");
  if (tax > 0) applied.push("tax");
  return applied;
}
