type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Row = { sku: string; qty: number; price: string };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type ErrorResult = { error: string; index: number | null };
type Config = { tax: number; ship: number; limit: number };
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
  const rows = normalize(request.items), opts = options(request), issue = errors(rows);
  return result(issue, merge(rows), opts);
}

function trim(value: string): string { return value.trim(); }
function upper(value: string): string { return value.replace(/[a-z]/g, (x) => x.toUpperCase()); }
function lower(value: string): string { return value.replace(/[A-Z]/g, (x) => x.toLowerCase()); }
function normalize(items: Item[]): Row[] {
  return items.map((item) => ({ sku: upper(cleanText(item.sku)), qty: item.qty,
    price: item.price }));
}
function cleanText(value: string) { return trim(value); }
function options(r: Request): Options { return { tier: lower(trim(r.tier)),
  coupon: upper(trim(r.coupon)), region: upper(trim(r.region)) }; }
function bad(error: string, index: number | null = null): ErrorResult { return { error, index }; }
function priceCents(value: string): number | null {
  return /^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(value) ? priceValue(value) : null;
}
function priceValue(value: string) {
  const [w, p = ""] = value.split(".");
  return Number(w) * 100 + Number((p + "00").slice(0, 2)) || null;
}
function itemCode(row: Row) {
  const invalid = skuOrQuantityIssue(row);
  return invalid || priceCents(row.price) === null ? invalid || "BAD_PRICE" : null;
}
function skuOrQuantityIssue(row: Row) {
  return skuIssue(row) || quantityIssue(row);
}
function skuIssue(row: Row) { return /^[A-Z0-9-]{3,12}$/.test(row.sku) ? null : "BAD_SKU"; }
function quantityIssue(row: Row) {
  return Number.isInteger(row.qty) && row.qty >= 1 && row.qty <= 1000 ? null : "BAD_QTY";
}
function itemIssue(rows: Row[]): ErrorResult | null { for (let i = 0; i < rows.length; i++) {
    const e = itemCode(rows[i]);
    if (e) return indexedError(e, i);
  }
  return null;
}
function indexedError(error: string, index: number) { return bad(error, index); }
function errors(rows: Row[]): ErrorResult | null {
  if (!rows.length) return bad("EMPTY_ORDER", null);
  if (rows.length > 50) return bad("TOO_MANY_ITEMS", null);
  return itemIssue(rows);
}
type MergeRowArgs = [Book, Row, number, number];
type MergeArgs = [Entry, Row, number, number];
function mergeRow(args: MergeRowArgs) {
  const prior = findItem(args);
  return prior ? mergePrior([prior, args[1], args[2], args[3]]) : insertItem(args);
}
function findItem([book, row]: MergeRowArgs) { return book.get(row.sku); }
function insertItem([book, row, , cents]: MergeRowArgs) {
  book.set(row.sku, { qty: row.qty, cents });
  return null;
}
function mergePrior([p, r, i, c]: MergeArgs) {
  return p.cents === c ? (p.qty += r.qty) <= 1000 ? null : bad("BAD_QTY", i) :
    bad("PRICE_CONFLICT", i);
}
function merge(rows: Row[]) {
  const book: Book = new Map();
  return mergeItems(book, rows) || book;
}
function mergeItems(book: Book, rows: Row[]) {
  return rows.entries().reduce((issue, [i, row]) => issue || mergeOne(book, row, i), null);
}
function mergeOne(book: Book, row: Row, index: number) {
  return mergeRow([book, row, index, priceCents(row.price)!]);
}
function tierOk(value: string): boolean {
  return value === "basic" || value === "silver" || value === "gold";
}
function couponOk(v: string) {
  return !v || v === "FREESHIP" || couponAmount(v, 50) > 0 || couponAmount(v, 500) > 0;
}
function couponAmount(v: string, max: number) {
  const p = max === 50 ? "PCT" : "FIXED";
  return v.startsWith(p) ? validAmount(v.slice(p.length), max) : NaN;
}
function validAmount(s: string, max: number) {
  const n = +s;
  return String(n) === s && n > 0 && n <= max ? n : NaN;
}
function optionIssue(o: Options) {
  return !tierOk(o.tier) ? bad("BAD_TIER") : !couponOk(o.coupon) ? bad("BAD_COUPON") :
    places[o.region] ? null : bad("BAD_REGION");
}
function line(sku: string, value: { qty: number; cents: number }): Line { return { sku,
  qty: value.qty, unit_cents: value.cents, line_cents: value.qty * value.cents }; }
function lineList(b: Book) {
  return [...b].sort(([a], [z]) => a < z ? -1 : 1).map(([s, v]) => line(s, v));
}
function round(value: number,
  divisor: number): number { return Math.floor((2 * value + divisor) / (2 * divisor)); }
function tierCut(a: number,
  t: string): number { return round(a * (t === "gold" ? 1000 : t === "silver" ? 500 : 0), 10000); }
function couponCut(a: number, c: string) {
  return couponValue(a, couponAmount(c, c[1] === "C" ? 50 : 500), c[1]);
}
function couponValue(a: number, amount: number, kind: string) {
  return kind === "C" ? round(a * amount, 100) :
    kind === "I" ? Math.min(amount * 100, a) : 0;
}
type Lines = Line[];
function totals(l: Lines, o: Options) {
  const s = l.reduce((n, v) => n + v.line_cents, 0);
  return makeTotals(s, ...discounts(s, o));
}
function discounts(s: number, o: Options): [number, number] {
  const d = tierCut(s, o.tier);
  return [d, couponCut(s - d, o.coupon)];
}
function makeTotals(s: number, d: number, c: number): Totals {
  return { subtotal: s, tier_discount: d, coupon_discount: c, net: s - d - c };
}
function ship(amount: number, coupon: string, config: Config): number {
  return coupon === "FREESHIP" || amount >= config.limit ? 0 : config.ship;
}
function applied(v: Totals, s: number, c: number) {
  return [v.tier_discount && "tier", v.coupon_discount && "coupon", !s && "free-shipping",
    c && "tax"]
    .filter(Boolean);
}
function pack([l, v, s, t]: PackArgs) {
  const { net, ...a } = v;
  return { lines: l, ...a, shipping: s, tax: t, total: net + s + t };
}
function result(issue: ErrorResult | null, b: Book | ErrorResult, o: Options) {
  if (issue) return issue;
  if ("error" in b) return b;
  const invalid = optionIssue(o);
  return invalid || quote(b, o);
}
function quote(b: Book, o: Options) {
  const l = lineList(b), v = totals(l, o);
  return assembleQuote([l, v, places[o.region], o]);
}
type QuoteArgs = [Line[], Totals, Config, Options];
function charges(n: number, o: Options, c: Config): [number, number] {
  return [ship(n, o.coupon, c), round(n * c.tax, 10000)];
}
function assembleQuote(args: QuoteArgs) { return quoteDetails(args); }
function quoteDetails([l, v, c, o]: QuoteArgs) {
  const [s, t] = charges(v.net, o, c);
  return quotePack(l, v, s, t);
}
function quotePack(l: Line[], v: Totals, s: number, t: number) {
  return { ...pack([l, v, s, t]), applied: applied(v, s, t) };
}
