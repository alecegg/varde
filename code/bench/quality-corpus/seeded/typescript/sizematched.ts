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

export function processOrder(input: unknown, source: unknown): OrderResult {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) throw new Error('Invalid order: expected an object');
  const rawOrder = input as Record<string, unknown>;
  if (typeof rawOrder.id !== 'string' || rawOrder.id.trim() === '') throw new Error('Invalid order id');
  if (!Array.isArray(rawOrder.items) || rawOrder.items.length === 0) throw new Error('Invalid items: expected a nonempty array');
  if (typeof source !== 'object' || source === null || Array.isArray(source)) throw new Error('Invalid catalog: expected an object');

  const order = rawOrder as unknown as OrderInput;
  const catalog = source as Catalog;
  const used = new Set<string>();
  const priced: PricedItem[] = [];
  let sum = 0;
  for (const candidate of order.items as unknown[]) {
    if (typeof candidate !== 'object' || candidate === null || Array.isArray(candidate)) throw new Error('Invalid item: expected an object');
    const item = candidate as Record<string, unknown>;
    const code = item.sku;
    const count = item.quantity;
    if (typeof code !== 'string' || code.trim() === '') throw new Error('Invalid item sku');
    if (typeof count !== 'number' || !Number.isInteger(count) || count <= 0) throw new Error(`Invalid quantity for ${code}`);
    if (used.has(code)) throw new Error(`Duplicate sku ${code}`);
    used.add(code);
    const record = catalog[code];
    if (typeof record !== 'object' || record === null || Array.isArray(record)) throw new Error(`Unknown sku ${code}`);
    const cost = (record as CatalogEntry).price;
    const available = (record as CatalogEntry).stock;
    if (typeof cost !== 'number' || !Number.isFinite(cost) || cost <= 0) throw new Error(`Invalid price for ${code}`);
    if (typeof available !== 'number' || !Number.isInteger(available) || available < 0) throw new Error(`Invalid stock for ${code}`);
    if (count > available) throw new Error(`Quantity exceeds stock for ${code}`);
    const extended = Math.round((cost * count + Number.EPSILON) * 100) / 100;
    priced.push({ sku: code, quantity: count, unitPrice: cost, lineTotal: extended });
    sum = Math.round((sum + extended + Number.EPSILON) * 100) / 100;
  }

  const subtotal = priced.reduce((running, line) => Math.round((running + line.lineTotal + Number.EPSILON) * 100) / 100, 0);
  let discount = 0;
  if (subtotal >= 100) {
    const baseCut = Math.round((subtotal * 0.1 + Number.EPSILON) * 100) / 100;
    const extraCut = subtotal >= 200 ? Math.round((subtotal * 0.05 + Number.EPSILON) * 100) / 100 : 0;
    discount = Math.round((baseCut + extraCut + Number.EPSILON) * 100) / 100;
  }
  const afterDiscount = Math.round((subtotal - discount + Number.EPSILON) * 100) / 100;
  const tax = Math.round((afterDiscount * 0.08 + Number.EPSILON) * 100) / 100;
  let shipping = 12;
  if (afterDiscount >= 150) shipping = 0;
  else if (afterDiscount >= 50) shipping = 5;

  return {
    id: order.id,
    items: priced,
    subtotal,
    discount,
    tax,
    shipping,
    total: Math.round((afterDiscount + tax + shipping + Number.EPSILON) * 100) / 100,
  };
}

export function formatOrderReport(result: OrderResult): string {
  const rows = [`Order ${result.id}`];
  for (const entry of result.items) rows.push(`${entry.sku} x${entry.quantity}: $${entry.lineTotal.toFixed(2)}`);
  rows.push(`Subtotal: $${result.subtotal.toFixed(2)}`);
  rows.push(`Discount: -$${result.discount.toFixed(2)}`);
  rows.push(`Tax: $${result.tax.toFixed(2)}`);
  rows.push(`Shipping: $${result.shipping.toFixed(2)}`);
  rows.push(`Total: $${result.total.toFixed(2)}`);
  return rows.join('\n');
}
