type Plan = 'basic' | 'plus' | 'max';
type InvoiceInput = {
  customerId: string;
  period: string;
  plan: Plan;
  units: number;
  credits: number;
  taxRate: number;
};
type Invoice = {
  customerId: string;
  period: string;
  plan: Plan;
  base: number;
  includedUnits: number;
  units: number;
  overage: number;
  credits: number;
  taxable: number;
  tax: number;
  total: number;
};

type PlanDetails = { price: number; allowance: number };

// Keep plan prices and allowances together so the calculation uses one catalog entry.
const catalog: Record<Plan, PlanDetails> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};

// Round calculated monetary amounts to cents, including common floating-point boundary cases.
function roundMoney(value: number): number {
  // Reject values that cannot be represented as a finite amount before rounding.
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError('Invalid monetary amount');
  }

  // Normalize negative zero so invoice amounts remain ordinary zero values.
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100;
  return Object.is(rounded, -0) ? 0 : rounded;
}

// Accept only non-empty strings for required identity fields.
function isPresent(value: unknown): value is string {
  // Validate the runtime type before checking string content.
  if (typeof value !== 'string') return false;
  return value.trim().length > 0;
}

// Validate non-negative integer unit counts before usage arithmetic.
function isWholeNonnegative(value: unknown): value is number {
  // Ensure the value is a finite number with no fractional component.
  if (typeof value !== 'number') return false;
  return Number.isInteger(value) && value >= 0;
}

// Convert a monetary value to the report's fixed two-decimal format.
function formatMoney(value: number): string {
  // Refuse malformed invoice fields rather than invoking toFixed on an unexpected value.
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError('Invalid invoice amount');
  }
  return `$${value.toFixed(2)}`;
}

// Format one labeled report row consistently.
function formatLine(label: string, value: string): string {
  // Check both pieces so malformed internal calls fail close to their source.
  if (typeof label !== 'string' || typeof value !== 'string') {
    throw new TypeError('Invalid report line');
  }
  return `${label}: ${value}`;
}

// Build a validated invoice from a caller-provided subscription record.
export function createInvoice(input: InvoiceInput): Invoice {
  // Reject nulls and primitive values before reading invoice properties.
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    throw new TypeError('Invalid invoice input');
  }

  // Read unknown runtime fields so JavaScript callers receive the same validation as TypeScript callers.
  const values = input as unknown as Record<string, unknown>;
  const customerId = values.customerId;
  const period = values.period;
  const plan = values.plan;
  const units = values.units;
  const credits = values.credits;
  const taxRate = values.taxRate;

  // Check required identity values before using them in the result.
  if (!isPresent(customerId)) throw new TypeError('Invalid customerId');
  if (!isPresent(period)) throw new TypeError('Invalid period');

  // Limit plan lookup to the supported catalog keys.
  if (plan !== 'basic' && plan !== 'plus' && plan !== 'max') {
    throw new TypeError('Invalid plan');
  }

  // Reject invalid quantities and monetary inputs before performing calculations.
  if (!isWholeNonnegative(units)) throw new TypeError('Invalid units');
  if (typeof credits !== 'number' || !Number.isFinite(credits) || credits < 0) {
    throw new TypeError('Invalid credits');
  }
  if (typeof taxRate !== 'number' || !Number.isFinite(taxRate) || taxRate < 0 || taxRate > 1) {
    throw new TypeError('Invalid taxRate');
  }

  // Derive plan charges and included units from the validated catalog entry.
  const planDetails = catalog[plan];
  const excessUnits = Math.max(0, units - planDetails.allowance);
  const overage = roundMoney(excessUnits * 0.1);
  const base = roundMoney(planDetails.price);

  // Apply credits after usage charges and cap them at the pre-credit subtotal.
  const beforeCredits = roundMoney(base + overage);
  const appliedCredits = Math.min(roundMoney(credits), beforeCredits);
  const taxable = roundMoney(beforeCredits - appliedCredits);

  // Apply tax to the post-credit amount and calculate the final invoice total.
  const tax = roundMoney(taxable * taxRate);
  const total = roundMoney(taxable + tax);

  // Return all documented invoice fields using the validated inputs and rounded amounts.
  return {
    customerId,
    period,
    plan,
    base,
    includedUnits: planDetails.allowance,
    units,
    overage,
    credits: appliedCredits,
    taxable,
    tax,
    total,
  };
}

// Render monetary rows and preserve the original unit count in the usage description.
function moneyRows(invoice: Invoice): string[] {
  // Require an object before reading its report fields.
  if (typeof invoice !== 'object' || invoice === null || Array.isArray(invoice)) {
    throw new TypeError('Invalid invoice');
  }

  // Validate count fields and amounts needed to compose the rows.
  if (!isWholeNonnegative(invoice.units) || !isWholeNonnegative(invoice.includedUnits)) {
    throw new TypeError('Invalid invoice units');
  }
  if (typeof invoice.overage !== 'number' || !Number.isFinite(invoice.overage) || invoice.overage < 0) {
    throw new TypeError('Invalid invoice overage');
  }

  // Use the stored charge as authoritative, while checking that all displayed amounts are valid.
  const usage = invoice.overage;
  const base = formatMoney(invoice.base);
  const credits = formatMoney(invoice.credits);
  const tax = formatMoney(invoice.tax);
  const total = formatMoney(invoice.total);

  // Keep the report's monetary rows in the required order.
  return [
    formatLine('Base', base),
    formatLine('Usage', `${invoice.units} units (${formatMoney(usage)})`),
    formatLine('Credits', `-${credits}`),
    formatLine('Tax', tax),
    formatLine('Total', total),
  ];
}

// Render a complete invoice report in the required line order.
export function renderInvoice(invoice: Invoice): string {
  // Reject missing or malformed invoice objects before reading their identity fields.
  if (typeof invoice !== 'object' || invoice === null || Array.isArray(invoice)) {
    throw new TypeError('Invalid invoice');
  }
  if (!isPresent(invoice.customerId)) throw new TypeError('Invalid customerId');
  if (!isPresent(invoice.period)) throw new TypeError('Invalid period');
  if (invoice.plan !== 'basic' && invoice.plan !== 'plus' && invoice.plan !== 'max') {
    throw new TypeError('Invalid plan');
  }

  // Combine identity and monetary rows in the documented report order.
  const header = [
    formatLine('Invoice', invoice.customerId),
    formatLine('Period', invoice.period),
    formatLine('Plan', invoice.plan),
  ];
  return header.concat(moneyRows(invoice)).join('\n');
}
