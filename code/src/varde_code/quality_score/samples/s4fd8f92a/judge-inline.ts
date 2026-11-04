type CatalogEntry = { price: number; stock: number };
type OrderInput = { id: string; items: Array<{ sku: string; quantity: number }> };
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

export function processOrder(input: unknown, source: unknown): OrderResult {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) throw new Error('Invalid order: expected an object');
  const order = input as Record<string, unknown>;
  if (typeof order.id !== 'string' || order.id.trim() === '') throw new Error('Invalid order id');
  if (!Array.isArray(order.items) || order.items.length === 0) throw new Error('Invalid items: expected a nonempty array');
  if (typeof source !== 'object' || source === null || Array.isArray(source)) throw new Error('Invalid catalog: expected an object');
  const catalog = source as Record<string, CatalogEntry>;
  const seen: Record<string, boolean> = {};
  const rows: PricedItem[] = [];
  let subtotal = 0;

  for (const raw of order.items as unknown[]) {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw new Error('Invalid item: expected an object');
    const item = raw as Record<string, unknown>;
    const sku = item.sku;
    const quantity = item.quantity;
    if (typeof sku !== 'string' || sku.trim() === '') throw new Error('Invalid item sku');
    if (!Number.isInteger(quantity) || (quantity as number) <= 0) throw new Error(`Invalid quantity for ${sku}`);
    if (seen[sku]) throw new Error(`Duplicate sku ${sku}`);
    seen[sku] = true;
    const entry = catalog[sku];
    if (!entry) throw new Error(`Unknown sku ${sku}`);
    if (typeof entry.price !== 'number' || !Number.isFinite(entry.price) || entry.price <= 0) throw new Error(`Invalid price for ${sku}`);
    if (!Number.isInteger(entry.stock) || entry.stock < 0) throw new Error(`Invalid stock for ${sku}`);
    if ((quantity as number) > entry.stock) throw new Error(`Quantity exceeds stock for ${sku}`);
    const lineTotal = Math.round((entry.price * (quantity as number) + Number.EPSILON) * 100) / 100;
    rows.push({ sku, quantity: quantity as number, unitPrice: entry.price, lineTotal });
    subtotal = Math.round((subtotal + lineTotal + Number.EPSILON) * 100) / 100;
  }

  let discount = 0;
  if (subtotal >= 100) {
    discount = Math.round((subtotal * 0.1 + Number.EPSILON) * 100) / 100;
    if (subtotal >= 200) discount = Math.round((discount + Math.round((subtotal * 0.05 + Number.EPSILON) * 100) / 100 + Number.EPSILON) * 100) / 100;
  }
  const discountedSubtotal = Math.round((subtotal - discount + Number.EPSILON) * 100) / 100;
  const tax = Math.round((discountedSubtotal * 0.08 + Number.EPSILON) * 100) / 100;
  let shipping = 12;
  if (discountedSubtotal >= 150) shipping = 0;
  else if (discountedSubtotal >= 50) shipping = 5;
  const total = Math.round((discountedSubtotal + tax + shipping + Number.EPSILON) * 100) / 100;
  return { id: order.id, items: rows, subtotal, discount, tax, shipping, total };
}

export function formatOrderReport(result: OrderResult): string {
  const lines = [`Order ${result.id}`];
  for (const item of result.items) lines.push(`${item.sku} x${item.quantity}: $${item.lineTotal.toFixed(2)}`);
  lines.push(`Subtotal: $${result.subtotal.toFixed(2)}`);
  lines.push(`Discount: -$${result.discount.toFixed(2)}`);
  lines.push(`Tax: $${result.tax.toFixed(2)}`);
  lines.push(`Shipping: $${result.shipping.toFixed(2)}`);
  lines.push(`Total: $${result.total.toFixed(2)}`);
  return lines.join('\n');
}
