type CatalogEntry = { price: number; stock: number };
type OrderItem = { sku: string; quantity: number };
type OrderInput = { id: string; items: OrderItem[] };
type PricedItem = { sku: string; quantity: number; unitPrice: number; lineTotal: number };
type OrderResult = { id: string; items: PricedItem[]; subtotal: number; discount: number; tax: number; shipping: number; total: number };
type Catalog = Record<string, CatalogEntry>;

function money(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalid(message: string): never {
  throw new Error(message);
}

function readOrder(value: unknown): OrderInput {
  if (!isRecord(value)) invalid('Invalid order: expected an object');
  validateOrderFields(value);
  return value as unknown as OrderInput;
}

function validateOrderFields(order: Record<string, unknown>): void {
  if (typeof order.id !== 'string' || order.id.trim() === '') invalid('Invalid order id');
  if (!Array.isArray(order.items) || order.items.length === 0) invalid('Invalid items: expected a nonempty array');
}

function readCatalog(value: unknown): Catalog {
  if (!isRecord(value)) invalid('Invalid catalog: expected an object');
  return value as unknown as Catalog;
}

function validateSku(sku: unknown): asserts sku is string {
  if (typeof sku !== 'string' || sku.trim() === '') invalid('Invalid item sku');
}

function validateQuantity(quantity: unknown, sku: string): asserts quantity is number {
  if (!Number.isInteger(quantity) || (quantity as number) <= 0) invalid(`Invalid quantity for ${sku}`);
}

function validateRow(row: unknown): asserts row is Record<string, unknown> {
  if (!isRecord(row)) invalid('Invalid item: expected an object');
}

function validateUnique(sku: string, seen: Record<string, boolean>): void {
  if (seen[sku]) invalid(`Duplicate sku ${sku}`);
  seen[sku] = true;
}

function catalogEntry(sku: string, catalog: Catalog): CatalogEntry {
  const entry = catalog[sku];
  if (!entry) invalid(`Unknown sku ${sku}`);
  return entry;
}

function validatePrice(entry: CatalogEntry, sku: string): void {
  if (typeof entry.price !== 'number' || !Number.isFinite(entry.price) || entry.price <= 0) invalid(`Invalid price for ${sku}`);
}

function validateStock(entry: CatalogEntry, sku: string): void {
  if (!Number.isInteger(entry.stock) || entry.stock < 0) invalid(`Invalid stock for ${sku}`);
}

function validateAvailable(quantity: number, entry: CatalogEntry, sku: string): void {
  if (quantity > entry.stock) invalid(`Quantity exceeds stock for ${sku}`);
}

function makePricedItem(sku: string, quantity: number, entry: CatalogEntry): PricedItem {
  return { sku, quantity, unitPrice: entry.price, lineTotal: money(entry.price * quantity) };
}

function priceRow(value: unknown, catalog: Catalog, seen: Record<string, boolean>): PricedItem {
  validateRow(value);
  const sku = value.sku;
  validateSku(sku);
  return priceValidatedRow(value, sku, catalog, seen);
}

function priceValidatedRow(row: Record<string, unknown>, sku: string, catalog: Catalog, seen: Record<string, boolean>): PricedItem {
  const quantity = row.quantity;
  validateQuantity(quantity, sku);
  validateUnique(sku, seen);
  return buildPricedItem(sku, quantity, catalogEntry(sku, catalog));
}

function buildPricedItem(sku: string, quantity: number, entry: CatalogEntry): PricedItem {
  validatePrice(entry, sku);
  validateStock(entry, sku);
  validateAvailable(quantity, entry, sku);
  return makePricedItem(sku, quantity, entry);
}

function priceItems(order: OrderInput, catalog: Catalog): PricedItem[] {
  const seen: Record<string, boolean> = {};
  return (order.items as unknown[]).map(row => priceRow(row, catalog, seen));
}

function sumItems(items: PricedItem[]): number {
  return items.reduce((sum, item) => money(sum + item.lineTotal), 0);
}

function discountFor(subtotal: number): number {
  if (subtotal < 100) return 0;
  return money(money(subtotal * 0.1) + (subtotal >= 200 ? money(subtotal * 0.05) : 0));
}

function taxableAmount(subtotal: number, discount: number): number {
  return money(subtotal - discount);
}

function taxFor(taxable: number): number {
  return money(taxable * 0.08);
}

function shippingFor(amount: number): number {
  if (amount >= 150) return 0;
  if (amount >= 50) return 5;
  return 12;
}

function totalFor(taxable: number, tax: number, shipping: number): number {
  return money(taxable + tax + shipping);
}

function buildResult(order: OrderInput, items: PricedItem[]): OrderResult {
  const subtotal = sumItems(items);
  const discount = discountFor(subtotal);
  return finishResult(order.id, items, subtotal, discount);
}

function finishResult(id: string, items: PricedItem[], subtotal: number, discount: number): OrderResult {
  const taxable = taxableAmount(subtotal, discount);
  const tax = taxFor(taxable);
  const shipping = shippingFor(taxable);
  return { id, items, subtotal, discount, tax, shipping, total: totalFor(taxable, tax, shipping) };
}

export function processOrder(input: unknown, source: unknown): OrderResult {
  const order = readOrder(input);
  return buildResult(order, priceItems(order, readCatalog(source)));
}

function amountLabel(value: number): string {
  return `$${value.toFixed(2)}`;
}

function itemLabel(item: PricedItem): string {
  return `${item.sku} x${item.quantity}: ${amountLabel(item.lineTotal)}`;
}

function summaryLine(name: string, value: number): string {
  return `${name}: ${amountLabel(value)}`;
}

function reportLines(result: OrderResult): string[] {
  return [`Order ${result.id}`, ...result.items.map(itemLabel), ...summaryLines(result)];
}

function summaryLines(result: OrderResult): string[] {
  return [summaryLine('Subtotal', result.subtotal), discountLine(result.discount), summaryLine('Tax', result.tax), summaryLine('Shipping', result.shipping), summaryLine('Total', result.total)];
}

function discountLine(value: number): string {
  return `Discount: -${amountLabel(value)}`;
}

export function formatOrderReport(result: OrderResult): string {
  return reportLines(result).join('\n');
}
