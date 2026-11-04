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

// Keep every pricing stage rounded to currency precision.
function money(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

// Restrict object reads to non-null, non-array records.
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Give validation failures a consistent exception type.
function invalid(message: string): never {
  throw new Error(message);
}

// Validate the top-level order before treating it as an order input.
function readOrder(value: unknown): OrderInput {
  // Reject non-record inputs before reading any properties.
  if (!isRecord(value)) invalid('Invalid order: expected an object');
  // Require a usable identifier and at least one row.
  if (typeof value.id !== 'string' || value.id.trim() === '') invalid('Invalid order id');
  if (!Array.isArray(value.items) || value.items.length === 0) invalid('Invalid items: expected a nonempty array');
  return value as unknown as OrderInput;
}

// Validate the catalog container before looking up SKUs.
function readCatalog(value: unknown): Record<string, unknown> {
  // Prevent unsafe indexing into non-object catalog values.
  if (!isRecord(value)) invalid('Invalid catalog: expected an object');
  return value;
}

// Select shipping from the discounted, pre-tax amount.
function shippingFor(amount: number): number {
  // Apply the free-shipping tier first, then the reduced tier.
  if (amount >= 150) return 0;
  if (amount >= 50) return 5;
  return 12;
}

// Format one monetary value consistently for the report.
function amountLabel(value: number): string {
  return `$${value.toFixed(2)}`;
}

// Render a priced row in a stable, readable form.
function itemLabel(item: PricedItem): string {
  return `${item.sku} x${item.quantity}: ${amountLabel(item.lineTotal)}`;
}

// Render a named amount in the report's standard format.
function summaryLine(name: string, value: number): string {
  return `${name}: ${amountLabel(value)}`;
}

// Validate and price one order from untrusted runtime values.
export function processOrder(input: unknown, source: unknown): OrderResult {
  // Validate both inputs before using their contents.
  const order = readOrder(input);
  const catalog = readCatalog(source);
  // Track SKUs and priced lines while accumulating rounded line totals.
  const seen = new Set<string>();
  const rows: PricedItem[] = [];
  let subtotal = 0;
  // Validate each row before catalog access and pricing.
  for (const raw of order.items as unknown[]) {
    // Require each item row to be a record.
    if (!isRecord(raw)) invalid('Invalid item: expected an object');
    const sku = raw.sku;
    const quantity = raw.quantity;
    // Require a nonblank SKU and a positive integer quantity.
    if (typeof sku !== 'string' || sku.trim() === '') invalid('Invalid item sku');
    if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity <= 0) invalid(`Invalid quantity for ${sku}`);
    // Reject repeated SKUs before processing their catalog data.
    if (seen.has(sku)) invalid(`Duplicate sku ${sku}`);
    seen.add(sku);
    // Require a catalog entry for every requested SKU.
    const rawEntry = catalog[sku];
    if (!isRecord(rawEntry)) invalid(`Unknown sku ${sku}`);
    // Validate entry fields before calculating a line total.
    const price = rawEntry.price;
    const stock = rawEntry.stock;
    if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) invalid(`Invalid price for ${sku}`);
    if (typeof stock !== 'number' || !Number.isInteger(stock) || stock < 0) invalid(`Invalid stock for ${sku}`);
    // Reject quantities exceeding available inventory.
    if (quantity > stock) invalid(`Quantity exceeds stock for ${sku}`);
    // Round each line and subtotal at the pricing stage boundary.
    const lineTotal = money(price * quantity);
    rows.push({ sku, quantity, unitPrice: price, lineTotal });
    subtotal = money(subtotal + lineTotal);
  }
  // Apply the first discount threshold and add the second cumulatively.
  let reduction = 0;
  if (subtotal >= 100) {
    reduction = money(subtotal * 0.1);
    // Apply the additional five percent only at the higher threshold.
    if (subtotal >= 200) reduction = money(reduction + money(subtotal * 0.05));
  }
  // Calculate tax and shipping from the discounted subtotal.
  const taxable = money(subtotal - reduction);
  const tax = money(taxable * 0.08);
  const shipping = shippingFor(taxable);
  const total = money(taxable + tax + shipping);
  // Return the validated order and all rounded pricing stages.
  return { id: order.id, items: rows, subtotal, discount: reduction, tax, shipping, total };
}

// Produce a deterministic multi-line report for a priced order.
export function formatOrderReport(result: OrderResult): string {
  // Validate the report input before accessing its fields.
  if (!isRecord(result)) invalid('Invalid result: expected an object');
  if (typeof result.id !== 'string') invalid('Invalid result id');
  if (!Array.isArray(result.items)) invalid('Invalid result items');
  // Build the report in a fixed field order.
  const lines = [`Order ${result.id}`];
  for (const item of result.items) {
    // Require each report row to have the expected shape.
    if (!isRecord(item) || typeof item.sku !== 'string' || typeof item.quantity !== 'number' || typeof item.lineTotal !== 'number') {
      invalid('Invalid result item');
    }
    lines.push(itemLabel(item as unknown as PricedItem));
  }
  // Validate monetary totals before formatting them.
  const amounts: Array<[string, unknown]> = [
    ['Subtotal', result.subtotal], ['Discount', result.discount], ['Tax', result.tax],
    ['Shipping', result.shipping], ['Total', result.total],
  ];
  for (const [name, value] of amounts) {
    // Reject non-finite or nonnumeric report amounts.
    if (typeof value !== 'number' || !Number.isFinite(value)) invalid(`Invalid result ${name.toLowerCase()}`);
  }
  // Preserve the established labels and sign for the discount row.
  lines.push(summaryLine('Subtotal', result.subtotal));
  lines.push(`Discount: -${amountLabel(result.discount)}`);
  lines.push(summaryLine('Tax', result.tax));
  lines.push(summaryLine('Shipping', result.shipping));
  lines.push(summaryLine('Total', result.total));
  return lines.join('\n');
}
