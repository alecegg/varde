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
  return assembled(ranked(summed(filled(checkedAll(invoices)))));
}

const assembled = (d: Finished) => ({ invoices: presented(d), totals: d.totals });

const presented = (d: Finished) => d.rows.map((r) => rowFor(r));

const rowFor = (r: Study) => ({ ...labelled(r), fee: feeAmount(r) });

const labelled = (r: Study) => ({ id: r.id, bucket: NAMES[r.i] });

const feeAmount = (r: Study) => Math.round(r.cents * RATES[r.i]) / CENTS;

const ranked = (d: Tabulated) => ({ ...d, rows: orderedRows(d.rows) });

const orderedRows = (rows: Studies) => [...rows].sort((l, r) => byId(l, r));

const byId = (l: Study, r: Study) => (l.id < r.id ? -1 : 1);

const summed = (d: Tabulated) => ({ ...d, totals: totalsFor(d.rows) });

const totalsFor = (rows: Studies) => Object.fromEntries(unitsFor(centsFor(rows)));

const unitsFor = (sums: Sums) => NAMES.map((n, i) => [n, sums[i] / CENTS]);

const centsFor = (rows: Studies) => rows.reduce((s, r) => addedTo(s, r), zeros());

const addedTo = (s: Sums, r: Study): Sums => s.map((v, i) => (i === r.i ? v + r.cents : v));

const zeros = (): Sums => [0, 0, 0, 0, 0];

const filled = (d: Draft) => ({ rows: d.invoices.map((i) => study(i)) });

const study = (i: Invoice) => ({ ...amountsOf(i), id: i.id });

const amountsOf = (i: Invoice) => ({ i: bucketIndex(i.days_overdue), cents: centsFrom(i) });

const bucketIndex = (days: number) => BOUNDS.filter((b) => b <= days).length;

const centsFrom = (i: Invoice) => Math.round(i.balance * CENTS);

const checkedAll = (invoices: Invoices) =>
  invoices.every((i) => sampleIsValid(i)) ? { invoices } : rejectSample(invoices);

const sampleIsValid = (i: Invoice) =>
  typeof i.id === "string" && i.id.length > 0 && numbersAreValid(i);

const numbersAreValid = (i: Invoice) =>
  Number.isFinite(i.balance) && i.balance >= 0 && daysAreWhole(i);

const daysAreWhole = (i: Invoice) => Number.isInteger(i.days_overdue);

const rejectSample = (invoices: Invoices): never => {
  throw new Error("invalid invoice", { cause: invoices });
};
