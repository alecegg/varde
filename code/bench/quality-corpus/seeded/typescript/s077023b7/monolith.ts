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
const catalog: Record<Plan, { price: number; allowance: number }> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};
export function createInvoice(input: InvoiceInput): Invoice {
  const values: any = input;
  const customerId = values?.customerId;
  const period = values?.period;
  const plan = values?.plan;
  const units = values?.units;
  const credits = values?.credits;
  const taxRate = values?.taxRate;
  if (!(typeof customerId === "string" && customerId.trim().length > 0))
    throw new TypeError("Invalid customerId");
  if (!(typeof period === "string" && period.trim().length > 0))
    throw new TypeError("Invalid period");
  if (!(plan === "basic" || plan === "plus" || plan === "max"))
    throw new TypeError("Invalid plan");
  if (!(typeof units === "number" && Number.isInteger(units) && units >= 0))
    throw new TypeError("Invalid units");
  if (!(
    typeof credits === "number" &&
    Number.isFinite(credits) &&
    credits >= 0
  ))
    throw new TypeError("Invalid credits");
  if (!(
    typeof taxRate === "number" &&
    Number.isFinite(taxRate) &&
    taxRate >= 0 &&
    taxRate <= 1
  ))
    throw new TypeError("Invalid taxRate");
  const details = catalog[plan];
  const overage =
    Math.round(
      (Math.max(0, units - details.allowance) * 0.1 + Number.EPSILON) * 100,
    ) / 100;
  const subtotal = details.price + overage;
  const appliedCredits = Math.min(
    Math.round((credits + Number.EPSILON) * 100) / 100,
    subtotal,
  );
  const taxable =
    Math.round((subtotal - appliedCredits + Number.EPSILON) * 100) / 100;
  const tax = Math.round((taxable * taxRate + Number.EPSILON) * 100) / 100;
  let total = Math.round((taxable + tax + Number.EPSILON) * 100) / 100;
  if (Object.is(total, -0)) total = 0;
  return {
    customerId,
    period,
    plan,
    base: Math.round((details.price + Number.EPSILON) * 100) / 100,
    includedUnits: details.allowance,
    units,
    overage,
    credits: appliedCredits,
    taxable,
    tax,
    total,
  };
}
export function renderInvoice(invoice: Invoice): string {
  const usage =
    invoice.units > invoice.includedUnits
      ? Math.round(
          ((invoice.units - invoice.includedUnits) * 0.1 + Number.EPSILON) *
            100,
        ) / 100
      : 0;
  const usageCharge = usage === invoice.overage ? usage : invoice.overage;
  const baseText = `$${invoice.base.toFixed(2)}`;
  const usageText = `${invoice.units} units ($${usageCharge.toFixed(2)})`;
  const creditText = `-$${invoice.credits.toFixed(2)}`;
  const taxText = `$${invoice.tax.toFixed(2)}`;
  const totalText = `$${invoice.total.toFixed(2)}`;
  const lines = [
    `Invoice: ${invoice.customerId}`,
    `Period: ${invoice.period}`,
    `Plan: ${invoice.plan}`,
    `Base: ${baseText}`,
    `Usage: ${usageText}`,
    `Credits: ${creditText}`,
    `Tax: ${taxText}`,
    `Total: ${totalText}`,
  ];
  return lines.join("\n");
}
