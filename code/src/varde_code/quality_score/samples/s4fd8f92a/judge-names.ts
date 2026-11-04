type CatalogProductEntry = { price: number; stock: number };
type CustomerOrderInput = { id: string; items: Array<{ sku: string; quantity: number }> };
type PricedOrderItem = { sku: string; quantity: number; unitPrice: number; lineTotal: number };
type ProcessedOrderResult = {
  id: string;
  items: PricedOrderItem[];
  subtotal: number;
  discount: number;
  tax: number;
  shipping: number;
  total: number;
};

function roundToCents(amountInDollars: number): number {
  return Math.round((amountInDollars + Number.EPSILON) * 100) / 100;
}

function isNonArrayObject(valueToCheck: unknown): valueToCheck is Record<string, unknown> {
  return typeof valueToCheck === 'object' && valueToCheck !== null && !Array.isArray(valueToCheck);
}

function throwOrderValidationError(errorMessage: string): never {
  throw new Error(errorMessage);
}

function readAndValidateCustomerOrder(orderValue: unknown): CustomerOrderInput {
  if (!isNonArrayObject(orderValue)) throwOrderValidationError('Invalid order: expected an object');
  const orderRecord = orderValue as Record<string, unknown>;
  if (typeof orderRecord.id !== 'string' || orderRecord.id.trim() === '') throwOrderValidationError('Invalid order id');
  if (!Array.isArray(orderRecord.items) || orderRecord.items.length === 0) throwOrderValidationError('Invalid items: expected a nonempty array');
  return orderRecord as unknown as CustomerOrderInput;
}

function readAndValidateProductCatalog(catalogValue: unknown): Record<string, CatalogProductEntry> {
  if (!isNonArrayObject(catalogValue)) throwOrderValidationError('Invalid catalog: expected an object');
  return catalogValue as Record<string, CatalogProductEntry>;
}

function calculateShippingCharge(amountBeforeTax: number): number {
  if (amountBeforeTax >= 150) return 0;
  if (amountBeforeTax >= 50) return 5;
  return 12;
}

function formatDollarAmount(amountInDollars: number): string {
  return `$${amountInDollars.toFixed(2)}`;
}

function formatPricedItemReportLine(pricedItem: PricedOrderItem): string {
  return `${pricedItem.sku} x${pricedItem.quantity}: ${formatDollarAmount(pricedItem.lineTotal)}`;
}

function formatMonetarySummaryReportLine(summaryName: string, amountInDollars: number): string {
  return `${summaryName}: ${formatDollarAmount(amountInDollars)}`;
}

export function processOrder(orderValue: unknown, catalogValue: unknown): ProcessedOrderResult {
  const validatedOrder = readAndValidateCustomerOrder(orderValue);
  const validatedCatalog = readAndValidateProductCatalog(catalogValue);
  const previouslySeenSkuValues: Record<string, boolean> = {};
  const pricedOrderItems: PricedOrderItem[] = [];
  let orderSubtotal = 0;
  for (const rawOrderItem of validatedOrder.items as unknown[]) {
    if (!isNonArrayObject(rawOrderItem)) throwOrderValidationError('Invalid item: expected an object');
    const stockKeepingUnit = rawOrderItem.sku;
    const requestedQuantity = rawOrderItem.quantity;
    if (typeof stockKeepingUnit !== 'string' || stockKeepingUnit.trim() === '') throwOrderValidationError('Invalid item sku');
    if (!Number.isInteger(requestedQuantity) || (requestedQuantity as number) <= 0) throwOrderValidationError(`Invalid quantity for ${stockKeepingUnit}`);
    if (previouslySeenSkuValues[stockKeepingUnit]) throwOrderValidationError(`Duplicate sku ${stockKeepingUnit}`);
    previouslySeenSkuValues[stockKeepingUnit] = true;
    const catalogProduct = validatedCatalog[stockKeepingUnit];
    if (!catalogProduct) throwOrderValidationError(`Unknown sku ${stockKeepingUnit}`);
    if (typeof catalogProduct.price !== 'number' || !Number.isFinite(catalogProduct.price) || catalogProduct.price <= 0) throwOrderValidationError(`Invalid price for ${stockKeepingUnit}`);
    if (!Number.isInteger(catalogProduct.stock) || catalogProduct.stock < 0) throwOrderValidationError(`Invalid stock for ${stockKeepingUnit}`);
    let pricedItemLineTotal = 0;
    if ((requestedQuantity as number) <= catalogProduct.stock) {
      if (catalogProduct.price > 0) {
        if (catalogProduct.price < 10) {
          pricedItemLineTotal = roundToCents(catalogProduct.price * (requestedQuantity as number));
        } else {
          pricedItemLineTotal = roundToCents(catalogProduct.price * (requestedQuantity as number));
        }
      } else {
        throwOrderValidationError(`Invalid price for ${stockKeepingUnit}`);
      }
    } else {
      throwOrderValidationError(`Quantity exceeds stock for ${stockKeepingUnit}`);
    }
    pricedOrderItems.push({ sku: stockKeepingUnit, quantity: requestedQuantity as number, unitPrice: catalogProduct.price, lineTotal: pricedItemLineTotal });
    orderSubtotal = roundToCents(orderSubtotal + pricedItemLineTotal);
  }
  let totalDiscount = 0;
  if (orderSubtotal >= 100) {
    totalDiscount = roundToCents(orderSubtotal * 0.1);
    if (orderSubtotal >= 200) {
      totalDiscount = roundToCents(totalDiscount + roundToCents(orderSubtotal * 0.05));
    }
  }
  const discountedSubtotal = roundToCents(orderSubtotal - totalDiscount);
  const orderTax = roundToCents(discountedSubtotal * 0.08);
  const shippingCalculationBase = roundToCents(orderSubtotal - totalDiscount);
  let shippingCharge = 12;
  if (shippingCalculationBase >= 150) {
    shippingCharge = 0;
  } else {
    if (shippingCalculationBase >= 50) {
      shippingCharge = 5;
    } else {
      if (shippingCalculationBase < 50) {
        shippingCharge = 12;
      }
    }
  }
  const orderTotal = roundToCents(discountedSubtotal + orderTax + shippingCharge);
  return {
    id: validatedOrder.id,
    items: pricedOrderItems,
    subtotal: orderSubtotal,
    discount: totalDiscount,
    tax: orderTax,
    shipping: shippingCharge,
    total: orderTotal,
  };
}

export function formatOrderReport(processedOrder: ProcessedOrderResult): string {
  const reportLines = [`Order ${processedOrder.id}`];
  for (const pricedItem of processedOrder.items) reportLines.push(formatPricedItemReportLine(pricedItem));
  reportLines.push(formatMonetarySummaryReportLine('Subtotal', processedOrder.subtotal));
  reportLines.push(`Discount: -${formatDollarAmount(processedOrder.discount)}`);
  reportLines.push(formatMonetarySummaryReportLine('Tax', processedOrder.tax));
  reportLines.push(formatMonetarySummaryReportLine('Shipping', processedOrder.shipping));
  reportLines.push(formatMonetarySummaryReportLine('Total', processedOrder.total));
  return reportLines.join('\n');
}
