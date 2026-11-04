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
  return composed(tidied(accumulated(drafted(checked(invoices)))));
}

function composed(d: Finished): Report {
  const invoices = listed(d);
  const report: Report = { invoices, totals: d.totals };
  return report;
}

function listed(d: Finished): Row[] {
  const rows = d.rows.map((r) => expressed(r));
  return rows;
}

function expressed(r: Study): Row {
  const fee = feeInUnits(r);
  const columns = captioned(r);
  const row: Row = { ...columns, fee };
  return row;
}

function captioned(r: Study): { id: string; bucket: Bucket } {
  const bucket = NAMES[r.i];
  const columns = { id: r.id, bucket };
  return columns;
}

function feeInUnits(r: Study): number {
  const rate = RATES[r.i];
  const cents = r.cents * rate;
  const rounded = Math.round(cents);
  const fee = rounded / CENTS;
  return fee;
}

function tidied(d: Tabulated): Tabulated {
  const rows = sortedStudies(d.rows);
  const ordered: Tabulated = { ...d, rows };
  return ordered;
}

function sortedStudies(rows: Studies): Studies {
  const copy: Studies = [...rows];
  copy.sort((l, r) => byIdentifier(l, r));
  return copy;
}

function byIdentifier(l: Study, r: Study): number {
  const ahead = l.id < r.id;
  if (ahead) {
    return -1;
  }
  return 1;
}

function accumulated(d: Tabulated): Tabulated {
  const totals = totalsFrom(d.rows);
  const complete: Tabulated = { ...d, totals };
  return complete;
}

function totalsFrom(rows: Studies): Record<string, number> {
  const units = unitsFrom(centsFrom(rows));
  const totals = Object.fromEntries(units);
  return totals;
}

function unitsFrom(sums: Sums): [string, number][] {
  const pairs = NAMES.map((n, i) => [n, sums[i] / CENTS]);
  return pairs;
}

function centsFrom(rows: Studies): Sums {
  const sums = zeros();
  for (const row of rows) {
    bumpInto(sums, row);
  }
  return sums;
}

function bumpInto(s: Sums, r: Study): Sums {
  const index = r.i;
  const cents = r.cents;
  s[index] += cents;
  return s;
}

function zeros(): Sums {
  const sums: Sums = [];
  for (let index = 0; index < NAMES.length; index = index + 1) {
    sums.push(0);
  }
  return sums;
}

function drafted(d: Draft): Tabulated {
  const rows = d.invoices.map((i) => studyOf(i));
  const tabulated: Tabulated = { rows };
  return tabulated;
}

function studyOf(i: Invoice): Study {
  const amounts = amountsOf(i);
  const study: Study = { ...amounts, id: i.id };
  return study;
}

function amountsOf(i: Invoice): { i: number; cents: number } {
  const days = i.days_overdue;
  const index = indexOfDays(days);
  const cents = balanceCents(i);
  return { i: index, cents };
}

function indexOfDays(days: number): number {
  const passed = BOUNDS.filter((bound) => bound <= days);
  const count = passed.length;
  return count;
}

function balanceCents(i: Invoice): number {
  const balance = i.balance;
  const scaled = balance * CENTS;
  const cents = Math.round(scaled);
  return cents;
}

function checked(invoices: Invoices): Draft {
  const usable = invoices.every((invoice) => sampleOk(invoice));
  if (!usable) {
    rejectSample(invoices);
  }
  const draft: Draft = { invoices };
  return draft;
}

function sampleOk(i: Invoice): boolean {
  const named = typeof i.id === "string" && i.id.length > 0;
  const figures = figuresOk(i);
  const usable = named && figures;
  return usable;
}

function figuresOk(i: Invoice): boolean {
  const balance = i.balance;
  const days = i.days_overdue;
  const finite = Number.isFinite(balance);
  const nonNegative = balance >= 0;
  const whole = wholeDays(days);
  return finite && nonNegative && whole;
}

function wholeDays(days: number): boolean {
  const truncated = Math.trunc(days);
  const whole = truncated === days;
  const finite = Number.isFinite(days);
  return whole && finite;
}

function rejectSample(invoices: Invoices): never {
  const detail = { cause: invoices };
  throw new Error("invalid invoice", detail);
}
