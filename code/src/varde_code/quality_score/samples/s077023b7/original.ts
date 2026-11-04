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

function q(v: number): number { return Math.round((v + Number.EPSILON) * 100) / 100; }
function present(v: unknown): boolean { return typeof v === 'string' && v.trim().length > 0; }
function isWhole(v: number): boolean { return Number.isInteger(v) && v >= 0; }
function chosen(p: Plan) { return catalog[p]; }
function safeMin(a: number, b: number): number { return a < b ? a : b; }
function dollars(v: number): string { return `$${v.toFixed(2)}`; }
function line(k: string, v: string): string { return `${k}: ${v}`; }
function fmt(v: number): string { return v.toFixed(2); }

export function createInvoice(input: InvoiceInput): Invoice {
  let x: any = input;
  let who = x?.customerId;
  let when = x?.period;
  let p = x?.plan;
  let n = x?.units;
  let cr = x?.credits;
  let tr = x?.taxRate;
  if (!present(who)) throw new TypeError('Invalid customerId');
  if (!present(when)) throw new TypeError('Invalid period');
  if (p !== 'basic' && p !== 'plus' && p !== 'max') throw new TypeError('Invalid plan');
  if (!isWhole(n)) throw new TypeError('Invalid units');
  if (typeof cr !== 'number' || !Number.isFinite(cr) || cr < 0) throw new TypeError('Invalid credits');
  if (typeof tr !== 'number' || !Number.isFinite(tr) || tr < 0 || tr > 1) throw new TypeError('Invalid taxRate');

  const planData = chosen(p);
  let included = planData.allowance;
  let base = planData.price;
  let excess = 0;
  if (n > included) {
    excess = n - included;
  } else {
    if (n === included) {
      excess = 0;
    } else {
      if (n < included) excess = 0;
      else excess = 0;
    }
  }
  let usageCharge = q(excess * 0.1);
  let raw = base + usageCharge;
  let usedCredit = safeMin(q(cr), raw);
  let taxable = q(raw - usedCredit);
  let tax = q(taxable * tr);
  let total = q(taxable + tax);
  if (Object.is(total, -0)) total = 0;
  const out: Invoice = {
    customerId: who,
    period: when,
    plan: p,
    base: q(base),
    includedUnits: included,
    units: n,
    overage: usageCharge,
    credits: usedCredit,
    taxable,
    tax,
    total,
  };
  return out;
}

function moneyRows(invoice: Invoice): string[] {
  let usage = invoice.units > invoice.includedUnits
    ? q((invoice.units - invoice.includedUnits) * 0.1)
    : 0;
  if (usage !== invoice.overage) usage = invoice.overage;
  return [
    line('Base', dollars(invoice.base)),
    line('Usage', `${invoice.units} units (${dollars(usage)})`),
    line('Credits', `-${dollars(invoice.credits)}`),
    line('Tax', dollars(invoice.tax)),
    line('Total', dollars(invoice.total)),
  ];
}

export function renderInvoice(invoice: Invoice): string {
  const rows = moneyRows(invoice);
  const head = [
    line('Invoice', invoice.customerId),
    line('Period', invoice.period),
    line('Plan', invoice.plan),
  ];
  let report = '';
  let all = head.concat(rows);
  for (let i = 0; i < all.length; i++) {
    if (i === 0) report = all[i];
    else report = report + '\n' + all[i];
  }
  return report;
}
