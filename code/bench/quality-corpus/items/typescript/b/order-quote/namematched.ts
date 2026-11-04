type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Row = { sku: string; qty: number; price: string };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type ErrorResult = { error: string; index: number | null };
type Config = { tax: number; shippingCost: number; limit: number };
type Totals = { subtotal: number; tier_discount: number; coupon_discount: number; net: number };
type Options = { tier: string; coupon: string; region: string };
type Entry = { qty: number; cents: number };
type PackArgs = [Line[], Totals, number, number];
type Book = Map<string, Entry>;
const places: Record<string, Config> = {
  EU: { tax: 2000, ship: 800, limit: 10000 },
  US: { tax: 700, ship: 500, limit: 7500 },
  ASIA: { tax: 1000, ship: 1200, limit: 15000 },
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  const rows = normalizedItems(request.items), opts = normalizedOptions(request);
  const issue = itemErrors(rows);
  return validatedOrderQuote(issue, mergedItems(rows), opts);
}

function trimText(value: string): string { return value.trim(); }
function uppercaseAscii(value: string): string {
  return value.replace(/[a-z]/g, (x) => x.toUpperCase());
}
function lowercaseAscii(value: string): string {
  return value.replace(/[A-Z]/g, (x) => x.toLowerCase());
}
function normalizedItems(items: Item[]): Row[] {
  return items.map((item) => ({ sku: uppercaseAscii(trimmedText(item.sku)), qty: item.qty,
    price: item.price }));
}
function trimmedText(value: string) { return trimText(value); }
function normalizedOptions(r: Request): Options { return { tier: lowercaseAscii(trimText(r.tier)),
  coupon: uppercaseAscii(trimText(r.coupon)), region: uppercaseAscii(trimText(r.region)) }; }
function errorResult(error: string, index: number | null = null): ErrorResult {
  return { error, index };
}
function priceInCents(value: string): number | null {
  return /^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(value) ? decimalToCents(value) : null;
}
function decimalToCents(value: string) {
  const [w, p = ""] = value.split(".");
  return Number(w) * 100 + Number((p + "00").slice(0, 2)) || null;
}
function itemErrorCode(row: Row) {
  const invalid = skuOrQuantityError(row);
  return invalid || priceInCents(row.price) === null ? invalid || "BAD_PRICE" : null;
}
function skuOrQuantityError(row: Row) {
  return skuError(row) || quantityError(row);
}
function skuError(row: Row) { return /^[A-Z0-9-]{3,12}$/.test(row.sku) ? null : "BAD_SKU"; }
function quantityError(row: Row) {
  return Number.isInteger(row.qty) && row.qty >= 1 && row.qty <= 1000 ? null : "BAD_QTY";
}
function firstItemError(rows: Row[]): ErrorResult | null { for (let i = 0; i < rows.length; i++) {
    const e = itemErrorCode(rows[i]);
    if (e) return indexedErrorResult(e, i);
  }
  return null;
}
function indexedErrorResult(error: string, index: number) { return errorResult(error, index); }
function itemErrors(rows: Row[]): ErrorResult | null {
  if (!rows.length) return errorResult("EMPTY_ORDER", null);
  if (rows.length > 50) return errorResult("TOO_MANY_ITEMS", null);
  return firstItemError(rows);
}
type MergeRowArgs = [Book, Row, number, number];
type MergeArgs = [Entry, Row, number, number];
function mergeRowIntoBook(args: MergeRowArgs) {
  const prior = findBookItem(args);
  return prior ? mergePriorEntry([prior, args[1], args[2], args[3]]) : insertBookItem(args);
}
function findBookItem([book, row]: MergeRowArgs) { return book.get(row.sku); }
function insertBookItem([book, row, , cents]: MergeRowArgs) {
  book.set(row.sku, { qty: row.qty, cents });
  return null;
}
function mergePriorEntry([p, r, i, c]: MergeArgs) {
  return p.cents === c ? (p.qty += r.qty) <= 1000 ? null : errorResult("BAD_QTY", i) :
    errorResult("PRICE_CONFLICT", i);
}
function mergedItems(rows: Row[]) {
  const book: Book = new Map();
  return mergeAllItems(book, rows) || book;
}
function mergeAllItems(book: Book, rows: Row[]) {
  return rows.entries().reduce((issue, [i, row]) => issue || mergeOneItem(book, row, i), null);
}
function mergeOneItem(book: Book, row: Row, index: number) {
  return mergeRowIntoBook([book, row, index, priceInCents(row.price)!]);
}
function validTier(value: string): boolean {
  return value === "basic" || value === "silver" || value === "gold";
}
function validCoupon(v: string) {
  return !v || v === "FREESHIP" || couponAmountValue(v, 50) > 0 || couponAmountValue(v, 500) > 0;
}
function couponAmountValue(v: string, max: number) {
  const p = max === 50 ? "PCT" : "FIXED";
  return v.startsWith(p) ? validCouponAmount(v.slice(p.length), max) : NaN;
}
function validCouponAmount(s: string, max: number) {
  const n = +s;
  return String(n) === s && n > 0 && n <= max ? n : NaN;
}
function optionError(o: Options) {
  return !validTier(o.tier) ? errorResult("BAD_TIER") :
    !validCoupon(o.coupon) ? errorResult("BAD_COUPON") :
    places[o.region] ? null : errorResult("BAD_REGION");
}
function quoteLine(sku: string, value: { qty: number; cents: number }): Line { return { sku,
  qty: value.qty, unit_cents: value.cents, line_cents: value.qty * value.cents }; }
function sortedLines(b: Book) {
  return [...b].sort(([a], [z]) => a < z ? -1 : 1).map(([s, v]) => quoteLine(s, v));
}
function roundHalfUp(value: number,
  divisor: number): number { return Math.floor((2 * value + divisor) / (2 * divisor)); }
function tierDiscount(a: number,
  t: string): number {
  return roundHalfUp(a * (t === "gold" ? 1000 : t === "silver" ? 500 : 0), 10000);
}
function couponDiscount(a: number, c: string) {
  return couponDiscountValue(a, couponAmountValue(c, c[1] === "C" ? 50 : 500), c[1]);
}
function couponDiscountValue(a: number, amount: number, kind: string) {
  return kind === "C" ? roundHalfUp(a * amount, 100) :
    kind === "I" ? Math.min(amount * 100, a) : 0;
}
type Lines = Line[];
function quoteTotals(l: Lines, o: Options) {
  const s = l.reduce((n, v) => n + v.line_cents, 0);
  return makeQuoteTotals(s, ...discountParts(s, o));
}
function discountParts(s: number, o: Options): [number, number] {
  const d = tierDiscount(s, o.tier);
  return [d, couponDiscount(s - d, o.coupon)];
}
function makeQuoteTotals(s: number, d: number, c: number): Totals {
  return { subtotal: s, tier_discount: d, coupon_discount: c, net: s - d - c };
}
function shippingCost(amount: number, coupon: string, config: Config): number {
  return coupon === "FREESHIP" || amount >= config.limit ? 0 : config.ship;
}
function appliedAdjustments(v: Totals, s: number, c: number) {
  return [v.tier_discount && "tier", v.coupon_discount && "coupon", !s && "free-shipping",
    c && "tax"]
    .filter(Boolean);
}
function packQuote([l, v, s, t]: PackArgs) {
  const { net, ...a } = v;
  return { lines: l, ...a, shipping: s, tax: t, total: net + s + t };
}
function validatedOrderQuote(issue: ErrorResult | null, b: Book | ErrorResult, o: Options) {
  if (issue) return issue;
  if ("error" in b) return b;
  const invalid = optionError(o);
  return invalid || pricedQuote(b, o);
}
function pricedQuote(b: Book, o: Options) {
  const l = sortedLines(b), v = quoteTotals(l, o);
  return assembleQuoteDetails([l, v, places[o.region], o]);
}
type QuoteArgs = [Line[], Totals, Config, Options];
function quoteCharges(n: number, o: Options, c: Config): [number, number] {
  return [shippingCost(n, o.coupon, c), roundHalfUp(n * c.tax, 10000)];
}
function assembleQuoteDetails(args: QuoteArgs) { return finalQuoteDetails(args); }
function finalQuoteDetails([l, v, c, o]: QuoteArgs) {
  const [s, t] = quoteCharges(v.net, o, c);
  return quotePackWithAdjustments(l, v, s, t);
}
function quotePackWithAdjustments(l: Line[], v: Totals, s: number, t: number) {
  return { ...packQuote([l, v, s, t]), applied: appliedAdjustments(v, s, t) };
}
