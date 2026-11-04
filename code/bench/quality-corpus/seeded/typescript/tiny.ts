type CatalogEntry = { price: number; stock: number };
type OrderItem = { sku: string; quantity: number };
type OrderInput = { id: string; items: OrderItem[] };
type PricedItem = { sku: string; quantity: number; unitPrice: number; lineTotal: number };
type OrderResult = { id: string; items: PricedItem[]; subtotal: number; discount: number; tax: number; shipping: number; total: number };
type Catalog = Record<string, CatalogEntry>;

function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function fail(message: string): never { throw new Error(message); }
function round(value: number): number { return Math.round((value + Number.EPSILON) * 100) / 100; }
function nonblank(value: unknown): value is string { return typeof value === 'string' && value.trim() !== ''; }
function list(value: unknown): value is unknown[] { return Array.isArray(value); }
function requireOrder(value: unknown): Record<string, unknown> { if (!record(value)) fail('Invalid order: expected an object'); return value; }
function requireOrderId(value: unknown): string { if (!nonblank(value)) fail('Invalid order id'); return value; }
function requireOrderItems(value: unknown): unknown[] { if (!list(value) || value.length === 0) fail('Invalid items: expected a nonempty array'); return value; }
function parseOrder(value: unknown): OrderInput { const row = requireOrder(value); return { id: requireOrderId(row.id), items: requireOrderItems(row.items) as OrderItem[] }; }
function requireCatalog(value: unknown): Catalog { if (!record(value)) fail('Invalid catalog: expected an object'); return value as Catalog; }
function requireItem(value: unknown): Record<string, unknown> { if (!record(value)) fail('Invalid item: expected an object'); return value; }
function requireSku(value: unknown): string { if (!nonblank(value)) fail('Invalid item sku'); return value; }
function requireQuantity(value: unknown, sku: string): number { if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) fail(`Invalid quantity for ${sku}`); return value; }
function ensureFresh(seen: Set<string>, sku: string): void { if (seen.has(sku)) fail(`Duplicate sku ${sku}`); seen.add(sku); }
function requireProduct(catalog: Catalog, sku: string): CatalogEntry { const value = catalog[sku]; if (!record(value)) fail(`Unknown sku ${sku}`); return value as unknown as CatalogEntry; }
function requirePrice(value: unknown, sku: string): number { if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) fail(`Invalid price for ${sku}`); return value; }
function requireStock(value: unknown, sku: string): number { if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) fail(`Invalid stock for ${sku}`); return value; }
function ensureAvailable(quantity: number, stock: number, sku: string): void { if (quantity > stock) fail(`Quantity exceeds stock for ${sku}`); }
function lineAmount(price: number, quantity: number): number { return round(price * quantity); }
function makePricedItem(sku: string, quantity: number, price: number): PricedItem { return { sku, quantity, unitPrice: price, lineTotal: lineAmount(price, quantity) }; }
type CheckedLine = { sku: string; quantity: number };
function checkLineIdentity(value: unknown, seen: Set<string>): CheckedLine { const row = requireItem(value); const sku = requireSku(row.sku); const quantity = requireQuantity(row.quantity, sku); ensureFresh(seen, sku); return { sku, quantity }; }
function checkLineProduct(line: CheckedLine, catalog: Catalog): CatalogEntry { const product = requireProduct(catalog, line.sku); requirePrice(product.price, line.sku); requireStock(product.stock, line.sku); ensureAvailable(line.quantity, product.stock, line.sku); return product; }
function readPricedItem(value: unknown, catalog: Catalog, seen: Set<string>): PricedItem { const line = checkLineIdentity(value, seen); const product = checkLineProduct(line, catalog); const price = requirePrice(product.price, line.sku); return makePricedItem(line.sku, line.quantity, price); }
function appendItem(items: PricedItem[], value: PricedItem): void { items.push(value); }
function priceItems(order: OrderInput, catalog: Catalog): PricedItem[] { const items: PricedItem[] = []; const seen = new Set<string>(); for (const row of order.items as unknown[]) appendItem(items, readPricedItem(row, catalog, seen)); return items; }
function itemSubtotal(item: PricedItem): number { return item.lineTotal; }
function addMoney(left: number, right: number): number { return round(left + right); }
function subtotal(items: PricedItem[]): number { return items.reduce((sum, item) => addMoney(sum, itemSubtotal(item)), 0); }
function firstRate(amount: number): number { return amount >= 100 ? 0.1 : 0; }
function secondRate(amount: number): number { return amount >= 200 ? 0.05 : 0; }
function discountPiece(amount: number, rate: number): number { return round(amount * rate); }
function discount(amount: number): number { return round(discountPiece(amount, firstRate(amount)) + discountPiece(amount, secondRate(amount))); }
function afterDiscount(amount: number, cut: number): number { return round(amount - cut); }
function tax(amount: number): number { return round(amount * 0.08); }
function shipping(amount: number): number { if (amount >= 150) return 0; if (amount >= 50) return 5; return 12; }
function finalTotal(net: number, taxAmount: number, shippingAmount: number): number { return round(net + taxAmount + shippingAmount); }
type ChargeSummary = { subtotal: number; discount: number; net: number; tax: number; shipping: number; total: number };
function summarizeCharges(items: PricedItem[]): ChargeSummary { const amount = subtotal(items); const cut = discount(amount); const net = afterDiscount(amount, cut); const taxAmount = tax(net); const shippingAmount = shipping(net); return { subtotal: amount, discount: cut, net, tax: taxAmount, shipping: shippingAmount, total: finalTotal(net, taxAmount, shippingAmount) }; }
function makeResult(order: OrderInput, items: PricedItem[]): OrderResult { const charges = summarizeCharges(items); return { id: order.id, items, subtotal: charges.subtotal, discount: charges.discount, tax: charges.tax, shipping: charges.shipping, total: charges.total }; }
export function processOrder(input: unknown, source: unknown): OrderResult { const order = parseOrder(input); const items = priceItems(order, requireCatalog(source)); return makeResult(order, items); }
function cash(value: number): string { return `$${value.toFixed(2)}`; }
function itemText(item: PricedItem): string { return `${item.sku} x${item.quantity}: ${cash(item.lineTotal)}`; }
function summaryText(label: string, value: number): string { return `${label}: ${cash(value)}`; }
function appendSummary(lines: string[], label: string, value: number): void { lines.push(summaryText(label, value)); }
function reportItems(result: OrderResult): string[] { return result.items.map(itemText); }
function appendFirstAmounts(lines: string[], result: OrderResult): void { appendSummary(lines, 'Subtotal', result.subtotal); lines.push(`Discount: -${cash(result.discount)}`); appendSummary(lines, 'Tax', result.tax); }
function appendLastAmounts(lines: string[], result: OrderResult): void { appendSummary(lines, 'Shipping', result.shipping); appendSummary(lines, 'Total', result.total); }
function reportRows(result: OrderResult): string[] { const lines = [`Order ${result.id}`, ...reportItems(result)]; appendFirstAmounts(lines, result); appendLastAmounts(lines, result); return lines; }
export function formatOrderReport(result: OrderResult): string { return reportRows(result).join('\n'); }
