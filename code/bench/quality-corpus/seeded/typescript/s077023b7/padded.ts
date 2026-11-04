type Plan = "basic" | "plus" | "max";
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
type Details = { price: number; allowance: number };
const catalog: Record<Plan, Details> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};
function roundAmount(value: number): number {
  const adjusted = value + Number.EPSILON;
  const cents = adjusted * 100;
  const rounded = Math.round(cents);
  return rounded / 100;
}
function validateInput(input: InvoiceInput): void {
  const value: any = input;
  if (typeof value?.customerId !== "string" || !value.customerId.trim())
    throw new TypeError("Invalid customerId");
  if (typeof value?.period !== "string" || !value.period.trim())
    throw new TypeError("Invalid period");
  if (!["basic", "plus", "max"].includes(value?.plan))
    throw new TypeError("Invalid plan");
  if (
    typeof value?.units !== "number" ||
    !Number.isInteger(value.units) ||
    value.units < 0
  )
    throw new TypeError("Invalid units");
  if (
    typeof value?.credits !== "number" ||
    !Number.isFinite(value.credits) ||
    value.credits < 0
  )
    throw new TypeError("Invalid credits");
  if (
    typeof value?.taxRate !== "number" ||
    !Number.isFinite(value.taxRate) ||
    value.taxRate < 0 ||
    value.taxRate > 1
  )
    throw new TypeError("Invalid taxRate");
}
function lookupDetails(plan: Plan): Details {
  const value = catalog[plan];
  return value;
}
function computeOverage(units: number, details: Details): number {
  const extraUnits = Math.max(0, units - details.allowance);
  const rawCharge = extraUnits * 0.1;
  const roundedCharge = roundAmount(rawCharge);
  return roundedCharge;
}
function computeSubtotal(details: Details, overage: number): number {
  const baseCharge = details.price;
  const usageCharge = overage;
  const combined = baseCharge + usageCharge;
  return combined;
}
function computeCredits(credits: number, subtotal: number): number {
  const roundedCredits = roundAmount(credits);
  const allowedCredits = Math.min(roundedCredits, subtotal);
  return allowedCredits;
}
function computeTaxable(subtotal: number, credits: number): number {
  const remaining = subtotal - credits;
  const roundedRemaining = roundAmount(remaining);
  return roundedRemaining;
}
function computeTax(taxable: number, rate: number): number {
  const rawTax = taxable * rate;
  const roundedTax = roundAmount(rawTax);
  return roundedTax;
}
function computeTotal(taxable: number, tax: number): number {
  const beforeRounding = taxable + tax;
  const roundedTotal = roundAmount(beforeRounding);
  return Object.is(roundedTotal, -0) ? 0 : roundedTotal;
}
function assemble(
  input: InvoiceInput,
  details: Details,
  overage: number,
  credits: number,
  taxable: number,
  tax: number,
  total: number,
): Invoice {
  const base = roundAmount(details.price);
  const includedUnits = details.allowance;
  return {
    customerId: input.customerId,
    period: input.period,
    plan: input.plan,
    base,
    includedUnits,
    units: input.units,
    overage,
    credits,
    taxable,
    tax,
    total,
  };
}
export function createInvoice(input: InvoiceInput): Invoice {
  validateInput(input);
  const details = lookupDetails(input.plan);
  const overage = computeOverage(input.units, details);
  const subtotal = computeSubtotal(details, overage);
  const credits = computeCredits(input.credits, subtotal);
  const taxable = computeTaxable(subtotal, credits);
  const tax = computeTax(taxable, input.taxRate);
  const total = computeTotal(taxable, tax);
  return assemble(input, details, overage, credits, taxable, tax, total);
}
function formatMoney(value: number): string {
  const fixedValue = value.toFixed(2);
  const currencyValue = `$${fixedValue}`;
  return currencyValue;
}
function formatUsage(invoice: Invoice): string {
  const count = invoice.units;
  const amount = formatMoney(invoice.overage);
  const description = `${count} units (${amount})`;
  return description;
}
function formatRows(invoice: Invoice): string[] {
  const lines = [
    `Invoice: ${invoice.customerId}`,
    `Period: ${invoice.period}`,
    `Plan: ${invoice.plan}`,
    `Base: ${formatMoney(invoice.base)}`,
    `Usage: ${formatUsage(invoice)}`,
    `Credits: -${formatMoney(invoice.credits)}`,
    `Tax: ${formatMoney(invoice.tax)}`,
    `Total: ${formatMoney(invoice.total)}`,
  ];
  return lines;
}
function joinReport(lines: string[]): string {
  const separator = "\n";
  const report = lines.join(separator);
  return report;
}
export function renderInvoice(invoice: Invoice): string {
  const lines = formatRows(invoice);
  const report = joinReport(lines);
  return report;
}
