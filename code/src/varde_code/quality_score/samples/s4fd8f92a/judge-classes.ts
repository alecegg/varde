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

interface DiscountPolicy {
  discount(subtotal: number): number;
}

interface ShippingPolicy {
  cost(discountedSubtotal: number): number;
}

class Money {
  static round(value: number): number {
    return Math.round((value + Number.EPSILON) * 100) / 100;
  }

  static label(value: number): string {
    return `$${value.toFixed(2)}`;
  }
}

class InputReader {
  static record(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  order(value: unknown): OrderInput {
    if (!InputReader.record(value)) throw new Error('Invalid order: expected an object');
    if (typeof value.id !== 'string' || value.id.trim() === '') throw new Error('Invalid order id');
    if (!Array.isArray(value.items) || value.items.length === 0) throw new Error('Invalid items: expected a nonempty array');
    return value as unknown as OrderInput;
  }

  catalog(value: unknown): Record<string, CatalogEntry> {
    if (!InputReader.record(value)) throw new Error('Invalid catalog: expected an object');
    return value as Record<string, CatalogEntry>;
  }
}

class Catalog {
  private readonly entries: Record<string, CatalogEntry>;

  constructor(entries: Record<string, CatalogEntry>) {
    this.entries = entries;
  }

  item(sku: string): CatalogEntry {
    const entry = this.entries[sku];
    if (!entry) throw new Error(`Unknown sku ${sku}`);
    if (typeof entry.price !== 'number' || !Number.isFinite(entry.price) || entry.price <= 0) {
      throw new Error(`Invalid price for ${sku}`);
    }
    if (!Number.isInteger(entry.stock) || entry.stock < 0) throw new Error(`Invalid stock for ${sku}`);
    return entry;
  }
}

class OrderItems {
  private readonly seen = new Set<string>();
  private readonly rows: PricedItem[] = [];
  private subtotal = 0;

  private readonly catalog: Catalog;

  constructor(catalog: Catalog) {
    this.catalog = catalog;
  }

  add(raw: unknown): void {
    if (!InputReader.record(raw)) throw new Error('Invalid item: expected an object');
    const sku = raw.sku;
    const quantity = raw.quantity;
    if (typeof sku !== 'string' || sku.trim() === '') throw new Error('Invalid item sku');
    if (!Number.isInteger(quantity) || (quantity as number) <= 0) throw new Error(`Invalid quantity for ${sku}`);
    if (this.seen.has(sku)) throw new Error(`Duplicate sku ${sku}`);
    this.seen.add(sku);
    const entry = this.catalog.item(sku);
    if ((quantity as number) > entry.stock) throw new Error(`Quantity exceeds stock for ${sku}`);
    const lineTotal = Money.round(entry.price * (quantity as number));
    this.rows.push({ sku, quantity: quantity as number, unitPrice: entry.price, lineTotal });
    this.subtotal = Money.round(this.subtotal + lineTotal);
  }

  result(): { items: PricedItem[]; subtotal: number } {
    return { items: this.rows, subtotal: this.subtotal };
  }
}

class ThresholdDiscount implements DiscountPolicy {
  discount(subtotal: number): number {
    if (subtotal < 100) return 0;
    let reduction = Money.round(subtotal * 0.1);
    if (subtotal >= 200) reduction = Money.round(reduction + Money.round(subtotal * 0.05));
    return reduction;
  }
}

class TieredShipping implements ShippingPolicy {
  cost(amount: number): number {
    if (amount >= 150) return 0;
    if (amount >= 50) return 5;
    return 12;
  }
}

class OrderProcessor {
  private readonly reader: InputReader;
  private readonly discountPolicy: DiscountPolicy;
  private readonly shippingPolicy: ShippingPolicy;

  constructor(
    reader = new InputReader(),
    discountPolicy: DiscountPolicy = new ThresholdDiscount(),
    shippingPolicy: ShippingPolicy = new TieredShipping(),
  ) {
    this.reader = reader;
    this.discountPolicy = discountPolicy;
    this.shippingPolicy = shippingPolicy;
  }

  process(input: unknown, source: unknown): OrderResult {
    const order = this.reader.order(input);
    const items = new OrderItems(new Catalog(this.reader.catalog(source)));
    for (const raw of order.items as unknown[]) items.add(raw);
    const priced = items.result();
    const discount = this.discountPolicy.discount(priced.subtotal);
    const taxable = Money.round(priced.subtotal - discount);
    const tax = Money.round(taxable * 0.08);
    const shipping = this.shippingPolicy.cost(taxable);
    return {
      id: order.id,
      items: priced.items,
      subtotal: priced.subtotal,
      discount,
      tax,
      shipping,
      total: Money.round(taxable + tax + shipping),
    };
  }
}

class OrderReport {
  format(result: OrderResult): string {
    const lines = [`Order ${result.id}`];
    for (const item of result.items) lines.push(`${item.sku} x${item.quantity}: ${Money.label(item.lineTotal)}`);
    lines.push(`Subtotal: ${Money.label(result.subtotal)}`);
    lines.push(`Discount: -${Money.label(result.discount)}`);
    lines.push(`Tax: ${Money.label(result.tax)}`);
    lines.push(`Shipping: ${Money.label(result.shipping)}`);
    lines.push(`Total: ${Money.label(result.total)}`);
    return lines.join('\n');
  }
}

const processor = new OrderProcessor();
const report = new OrderReport();

export function processOrder(input: unknown, catalog: unknown): OrderResult {
  return processor.process(input, catalog);
}

export function formatOrderReport(result: OrderResult): string {
  return report.format(result);
}
