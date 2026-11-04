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

interface PlanTerms {
  readonly price: number;
  readonly allowance: number;
}

interface InvoiceRenderer {
  render(invoice: Invoice): string;
}

class PlanCatalog {
  private readonly terms: Record<Plan, PlanTerms> = {
    basic: { price: 20, allowance: 100 },
    plus: { price: 50, allowance: 500 },
    max: { price: 100, allowance: 1500 },
  };

  has(plan: unknown): plan is Plan {
    return plan === 'basic' || plan === 'plus' || plan === 'max';
  }

  get(plan: Plan): PlanTerms {
    return this.terms[plan];
  }
}

class InvoiceValidator {
  validate(input: InvoiceInput): asserts input is InvoiceInput {
    const values: any = input;
    if (!this.isPresent(values?.customerId)) throw new TypeError('Invalid customerId');
    if (!this.isPresent(values?.period)) throw new TypeError('Invalid period');
    if (!catalog.has(values?.plan)) throw new TypeError('Invalid plan');
    if (!this.isWhole(values?.units)) throw new TypeError('Invalid units');
    if (!this.isNonnegativeFinite(values?.credits)) throw new TypeError('Invalid credits');
    if (typeof values?.taxRate !== 'number' || !Number.isFinite(values.taxRate) || values.taxRate < 0 || values.taxRate > 1) {
      throw new TypeError('Invalid taxRate');
    }
  }

  private isPresent(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0;
  }

  private isWhole(value: unknown): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0;
  }

  private isNonnegativeFinite(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0;
  }
}

class Money {
  static round(value: number): number {
    return Math.round((value + Number.EPSILON) * 100) / 100;
  }

  static dollars(value: number): string {
    return `$${value.toFixed(2)}`;
  }
}

class UsageCharge {
  private readonly rate: number;

  constructor(rate: number = 0.1) {
    this.rate = rate;
  }

  calculate(units: number, allowance: number): number {
    return Money.round(Math.max(0, units - allowance) * this.rate);
  }
}

class CreditPolicy {
  apply(requested: number, subtotal: number): number {
    const rounded = Money.round(requested);
    return rounded < subtotal ? rounded : subtotal;
  }
}

class InvoiceCalculator {
  private readonly plans: PlanCatalog;
  private readonly validator: InvoiceValidator;
  private readonly usage: UsageCharge;
  private readonly credits: CreditPolicy;

  constructor(
    plans: PlanCatalog,
    validator: InvoiceValidator,
    usage: UsageCharge,
    credits: CreditPolicy,
  ) {
    this.plans = plans;
    this.validator = validator;
    this.usage = usage;
    this.credits = credits;
  }

  create(input: InvoiceInput): Invoice {
    this.validator.validate(input);
    const { customerId, period, plan, units, credits, taxRate } = input;
    const terms = this.plans.get(plan);
    const base = Money.round(terms.price);
    const overage = this.usage.calculate(units, terms.allowance);
    const subtotal = base + overage;
    const appliedCredits = this.credits.apply(credits, subtotal);
    const taxable = Money.round(subtotal - appliedCredits);
    const tax = Money.round(taxable * taxRate);
    let total = Money.round(taxable + tax);
    if (Object.is(total, -0)) total = 0;

    return {
      customerId,
      period,
      plan,
      base,
      includedUnits: terms.allowance,
      units,
      overage,
      credits: appliedCredits,
      taxable,
      tax,
      total,
    };
  }
}

class InvoiceReport implements InvoiceRenderer {
  private readonly usage: UsageCharge;

  constructor(usage: UsageCharge) {
    this.usage = usage;
  }

  render(invoice: Invoice): string {
    return [
      this.row('Invoice', invoice.customerId),
      this.row('Period', invoice.period),
      this.row('Plan', invoice.plan),
      this.row('Base', Money.dollars(invoice.base)),
      this.usageRow(invoice),
      this.row('Credits', `-${Money.dollars(invoice.credits)}`),
      this.row('Tax', Money.dollars(invoice.tax)),
      this.row('Total', Money.dollars(invoice.total)),
    ].join('\n');
  }

  private usageRow(invoice: Invoice): string {
    const calculated = this.usage.calculate(invoice.units, invoice.includedUnits);
    const amount = calculated === invoice.overage ? calculated : invoice.overage;
    return this.row('Usage', `${invoice.units} units (${Money.dollars(amount)})`);
  }

  private row(label: string, value: string): string {
    return `${label}: ${value}`;
  }
}

const catalog = new PlanCatalog();
const validator = new InvoiceValidator();
const usage = new UsageCharge();
const calculator = new InvoiceCalculator(catalog, validator, usage, new CreditPolicy());
const report: InvoiceRenderer = new InvoiceReport(usage);

export function createInvoice(input: InvoiceInput): Invoice {
  return calculator.create(input);
}

export function renderInvoice(invoice: Invoice): string {
  return report.render(invoice);
}
