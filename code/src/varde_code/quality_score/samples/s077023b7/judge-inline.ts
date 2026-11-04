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

export function createInvoice(input: InvoiceInput): Invoice {
  const values: any = input;
  const customerId = values?.customerId;
  const period = values?.period;
  const plan = values?.plan;
  const units = values?.units;
  const credits = values?.credits;
  const taxRate = values?.taxRate;

  if (typeof customerId !== 'string' || customerId.trim().length === 0) throw new TypeError('Invalid customerId');
  if (typeof period !== 'string' || period.trim().length === 0) throw new TypeError('Invalid period');
  if (plan !== 'basic' && plan !== 'plus' && plan !== 'max') throw new TypeError('Invalid plan');
  if (!Number.isInteger(units) || units < 0) throw new TypeError('Invalid units');
  if (typeof credits !== 'number' || !Number.isFinite(credits) || credits < 0) throw new TypeError('Invalid credits');
  if (typeof taxRate !== 'number' || !Number.isFinite(taxRate) || taxRate < 0 || taxRate > 1) throw new TypeError('Invalid taxRate');

  let base: number;
  let includedUnits: number;
  if (plan === 'basic') {
    base = 20;
    includedUnits = 100;
  } else if (plan === 'plus') {
    base = 50;
    includedUnits = 500;
  } else {
    base = 100;
    includedUnits = 1500;
  }
  const overage = Math.round((Math.max(0, units - includedUnits) * 0.1 + Number.EPSILON) * 100) / 100;
  const preCredit = base + overage;
  const appliedCredits = Math.min(Math.round((credits + Number.EPSILON) * 100) / 100, preCredit);
  const taxable = Math.round((preCredit - appliedCredits + Number.EPSILON) * 100) / 100;
  const tax = Math.round((taxable * taxRate + Number.EPSILON) * 100) / 100;
  let total = Math.round((taxable + tax + Number.EPSILON) * 100) / 100;
  if (Object.is(total, -0)) total = 0;

  return {
    customerId,
    period,
    plan,
    base: Math.round((base + Number.EPSILON) * 100) / 100,
    includedUnits,
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
    ? Math.round(((invoice.units - invoice.includedUnits) * 0.1 + Number.EPSILON) * 100) / 100
    : 0;
  const displayedUsage = usage === invoice.overage ? usage : invoice.overage;
  return [
    `Invoice: ${invoice.customerId}`,
    `Period: ${invoice.period}`,
    `Plan: ${invoice.plan}`,
    `Base: $${invoice.base.toFixed(2)}`,
    `Usage: ${invoice.units} units ($${displayedUsage.toFixed(2)})`,
    `Credits: -$${invoice.credits.toFixed(2)}`,
    `Tax: $${invoice.tax.toFixed(2)}`,
    `Total: $${invoice.total.toFixed(2)}`,
  ].join('\n');
}
