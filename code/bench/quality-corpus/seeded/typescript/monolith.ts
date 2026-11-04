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
  const orderData = input as Record<string, unknown>;
  if (typeof orderData.id !== 'string' || orderData.id.trim() === '') throw new Error('Invalid order id');
  if (!Array.isArray(orderData.items) || orderData.items.length === 0) throw new Error('Invalid items: expected a nonempty array');
  if (typeof source !== 'object' || source === null || Array.isArray(source)) throw new Error('Invalid catalog: expected an object');
  const id = orderData.id;
  const catalog = source as Catalog;
  const seen = new Set<string>();
  const items: PricedItem[] = [];
  for (const raw of orderData.items as unknown[]) {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw new Error('Invalid item: expected an object');
    const row = raw as Record<string, unknown>;
    const sku = row.sku;
    const quantity = row.quantity;
    if (typeof sku !== 'string' || sku.trim() === '') throw new Error('Invalid item sku');
    if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity <= 0) throw new Error(`Invalid quantity for ${sku}`);
    if (seen.has(sku)) throw new Error(`Duplicate sku ${sku}`);
    seen.add(sku);
    const product = catalog[sku];
    if (typeof product !== 'object' || product === null || Array.isArray(product)) throw new Error(`Unknown sku ${sku}`);
    const price = product.price;
    const stock = product.stock;
    if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) throw new Error(`Invalid price for ${sku}`);
    if (typeof stock !== 'number' || !Number.isInteger(stock) || stock < 0) throw new Error(`Invalid stock for ${sku}`);
    if (quantity > stock) throw new Error(`Quantity exceeds stock for ${sku}`);
    const lineTotal = Math.round((price * quantity + Number.EPSILON) * 100) / 100;
    items.push({ sku, quantity, unitPrice: price, lineTotal });
  }
  const subtotal = items.reduce((sum, item) => Math.round((sum + item.lineTotal + Number.EPSILON) * 100) / 100, 0);
  const firstDiscount = subtotal >= 100 ? Math.round((subtotal * 0.1 + Number.EPSILON) * 100) / 100 : 0;
  const secondDiscount = subtotal >= 200 ? Math.round((subtotal * 0.05 + Number.EPSILON) * 100) / 100 : 0;
  const discount = Math.round((firstDiscount + secondDiscount + Number.EPSILON) * 100) / 100;
  const net = Math.round((subtotal - discount + Number.EPSILON) * 100) / 100;
  const tax = Math.round((net * 0.08 + Number.EPSILON) * 100) / 100;
  let shipping = 12;
  if (net >= 150) shipping = 0;
  else if (net >= 50) shipping = 5;
  return { id, items, subtotal, discount, tax, shipping, total: Math.round((net + tax + shipping + Number.EPSILON) * 100) / 100 };
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
