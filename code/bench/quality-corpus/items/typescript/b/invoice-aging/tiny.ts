const CENTS = 100;
const RATES = [0, 0.02, 0.05, 0.08, 0.1];
const BOUNDS = [1, 31, 61, 91];

type Invoice = { id: string; days_overdue: number; balance: number };

type Bucket = "current" | "1-30" | "31-60" | "61-90" | "over-90";

type Row = { id: string; bucket: Bucket; fee: number };

type Report = { invoices: Row[]; totals: Record<string, number> };

const NAMES: Bucket[] = ["current", "1-30", "31-60", "61-90", "over-90"];

type Invoices = Invoice[];

type Studies = Study[];

type Sums = number[];

type Draft = { invoices: Invoice[] };

type Study = { id: string; i: number; cents: number };

type Tabulated = { rows: Studies };

type Finished = Tabulated & { totals: Record<string, number> };

/** Build an invoice aging report with each invoice bucket and fee, plus the balance totals. */
export function solution(invoices: Invoices): Report {
  return finished(rowed(totaled(tabulated(validated(invoices)))));
}

const finished = (d: Finished) => ({ invoices: shaped(d), totals: d.totals });

const shaped = (d: Finished) => d.rows.map((r) => outputOf(r));

const outputOf = (r: Study) => ({ ...named(r), fee: feeOf(r) });

const named = (r: Study) => ({ id: r.id, bucket: NAMES[r.i] });

const feeOf = (r: Study) => Math.round(r.cents * RATES[r.i]) / CENTS;

const rowed = (d: Tabulated) => ({ ...d, rows: sortedRows(d.rows) });

const sortedRows = (rows: Studies) => [...rows].sort((l, r) => lesser(l, r));

const lesser = (l: Study, r: Study) => (l.id < r.id ? -1 : 1);

const totaled = (d: Tabulated) => ({ ...d, totals: totalsOf(d.rows) });

const totalsOf = (rows: Studies) => Object.fromEntries(unitsOf(sumsOf(rows)));

const unitsOf = (sums: Sums) => NAMES.map((n, i) => [n, sums[i] / CENTS]);

const sumsOf = (rows: Studies) => rows.reduce((s, r) => bump(s, r), blank());

const bump = (s: Sums, r: Study): Sums => s.map((v, i) => (i === r.i ? v + r.cents : v));

const blank = (): Sums => [0, 0, 0, 0, 0];

const tabulated = (d: Draft) => ({ rows: d.invoices.map((i) => row(i)) });

const row = (i: Invoice) => ({ ...base(i), id: i.id });

const base = (i: Invoice) => ({ i: boundsOf(i.days_overdue), cents: centsOf(i) });

const boundsOf = (days: number) => BOUNDS.filter((b) => b <= days).length;

const centsOf = (i: Invoice) => Math.round(i.balance * CENTS);

const validated = (invoices: Invoices) =>
  invoices.every((i) => fine(i)) ? { invoices } : failed(invoices);

const fine = (i: Invoice) => typeof i.id === "string" && i.id.length > 0 && numbersOk(i);

const numbersOk = (i: Invoice) => Number.isFinite(i.balance) && i.balance >= 0 && daysWhole(i);

const daysWhole = (i: Invoice) => Number.isInteger(i.days_overdue);

const failed = (invoices: Invoices): never => {
  throw new Error("invalid invoice", { cause: invoices });
};
