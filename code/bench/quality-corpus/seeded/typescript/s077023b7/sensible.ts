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

const catalog: Record<Plan, { price: number; allowance: number }> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};

function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function isNonblankString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isPlan(value: unknown): value is Plan {
  return value === 'basic' || value === 'plus' || value === 'max';
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function formatMoney(value: number): string {
  return `$${value.toFixed(2)}`;
}

function formatLine(label: string, value: string): string {
  return `${label}: ${value}`;
}

export function createInvoice(input: InvoiceInput): Invoice {
  const values: any = input;
  const customerId = values?.customerId;
  const period = values?.period;
  const plan = values?.plan;
  const units = values?.units;
  const credits = values?.credits;
  const taxRate = values?.taxRate;

  if (!isNonblankString(customerId)) throw new TypeError('Invalid customerId');
  if (!isNonblankString(period)) throw new TypeError('Invalid period');
  if (!isPlan(plan)) throw new TypeError('Invalid plan');
  if (!isNonnegativeInteger(units)) throw new TypeError('Invalid units');
  if (typeof credits !== 'number' || !Number.isFinite(credits) || credits < 0) {
    throw new TypeError('Invalid credits');
  }
  if (typeof taxRate !== 'number' || !Number.isFinite(taxRate) || taxRate < 0 || taxRate > 1) {
    throw new TypeError('Invalid taxRate');
  }

  const planDetails = catalog[plan];
  const overage = roundMoney(Math.max(0, units - planDetails.allowance) * 0.1);
  const subtotal = planDetails.price + overage;
  const appliedCredits = Math.min(roundMoney(credits), subtotal);
  const taxable = roundMoney(subtotal - appliedCredits);
  const tax = roundMoney(taxable * taxRate);
  let total = roundMoney(taxable + tax);
  if (Object.is(total, -0)) total = 0;

  return {
    customerId,
    period,
    plan,
    base: roundMoney(planDetails.price),
    includedUnits: planDetails.allowance,
    units,
    overage,
    credits: appliedCredits,
    taxable,
    tax,
    total,
  };
}

export function renderInvoice(invoice: Invoice): string {
  const usage = invoice.units > invoice.includedUnits
    ? roundMoney((invoice.units - invoice.includedUnits) * 0.1)
    : 0;
  const usageCharge = usage === invoice.overage ? usage : invoice.overage;

  return [
    formatLine('Invoice', invoice.customerId),
    formatLine('Period', invoice.period),
    formatLine('Plan', invoice.plan),
    formatLine('Base', formatMoney(invoice.base)),
    formatLine('Usage', `${invoice.units} units (${formatMoney(usageCharge)})`),
    formatLine('Credits', `-${formatMoney(invoice.credits)}`),
    formatLine('Tax', formatMoney(invoice.tax)),
    formatLine('Total', formatMoney(invoice.total)),
  ].join('\n');
}
