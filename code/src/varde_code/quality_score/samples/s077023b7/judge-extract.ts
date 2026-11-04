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

const catalog = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};

function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function hasText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isWholeNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isMoneyAmount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isTaxRate(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

function isPlan(value: unknown): value is Plan {
  return value === 'basic' || value === 'plus' || value === 'max';
}

function requireCustomerId(value: unknown): string {
  if (!hasText(value)) throw new TypeError('Invalid customerId');
  return value;
}

function requirePeriod(value: unknown): string {
  if (!hasText(value)) throw new TypeError('Invalid period');
  return value;
}

function requirePlan(value: unknown): Plan {
  if (!isPlan(value)) throw new TypeError('Invalid plan');
  return value;
}

function requireUnits(value: unknown): number {
  if (!isWholeNonnegative(value)) throw new TypeError('Invalid units');
  return value;
}

function requireCredits(value: unknown): number {
  if (!isMoneyAmount(value)) throw new TypeError('Invalid credits');
  return value;
}

function requireTaxRate(value: unknown): number {
  if (!isTaxRate(value)) throw new TypeError('Invalid taxRate');
  return value;
}

function readInput(input: InvoiceInput) {
  const values: any = input;
  return {
    customerId: requireCustomerId(values?.customerId),
    period: requirePeriod(values?.period),
    plan: requirePlan(values?.plan),
    units: requireUnits(values?.units),
    credits: requireCredits(values?.credits),
    taxRate: requireTaxRate(values?.taxRate),
  };
}

function planDetails(plan: Plan) {
  return catalog[plan];
}

function overageUnits(units: number, includedUnits: number): number {
  return Math.max(0, units - includedUnits);
}

function overageCharge(units: number, includedUnits: number): number {
  return roundMoney(overageUnits(units, includedUnits) * 0.1);
}

function creditAmount(credits: number, subtotal: number): number {
  return Math.min(roundMoney(credits), subtotal);
}

function taxableAmount(subtotal: number, credits: number): number {
  return roundMoney(subtotal - credits);
}

function taxAmount(taxable: number, taxRate: number): number {
  return roundMoney(taxable * taxRate);
}

function totalAmount(taxable: number, tax: number): number {
  const total = roundMoney(taxable + tax);
  return Object.is(total, -0) ? 0 : total;
}

export function createInvoice(input: InvoiceInput): Invoice {
  const values = readInput(input);
  const details = planDetails(values.plan);
  const overage = overageCharge(values.units, details.allowance);
  const subtotal = details.price + overage;
  const credits = creditAmount(values.credits, subtotal);
  return buildInvoice(values, details, overage, credits, subtotal);
}

function buildInvoice(values: ReturnType<typeof readInput>, details: { price: number; allowance: number }, overage: number, credits: number, subtotal: number): Invoice {
  const taxable = taxableAmount(subtotal, credits);
  const tax = taxAmount(taxable, values.taxRate);
  return {
    customerId: values.customerId,
    period: values.period,
    plan: values.plan,
    base: roundMoney(details.price),
    includedUnits: details.allowance,
    units: values.units,
    overage,
    credits,
    taxable,
    tax,
    total: totalAmount(taxable, tax),
  };
}

function line(label: string, value: string): string {
  return `${label}: ${value}`;
}

function formatMoney(value: number): string {
  return `$${value.toFixed(2)}`;
}

function usageAmount(invoice: Invoice): number {
  return invoice.units > invoice.includedUnits
    ? roundMoney((invoice.units - invoice.includedUnits) * 0.1)
    : 0;
}

function usageLine(invoice: Invoice): string {
  const amount = usageAmount(invoice);
  const charge = amount === invoice.overage ? amount : invoice.overage;
  return line('Usage', `${invoice.units} units (${formatMoney(charge)})`);
}

function invoiceRows(invoice: Invoice): string[] {
  return [
    line('Base', formatMoney(invoice.base)),
    usageLine(invoice),
    line('Credits', `-${formatMoney(invoice.credits)}`),
    line('Tax', formatMoney(invoice.tax)),
    line('Total', formatMoney(invoice.total)),
  ];
}

function invoiceHeader(invoice: Invoice): string[] {
  return [
    line('Invoice', invoice.customerId),
    line('Period', invoice.period),
    line('Plan', invoice.plan),
  ];
}

function invoiceLines(invoice: Invoice): string[] {
  return invoiceHeader(invoice).concat(invoiceRows(invoice));
}

export function renderInvoice(invoice: Invoice): string {
  return invoiceLines(invoice).join('\n');
}
