const CENTS = 100;
const RATES = [0, 0.02, 0.05, 0.08, 0.1];
const BOUNDS = [1, 31, 61, 91];

type Invoice = { id: string; days_overdue: number; balance: number };

type Bucket = "current" | "1-30" | "31-60" | "61-90" | "over-90";

type Row = { id: string; bucket: Bucket; fee: number };

type Report = { invoices: Row[]; totals: Record<string, number> };

const NAMES: Bucket[] = ["current", "1-30", "31-60", "61-90", "over-90"];

type Invoices = Invoice[];

type Study = { id: string; index: number; cents: number };

/** Build an invoice aging report with each invoice bucket and fee, plus the balance totals. */
export function solution(invoices: Invoices): Report {
  requireInvoices(invoices);
  const studies = tabulate(invoices);
  const rows = studies.map((study) => rowOf(study));
  const ordered = rows.sort((left, right) => (left.id < right.id ? -1 : 1));
  const totals = totalsOf(studies);
  const report: Report = { invoices: ordered, totals };
  return report;
}

function requireInvoices(invoices: Invoices) {
  for (const invoice of invoices) {
    const idOk = typeof invoice.id === "string" && invoice.id.length > 0;
    const moneyOk = Number.isFinite(invoice.balance) && invoice.balance >= 0;
    if (!idOk || !moneyOk || !Number.isInteger(invoice.days_overdue)) {
      throw new Error("invalid invoice", { cause: invoices });
    }
  }
}

function tabulate(invoices: Invoice[]): Study[] {
  return invoices.map((invoice) => {
    const index = BOUNDS.filter((bound) => bound <= invoice.days_overdue).length;
    const cents = Math.round(invoice.balance * CENTS);
    return { id: invoice.id, index, cents };
  });
}

function rowOf(study: Study): Row {
  const bucket = NAMES[study.index];
  const fee = Math.round(study.cents * RATES[study.index]) / CENTS;
  return { id: study.id, bucket, fee };
}

function totalsOf(studies: Study[]): Record<string, number> {
  const sums = [0, 0, 0, 0, 0];
  for (const study of studies) {
    sums[study.index] += study.cents;
  }
  const totals: Record<string, number> = {};
  for (const [index, name] of NAMES.entries()) {
    totals[name] = sums[index] / CENTS;
  }
  return totals;
}
