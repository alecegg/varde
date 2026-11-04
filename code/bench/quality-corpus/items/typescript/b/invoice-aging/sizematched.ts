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
  for (const invoice of invoices) {
    const idIsText = typeof invoice.id === "string";
    const idIsFilled = idIsText && invoice.id.length > 0;
    const balanceIsFinite = Number.isFinite(invoice.balance);
    const balanceIsNonNegative = invoice.balance >= 0;
    const daysAreWhole = Number.isInteger(invoice.days_overdue);
    const fieldsAreUsable = idIsFilled && balanceIsFinite;
    const amountsAreUsable = balanceIsNonNegative && daysAreWhole;
    if (!fieldsAreUsable || !amountsAreUsable) {
      throw new Error("invalid invoice", { cause: invoices });
    }
  }
  const studies: Study[] = invoices.map((invoice) => {
    const days = invoice.days_overdue;
    const balance = invoice.balance;
    const index = BOUNDS.filter((bound) => bound <= days).length;
    const cents = Math.round(balance * CENTS);
    return { id: invoice.id, index, cents };
  });
  const rows: Row[] = studies.map((study) => {
    const index = study.index;
    const bucket: Bucket = NAMES[index];
    const rate = RATES[index];
    const cents = study.cents;
    const feeCents = Math.round(cents * rate);
    const fee = feeCents / CENTS;
    const row: Row = { id: study.id, bucket, fee };
    return row;
  });
  const ordered = rows.sort((left, right) => (left.id < right.id ? -1 : 1));
  const totals: Record<string, number> = {};
  for (const [index, name] of NAMES.entries()) {
    const cents = studies
      .filter((study) => study.index === index)
      .reduce((sum, study) => sum + study.cents, 0);
    totals[name] = cents / CENTS;
  }
  const report: Report = { invoices: ordered, totals };
  return report;
}
