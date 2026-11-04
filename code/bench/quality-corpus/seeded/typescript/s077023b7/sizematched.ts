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
const plans: Record<Plan, [number, number]> = {
  basic: [20, 100],
  plus: [50, 500],
  max: [100, 1500],
};
function cents(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}
export function createInvoice(input: InvoiceInput): Invoice {
  const data: any = input;
  const id = data?.customerId;
  const cycle = data?.period;
  const tier = data?.plan;
  const count = data?.units;
  const allowanceCredit = data?.credits;
  const rate = data?.taxRate;
  if (typeof id !== "string" || id.trim().length === 0)
    throw new TypeError("Invalid customerId");
  if (typeof cycle !== "string" || cycle.trim().length === 0)
    throw new TypeError("Invalid period");
  if (tier !== "basic" && tier !== "plus" && tier !== "max")
    throw new TypeError("Invalid plan");
  if (typeof count !== "number" || !Number.isInteger(count) || count < 0)
    throw new TypeError("Invalid units");
  if (
    typeof allowanceCredit !== "number" ||
    !Number.isFinite(allowanceCredit) ||
    allowanceCredit < 0
  )
    throw new TypeError("Invalid credits");
  if (
    typeof rate !== "number" ||
    !Number.isFinite(rate) ||
    rate < 0 ||
    rate > 1
  )
    throw new TypeError("Invalid taxRate");
  const [fixed, cap] = plans[tier];
  const extra = cents(Math.max(0, count - cap) * 0.1);
  const before = fixed + extra;
  const usedCredit = Math.min(cents(allowanceCredit), before);
  const basis = cents(before - usedCredit);
  const duty = cents(basis * rate);
  let due = cents(basis + duty);
  if (Object.is(due, -0)) due = 0;
  return {
    customerId: id,
    period: cycle,
    plan: tier,
    base: cents(fixed),
    includedUnits: cap,
    units: count,
    overage: extra,
    credits: usedCredit,
    taxable: basis,
    tax: duty,
    total: due,
  };
}
export function renderInvoice(item: Invoice): string {
  const amount = item.overage;
  const currency = (n: number) => `$${n.toFixed(2)}`;
  const labels = [
    "Invoice",
    "Period",
    "Plan",
    "Base",
    "Usage",
    "Credits",
    "Tax",
    "Total",
  ];
  const values = [
    item.customerId,
    item.period,
    item.plan,
    currency(item.base),
    `${item.units} units (${currency(amount)})`,
    `-${currency(item.credits)}`,
    currency(item.tax),
    currency(item.total),
  ];
  const output: string[] = [];
  for (let index = 0; index < labels.length; index++)
    output.push(`${labels[index]}: ${values[index]}`);
  return output.join("\n");
}
