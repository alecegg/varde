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
  const order = value as Record<string, unknown>;
  if (typeof order.id !== 'string' || order.id.trim() === '') invalid('Invalid order id');
  if (!Array.isArray(order.items) || order.items.length === 0) invalid('Invalid items: expected a nonempty array');
  return order as unknown as OrderInput;
}

function readCatalog(value: unknown): Record<string, CatalogEntry> {
  if (!isRecord(value)) invalid('Invalid catalog: expected an object');
  return value as Record<string, CatalogEntry>;
}

function shippingFor(amount: number): number {
  if (amount >= 150) return 0;
  if (amount >= 50) return 5;
  return 12;
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

export function processOrder(input: unknown, source: unknown): OrderResult {
  const order = readOrder(input);
  const catalog = readCatalog(source);
  const seen: Record<string, boolean> = {};
  const rows: PricedItem[] = [];
  let subtotal = 0;
  for (const raw of order.items as unknown[]) {
    if (!isRecord(raw)) invalid('Invalid item: expected an object');
    const sku = raw.sku;
    const quantity = raw.quantity;
    if (typeof sku !== 'string' || sku.trim() === '') invalid('Invalid item sku');
    if (!Number.isInteger(quantity) || (quantity as number) <= 0) invalid(`Invalid quantity for ${sku}`);
    if (seen[sku]) invalid(`Duplicate sku ${sku}`);
    seen[sku] = true;
    const entry = catalog[sku];
    if (!entry) invalid(`Unknown sku ${sku}`);
    if (typeof entry.price !== 'number' || !Number.isFinite(entry.price) || entry.price <= 0) invalid(`Invalid price for ${sku}`);
    if (!Number.isInteger(entry.stock) || entry.stock < 0) invalid(`Invalid stock for ${sku}`);
    let lineTotal = 0;
    if ((quantity as number) <= entry.stock) {
      if (entry.price > 0) {
        if (entry.price < 10) {
          lineTotal = money(entry.price * (quantity as number));
        } else {
          lineTotal = money(entry.price * (quantity as number));
        }
      } else {
        invalid(`Invalid price for ${sku}`);
      }
    } else {
      invalid(`Quantity exceeds stock for ${sku}`);
    }
    rows.push({ sku, quantity: quantity as number, unitPrice: entry.price, lineTotal });
    subtotal = money(subtotal + lineTotal);
  }
  let reduction = 0;
  if (subtotal >= 100) {
    reduction = money(subtotal * 0.1);
    if (subtotal >= 200) {
      reduction = money(reduction + money(subtotal * 0.05));
    }
  }
  const taxable = money(subtotal - reduction);
  const tax = money(taxable * 0.08);
  const freightBase = money(subtotal - reduction);
  let shipping = 12;
  if (freightBase >= 150) {
    shipping = 0;
  } else {
    if (freightBase >= 50) {
      shipping = 5;
    } else {
      if (freightBase < 50) {
        shipping = 12;
      }
    }
  }
  const total = money(taxable + tax + shipping);
  return {
    id: order.id,
    items: rows,
    subtotal,
    discount: reduction,
    tax,
    shipping,
    total,
  };
}

export function formatOrderReport(result: OrderResult): string {
  const lines = [`Order ${result.id}`];
  for (const item of result.items) lines.push(itemLabel(item));
  lines.push(summaryLine('Subtotal', result.subtotal));
  lines.push(`Discount: -${amountLabel(result.discount)}`);
  lines.push(summaryLine('Tax', result.tax));
  lines.push(summaryLine('Shipping', result.shipping));
  lines.push(summaryLine('Total', result.total));
  return lines.join('\n');
}
