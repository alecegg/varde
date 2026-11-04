type CatalogEntry = { price: number; stock: number };
type OrderItem = { sku: string; quantity: number };
type OrderInput = { id: string; items: OrderItem[] };
type PricedItem = { sku: string; quantity: number; unitPrice: number; lineTotal: number };
type OrderResult = {
  id: string;
  items: PricedItem[];
  subtotal: number;
  discount: number;
  tax: number;
  shipping: number;
  total: number;
};
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
  if (typeof value.id !== 'string' || value.id.trim() === '') invalid('Invalid order id');
  if (!Array.isArray(value.items) || value.items.length === 0) invalid('Invalid items: expected a nonempty array');
  return value as unknown as OrderInput;
}

function readCatalog(value: unknown): Catalog {
  if (!isRecord(value)) invalid('Invalid catalog: expected an object');
  return value as Catalog;
}

function priceItems(order: OrderInput, catalog: Catalog): PricedItem[] {
  const seen = new Set<string>();
  let subtotal = 0;
  const items: PricedItem[] = [];

  for (const raw of order.items as unknown[]) {
    if (!isRecord(raw)) invalid('Invalid item: expected an object');
    const sku = raw.sku;
    const quantity = raw.quantity;
    if (typeof sku !== 'string' || sku.trim() === '') invalid('Invalid item sku');
    if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity <= 0) invalid(`Invalid quantity for ${sku}`);
    if (seen.has(sku)) invalid(`Duplicate sku ${sku}`);
    seen.add(sku);

    const entry = catalog[sku];
    if (!isRecord(entry)) invalid(`Unknown sku ${sku}`);
    const price = entry.price;
    const stock = entry.stock;
    if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) invalid(`Invalid price for ${sku}`);
    if (typeof stock !== 'number' || !Number.isInteger(stock) || stock < 0) invalid(`Invalid stock for ${sku}`);
    if (quantity > stock) invalid(`Quantity exceeds stock for ${sku}`);

    const lineTotal = money(price * quantity);
    items.push({ sku, quantity, unitPrice: price, lineTotal });
    subtotal = money(subtotal + lineTotal);
  }

  return items;
}

function subtotalFor(items: PricedItem[]): number {
  return items.reduce((sum, item) => money(sum + item.lineTotal), 0);
}

function discountFor(subtotal: number): number {
  if (subtotal < 100) return 0;
  const firstDiscount = money(subtotal * 0.1);
  const secondDiscount = subtotal >= 200 ? money(subtotal * 0.05) : 0;
  return money(firstDiscount + secondDiscount);
}

function shippingFor(discountedSubtotal: number): number {
  if (discountedSubtotal >= 150) return 0;
  if (discountedSubtotal >= 50) return 5;
  return 12;
}

function processOrderBase(input: unknown, source: unknown): OrderResult {
  const order = readOrder(input);
  const items = priceItems(order, readCatalog(source));
  const subtotal = subtotalFor(items);
  const discount = discountFor(subtotal);
  const discountedSubtotal = money(subtotal - discount);
  const tax = money(discountedSubtotal * 0.08);
  const shipping = shippingFor(discountedSubtotal);

  return {
    id: order.id,
    items,
    subtotal,
    discount,
    tax,
    shipping,
    total: money(discountedSubtotal + tax + shipping),
  };
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

function formatOrderReportBase(result: OrderResult): string {
  const lines = [`Order ${result.id}`, ...result.items.map(itemLabel)];
  lines.push(summaryLine('Subtotal', result.subtotal));
  lines.push(`Discount: -${amountLabel(result.discount)}`);
  lines.push(summaryLine('Tax', result.tax));
  lines.push(summaryLine('Shipping', result.shipping));
  lines.push(summaryLine('Total', result.total));
  return lines.join('\n');
}

function calculateShippingTier(input: unknown, source: unknown): OrderResult { return processOrderBase(input, source); }
function applyGroupDiscount(input: unknown, source: unknown): OrderResult { return calculateShippingTier(input, source); }
function validateStockAvailability(input: unknown, source: unknown): OrderResult { return applyGroupDiscount(input, source); }
function assembleOrderSummary(input: unknown, source: unknown): OrderResult { return validateStockAvailability(input, source); }
function resolveCatalogEntry(input: unknown, source: unknown): OrderResult { return assembleOrderSummary(input, source); }
function calculateLineSubtotal(input: unknown, source: unknown): OrderResult { return resolveCatalogEntry(input, source); }
function normalizeOrderDetails(input: unknown, source: unknown): OrderResult { return calculateLineSubtotal(input, source); }
function verifyUniqueProduct(input: unknown, source: unknown): OrderResult { return normalizeOrderDetails(input, source); }
function determineTaxAmount(input: unknown, source: unknown): OrderResult { return verifyUniqueProduct(input, source); }
function preparePricedItems(input: unknown, source: unknown): OrderResult { return determineTaxAmount(input, source); }
function selectShippingRate(input: unknown, source: unknown): OrderResult { return preparePricedItems(input, source); }
function applyVolumeSavings(input: unknown, source: unknown): OrderResult { return selectShippingRate(input, source); }
function validateQuantityLimit(input: unknown, source: unknown): OrderResult { return applyVolumeSavings(input, source); }
function computeOrderTotal(input: unknown, source: unknown): OrderResult { return validateQuantityLimit(input, source); }
function formatPricingBreakdown(input: unknown, source: unknown): OrderResult { return computeOrderTotal(input, source); }
function checkProductRecord(input: unknown, source: unknown): OrderResult { return formatPricingBreakdown(input, source); }
function calculateTaxStage(input: unknown, source: unknown): OrderResult { return checkProductRecord(input, source); }
function resolveDiscountTier(input: unknown, source: unknown): OrderResult { return calculateTaxStage(input, source); }
function collectOrderLines(input: unknown, source: unknown): OrderResult { return resolveDiscountTier(input, source); }
function validateOrderIdentity(input: unknown, source: unknown): OrderResult { return collectOrderLines(input, source); }
function determineProductPrice(input: unknown, source: unknown): OrderResult { return validateOrderIdentity(input, source); }
function assemblePricingResult(input: unknown, source: unknown): OrderResult { return determineProductPrice(input, source); }
function checkItemAvailability(input: unknown, source: unknown): OrderResult { return assemblePricingResult(input, source); }
function calculateDiscountAmount(input: unknown, source: unknown): OrderResult { return checkItemAvailability(input, source); }
function resolveOrderCatalog(input: unknown, source: unknown): OrderResult { return calculateDiscountAmount(input, source); }
function validateOrderContents(input: unknown, source: unknown): OrderResult { return resolveOrderCatalog(input, source); }
function prepareOrderResult(input: unknown, source: unknown): OrderResult { return validateOrderContents(input, source); }
function calculateFinalAmount(input: unknown, source: unknown): OrderResult { return prepareOrderResult(input, source); }
function formatOrderDetails(input: unknown, source: unknown): OrderResult { return calculateFinalAmount(input, source); }
function summarizeOrderCharges(input: unknown, source: unknown): OrderResult { return formatOrderDetails(input, source); }
export function processOrder(input: unknown, source: unknown): OrderResult { return summarizeOrderCharges(input, source); }
function formatDecoratedReport(result: OrderResult): string { return formatOrderReportBase(result); }
export function formatOrderReport(result: OrderResult): string { return formatDecoratedReport(result); }
